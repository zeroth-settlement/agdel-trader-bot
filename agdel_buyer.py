"""AGDEL signal buyer — MCP-first integration with agent-deliberation.net.

Simplified from trader-bot-basic: no CxU, no complex scoring weights.
Core MCP buying + X25519 decryption + budget tracking.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from persistence import DATA_DIR, append_jsonl, load_jsonl, rewrite_jsonl
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger("agdel_buyer")

ALG_ID = "x25519-aes256gcm"
HKDF_INFO = b"agdel-signal-delivery"

_HORIZON_RANGES: list[tuple[int, int, str]] = [
    (45, 90, "1m"),
    (240, 450, "5m"),
    (800, 1200, "15m"),
    (1500, 2400, "30m"),
    (3000, 5400, "1h"),
]

# Minimum seconds remaining before we attempt to buy a signal for each horizon.
# The AGDEL buying window closes well before expiry — roughly 50% of signal lifetime
# for short horizons. These thresholds prevent wasting purchase attempts.
_MIN_REMAINING_SECS: dict[str, int] = {
    "1m": 20,
    "5m": 90,
    "15m": 90,
    "30m": 120,
    "1h": 120,
}


@dataclass
class BudgetTracker:
    max_per_signal: float
    max_hourly: float
    max_daily: float
    _hourly_spend: float = 0.0
    _daily_spend: float = 0.0
    _hourly_reset: float = field(default_factory=time.time)
    _daily_reset: float = field(default_factory=time.time)

    def can_spend(self, cost: float) -> tuple[bool, str]:
        now = time.time()
        if now - self._hourly_reset > 3600:
            self._hourly_spend = 0.0
            self._hourly_reset = now
        if now - self._daily_reset > 86400:
            self._daily_spend = 0.0
            self._daily_reset = now
        if cost > self.max_per_signal:
            return False, f"cost ${cost:.2f} > max ${self.max_per_signal:.2f}"
        if self._hourly_spend + cost > self.max_hourly:
            return False, f"hourly limit exceeded"
        if self._daily_spend + cost > self.max_daily:
            return False, f"daily limit exceeded"
        return True, ""

    def record(self, cost: float):
        self._hourly_spend += cost
        self._daily_spend += cost

    def status(self) -> dict:
        return {
            "hourlySpend": round(self._hourly_spend, 2),
            "hourlyLimit": self.max_hourly,
            "dailySpend": round(self._daily_spend, 2),
            "dailyLimit": self.max_daily,
        }


def _classify_horizon(duration_seconds: float) -> str | None:
    for min_s, max_s, label in _HORIZON_RANGES:
        if min_s <= duration_seconds <= max_s:
            return label
    return None


def decrypt_delivery(
    envelope: dict,
    buyer_private_key: X25519PrivateKey,
    commitment_hash: str,
    buyer_address: str,
    maker_address: str,
) -> dict:
    """Decrypt an AGDEL delivery envelope."""
    ephemeral_pub = X25519PublicKey.from_public_bytes(
        base64.b64decode(envelope["ephemeral_pubkey_b64"])
    )
    shared_secret = buyer_private_key.exchange(ephemeral_pub)
    derived_key = HKDF(
        algorithm=SHA256(), length=32,
        salt=None, info=HKDF_INFO,
    ).derive(shared_secret)
    nonce = base64.b64decode(envelope["nonce_b64"])
    ciphertext = base64.b64decode(envelope["ciphertext_b64"])
    plaintext = AESGCM(derived_key).decrypt(nonce, ciphertext, None)
    return json.loads(plaintext)


class AgdelBuyer:
    """MCP-first AGDEL signal buyer."""

    def __init__(self, config: dict):
        ac = config.get("agdel", {})
        self.enabled: bool = ac.get("enabled", True)
        self.auto_buy: bool = ac.get("autoBuy", False)
        self.poll_interval: int = ac.get("pollIntervalSeconds", 30)
        self.api_url: str = ac.get("apiUrl", "https://agent-deliberation.net/api")
        self.assets: list[str] = ac.get("assets", ["ETH"])
        self.fetch_limit: int = ac.get("selection", {}).get("fetchLimit", 100)

        sp = config.get("signalProcessing", {})
        self.invert_direction: bool = sp.get("invertSignalDirection", False)
        self.score_multiplier: float = sp.get("scoreMultiplier", 1.0)

        budget = ac.get("budget", {})
        self.budget = BudgetTracker(
            max_per_signal=budget.get("maxCostPerSignalUsdc", 2.0),
            max_hourly=budget.get("maxHourlySpendUsdc", 10.0),
            max_daily=budget.get("maxDailySpendUsdc", 50.0),
        )

        sel = ac.get("selection", {})
        self.min_confidence: float = sel.get("minSignalConfidence", 0.2)
        self.target_horizons: dict[str, int] = sel.get("targetHorizons", {"5m": 1, "15m": 1})

        mf = ac.get("makerFilters", {})
        self.min_maker_win_rate: float = mf.get("minWinRate", 0.3)
        self.min_maker_signals: int = mf.get("minTotalSignals", 5)
        self.allowed_signal_types: set[str] = set(mf.get("allowedSignalTypes", []))
        self.blocked_signal_types: set[str] = set(mf.get("blockedSignalTypes", []))
        self.blocked_makers: set[str] = set(mf.get("blockedMakers", []))
        self.preferred_makers: set[str] = set(mf.get("preferredMakers", []))

        exc = ac.get("exchange", {})
        self.delivery_poll_seconds: int = exc.get("deliveryPollSeconds", 1)
        self.delivery_timeout: int = exc.get("deliveryTimeoutSeconds", 60)
        self.key_file_path: str = exc.get("keyFilePath", "data/buyer_exchange_key.bin")

        webhook_base = os.environ.get("TRADERBOT_WEBHOOK_BASE_URL", "")
        if webhook_base:
            self.webhook_url = webhook_base.rstrip("/") + "/api/agdel/webhook/delivery"
        else:
            self.webhook_url = exc.get("webhookUrl", "")

        self._rpc_url: str = os.environ.get("AGDEL_RPC_URL", "https://rpc.hyperliquid.xyz/evm")
        self._usdc_address: str = os.environ.get(
            "AGDEL_USDC_ADDRESS", "0xb88339cb7199b77e23db6e890353e22632ba630f"
        )
        self._usdc_balance: float = 0.0

        self.auto_buy_cooldown: int = ac.get("autoBuyCooldownSeconds", 180)
        self.outlier_cc_multiplier: float = ac.get("outlierCcMultiplier", 1.25)

        self.signals: dict[str, list[dict]] = {}  # horizon → list of active signals
        self._purchase_log_path = DATA_DIR / "purchase_log.jsonl"
        self.purchase_log: deque[dict] = load_jsonl(self._purchase_log_path, maxlen=200)
        self.purchased_hashes: set[str] = {
            e["commitment_hash"] for e in self.purchase_log if e.get("commitment_hash")
        }
        self.available_signals: list[dict] = []
        self._last_buy_at: dict[str, float] = {}
        self._mcp_session: Any = None
        self._mcp_context: Any = None
        self._mcp_process: Any = None  # subprocess for HTTP-transport MCP server
        self._consecutive_errors: int = 0
        self._buyer_private_key: X25519PrivateKey | None = None
        self._buyer_public_key_b64: str = ""
        self._buyer_address: str = ""
        self._pending_deliveries: dict[str, dict] = {}
        self._delivered_hashes: set[str] = {
            e["commitment_hash"] for e in self.purchase_log
            if e.get("delivered") and e.get("commitment_hash")
        }
        self._maker_cache: dict[str, dict] = {}
        self._usdc_last_refresh: float = 0.0
        self._delivery_log_path = Path("logs/delivery_metrics.jsonl")
        self._delivery_times: deque[float] = deque(maxlen=100)  # recent delivery times for stats
        self._stats = {
            "polls": 0, "purchases": 0, "deliveries": 0,
            "errors": 0, "lastPollAt": None,
            "delivery_avg_s": 0.0, "delivery_max_s": 0.0,
            "delivery_expired": 0, "delivery_timeout": 0,
        }

    def _persist_purchase(self, entry: dict):
        """Append a new purchase entry to log and disk."""
        self.purchase_log.appendleft(entry)
        append_jsonl(self._purchase_log_path, entry)

    def _persist_purchase_log(self):
        """Rewrite the full purchase log to capture in-place updates."""
        rewrite_jsonl(self._purchase_log_path, list(self.purchase_log))

    async def start(self):
        if not self.enabled:
            logger.info("AGDEL buyer disabled")
            return

        self._buyer_address = os.environ.get("TRADERBOT_WALLET_ADDRESS", "")
        if not self._buyer_address:
            self._buyer_address = self._derive_address_from_key()
        if not self._buyer_address:
            self._buyer_address = os.environ.get("HYPERLIQUID_WALLET_ADDRESS", "")

        logger.info("AGDEL buyer address: %s", self._buyer_address)
        self._load_or_generate_keypair()
        await self._refresh_usdc_balance()
        await self._connect_mcp()

        if self._mcp_session:
            try:
                register_args = {
                    "algorithm": ALG_ID,
                    "public_key_b64": self._buyer_public_key_b64,
                }
                if self.webhook_url:
                    register_args["webhook_url"] = self.webhook_url
                await self._call_tool("agdel_exchange_register_key", register_args)
                logger.info("Registered buyer encryption key")
            except Exception as e:
                logger.warning("Failed to register encryption key: %s", e)

    async def stop(self):
        if self._mcp_session:
            try:
                await self._mcp_session.__aexit__(None, None, None)
            except Exception:
                pass
        if self._mcp_context:
            try:
                await self._mcp_context.__aexit__(None, None, None)
            except Exception:
                pass
        if self._mcp_process:
            try:
                self._mcp_process.terminate()
                await self._mcp_process.wait()
            except Exception:
                pass

    async def _connect_mcp(self):
        """Connect to the AGDEL MCP server via Streamable HTTP transport.

        Launches the MCP server as a subprocess, waits for it to be ready,
        then connects via HTTP.
        """
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            server_path = os.environ.get("AGDEL_MCP_PATH", "")
            mcp_port = int(os.environ.get("MCP_SERVER_PORT", "3000"))

            env = {
                **os.environ,
                "MCP_SERVER_PORT": str(mcp_port),
                "AGDEL_API_URL": self.api_url,
                "AGDEL_SIGNER_PRIVATE_KEY": (
                    os.environ.get("AGDEL_PRIVATE_KEY")
                    or os.environ.get("TRADERBOT_WALLET_PRIVATE_KEY", "")
                ),
                "MARKETPLACE_ADDRESS": os.environ.get(
                    "AGDEL_MARKETPLACE_ADDRESS", "0x1779255c0AcDe950095C9E872B2fAD06CFB88D4c"
                ),
                "AGDEL_RPC_URL": os.environ.get(
                    "AGDEL_RPC_URL", "https://rpc.hyperliquid.xyz/evm"
                ),
                "AGDEL_ONCHAIN": "1",
            }

            if server_path:
                cmd = ["npx", "tsx", "mcp/server.ts"]
                cwd = server_path
            else:
                cmd = ["npx", "-y", "agdel-mcp"]
                cwd = None

            # Launch MCP server as a subprocess
            self._mcp_process = await asyncio.create_subprocess_exec(
                *cmd, cwd=cwd, env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            logger.info("MCP server subprocess started (pid=%d, port=%d)", self._mcp_process.pid, mcp_port)

            # Wait for server to be ready via health endpoint
            mcp_url = f"http://localhost:{mcp_port}/mcp"
            health_url = f"http://localhost:{mcp_port}/health"
            ready = False
            for attempt in range(30):
                await asyncio.sleep(1)
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(health_url, timeout=3)
                        if resp.status_code == 200:
                            ready = True
                            break
                except Exception:
                    pass
                # Check if process died
                if self._mcp_process.returncode is not None:
                    stderr_out = await self._mcp_process.stderr.read()
                    logger.error("MCP server died during startup: %s", stderr_out.decode()[-500:])
                    return
            if not ready:
                logger.error("MCP server did not become ready after 30s")
                return

            logger.info("MCP server ready at %s", mcp_url)
            self._mcp_context = streamablehttp_client(url=mcp_url)
            read_stream, write_stream, _ = await self._mcp_context.__aenter__()
            self._mcp_session = ClientSession(read_stream, write_stream)
            await self._mcp_session.__aenter__()
            await self._mcp_session.initialize()
            logger.info("MCP session initialized (Streamable HTTP)")

        except ImportError:
            logger.error("mcp package not installed. Run: pip install mcp")
        except Exception as e:
            logger.error("Failed to connect MCP server: %s", e)
            self._mcp_session = None

    async def _call_tool(self, tool_name: str, arguments: dict | None = None) -> Any:
        if not self._mcp_session:
            raise RuntimeError("MCP session not connected")
        result = await self._mcp_session.call_tool(tool_name, arguments or {})
        if getattr(result, "isError", False):
            texts = []
            if hasattr(result, "content") and result.content:
                for block in result.content:
                    if hasattr(block, "text"):
                        texts.append(block.text)
            raise RuntimeError(f"{tool_name}: {' | '.join(texts)}")
        if hasattr(result, "content") and result.content:
            for block in result.content:
                if hasattr(block, "text"):
                    try:
                        return json.loads(block.text)
                    except json.JSONDecodeError:
                        return block.text
        return result

    async def poll_once(self) -> list[dict]:
        if not self._mcp_session:
            # Try to reconnect if session is dead
            logger.warning("MCP session not connected, attempting reconnect...")
            await self._reconnect_mcp()
            if not self._mcp_session:
                return []
        self._prune_expired_signals()
        self._stats["polls"] += 1
        self._stats["lastPollAt"] = time.time()
        purchased = []
        # Refresh USDC balance at most every 60s to avoid adding latency
        if time.time() - self._usdc_last_refresh > 60:
            await self._refresh_usdc_balance()
            self._usdc_last_refresh = time.time()

        try:
            for asset in self.assets:
                signals = await self._call_tool("agdel_market_list_signals", {
                    "asset": asset, "status": "available", "limit": self.fetch_limit,
                })
                if not isinstance(signals, list):
                    if isinstance(signals, dict):
                        signals = signals.get("items", signals.get("signals", []))
                    else:
                        signals = []
                self.available_signals = signals
                self._consecutive_errors = 0  # reset on success

                if self.auto_buy:
                    candidates = self._filter_candidates(signals)
                    if candidates:
                        logger.info("Auto-buy: %d candidates to purchase", len(candidates))
                    for candidate in candidates:
                        logger.info("Auto-buy attempting: %s hz=%s cc=%.3f type=%s",
                                    candidate.get("commitment_hash", "")[:12],
                                    candidate.get("horizon", "?"),
                                    candidate.get("conf_calib", 0),
                                    candidate.get("signal_type", "?"))
                        result = await self._purchase_and_receive(candidate)
                        if result:
                            purchased.append(result)
                    # Opportunistic: snap up outlier C*C signals
                    outlier = self._find_outlier(signals)
                    if outlier:
                        result = await self._purchase_and_receive(outlier)
                        if result:
                            purchased.append(result)
        except Exception as e:
            self._stats["errors"] += 1
            self._consecutive_errors = getattr(self, "_consecutive_errors", 0) + 1
            logger.error("AGDEL poll error (%s): %s", type(e).__name__, e)
            # Clear stale signals on error so dashboard doesn't show expired data
            self.available_signals = []
            # Auto-reconnect MCP after consecutive failures (e.g. after PC sleep)
            if self._consecutive_errors >= 3:
                logger.warning("MCP session appears broken (%d consecutive errors), reconnecting...",
                               self._consecutive_errors)
                await self._reconnect_mcp()
        return purchased

    async def _reconnect_mcp(self):
        """Tear down and re-establish the MCP session."""
        # Close old session
        if self._mcp_session:
            try:
                await self._mcp_session.__aexit__(None, None, None)
            except Exception:
                pass
            self._mcp_session = None
        if self._mcp_context:
            try:
                await self._mcp_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._mcp_context = None
        # Check if MCP subprocess is still alive; restart if needed
        if self._mcp_process and self._mcp_process.returncode is not None:
            logger.info("MCP subprocess died (rc=%d), restarting...", self._mcp_process.returncode)
            self._mcp_process = None
        # Reconnect
        await self._connect_mcp()
        if self._mcp_session:
            self._consecutive_errors = 0
            logger.info("MCP session reconnected successfully")

    def _count_active(self, horizon: str) -> int:
        """Count active (non-expired) signals for a horizon."""
        now = time.time()
        return sum(
            1 for sig in self.signals.get(horizon, [])
            if sig.get("expiry_time", 0) > now
            and now - sig.get("received_at", 0) < 960
        )

    def _prune_expired_signals(self):
        """Remove expired signals from all horizons."""
        now = time.time()
        for hz in list(self.signals.keys()):
            self.signals[hz] = [
                sig for sig in self.signals[hz]
                if sig.get("expiry_time", 0) > now
                and now - sig.get("received_at", 0) < 960
            ]

    def _needs_signal(self, horizon: str) -> bool:
        """Check if a horizon needs more signals (active count < target)."""
        target = self.target_horizons.get(horizon, 1)
        active = self._count_active(horizon)
        if active >= target:
            return False
        # Brief cooldown to prevent buying multiple in rapid succession
        last_buy = self._last_buy_at.get(horizon, 0)
        if time.time() - last_buy < 8:
            return False
        return True

    def _deficit(self, horizon: str) -> int:
        """How many more signals do we need for this horizon?"""
        target = self.target_horizons.get(horizon, 1)
        active = self._count_active(horizon)
        return max(0, target - active)

    def _recent_signal_types(self, n: int = 10) -> dict[str, int]:
        """Count signal types in recent purchases."""
        counts: dict[str, int] = {}
        for entry in list(self.purchase_log)[:n]:
            st = entry.get("signal_type", "unknown")
            counts[st] = counts.get(st, 0) + 1
        return counts

    def _filter_candidates(self, signals: list[dict]) -> list[dict]:
        """Filter and rank signals, returning up to the deficit per horizon."""
        now = time.time()
        # Determine which horizons need signals and how many
        deficits: dict[str, int] = {}
        for hz in self.target_horizons:
            d = self._deficit(hz)
            if d > 0:
                deficits[hz] = d
        if not deficits:
            logger.debug("No deficits — all horizons filled")
            return []

        logger.info("Signal deficits: %s (from %d available)", deficits, len(signals))

        # Track rejection reasons for debugging
        reasons: dict[str, int] = {}

        # Build scored candidate list
        recent_types = self._recent_signal_types()
        scored: list[tuple[float, dict]] = []

        for sig in signals:
            commitment_hash = sig.get("commitment_hash", "")
            if commitment_hash in self.purchased_hashes:
                reasons["already_purchased"] = reasons.get("already_purchased", 0) + 1
                continue
            expiry = sig.get("expiry_time", 0)
            if isinstance(expiry, str):
                try:
                    expiry = int(expiry)
                except ValueError:
                    reasons["bad_expiry"] = reasons.get("bad_expiry", 0) + 1
                    continue
            remaining = expiry - now
            if remaining < 60:
                reasons["expired_soon"] = reasons.get("expired_soon", 0) + 1
                continue
            horizon = sig.get("horizon_bucket") or _classify_horizon(remaining)
            if horizon not in deficits:
                reasons[f"wrong_hz_{horizon or 'none'}"] = reasons.get(f"wrong_hz_{horizon or 'none'}", 0) + 1
                continue
            # Per-horizon minimum remaining time — buying window closes early
            min_remaining = _MIN_REMAINING_SECS.get(horizon, 60)
            if remaining < min_remaining:
                reasons["too_stale"] = reasons.get("too_stale", 0) + 1
                continue
            # Signal type filters
            sig_type = sig.get("signal_type", "unknown")
            if self.allowed_signal_types and sig_type not in self.allowed_signal_types:
                reasons["not_allowed_type"] = reasons.get("not_allowed_type", 0) + 1
                continue
            if self.blocked_signal_types and sig_type in self.blocked_signal_types:
                reasons["blocked_type"] = reasons.get("blocked_type", 0) + 1
                continue
            # Maker block list
            maker_addr = sig.get("maker_address", sig.get("maker", ""))
            if self.blocked_makers and maker_addr in self.blocked_makers:
                reasons["blocked_maker"] = reasons.get("blocked_maker", 0) + 1
                continue
            # Skip quality filters for explicitly allowed signal types
            is_allowed_type = bool(self.allowed_signal_types and sig_type in self.allowed_signal_types)
            confidence = float(sig.get("confidence", 0) or 0)
            if not is_allowed_type and confidence < self.min_confidence:
                reasons["low_conf"] = reasons.get("low_conf", 0) + 1
                continue
            raw_cost = float(sig.get("cost_usdc", 0) or 0)
            cost = raw_cost / 1_000_000 if raw_cost > 100 else raw_cost
            can_afford, _ = self.budget.can_spend(cost)
            if not can_afford:
                reasons["budget"] = reasons.get("budget", 0) + 1
                continue
            rep = sig.get("maker_track_record") or self._maker_cache.get(maker_addr, None) or {}
            has_track_record = bool(rep.get("hit_rate") or rep.get("win_rate") or rep.get("calibration_score"))
            win_rate = float(rep.get("hit_rate", rep.get("win_rate", 0)) or 0)
            # Only apply win-rate filter if maker has actual track record data and not an allowed type
            if not is_allowed_type and has_track_record and win_rate < self.min_maker_win_rate:
                reasons["low_winrate"] = reasons.get("low_winrate", 0) + 1
                continue
            # Default calibration to 0.5 for unknown makers so they get a fair C*C score
            calibration = float(rep.get("calibration_score", 0) or 0)
            if not calibration:
                calibration = 0.5
            cc = confidence * calibration

            # Diversity bonus: boost under-represented signal types
            type_count = recent_types.get(sig_type, 0)
            diversity_bonus = 0.1 / (1 + type_count)  # diminishes as type is seen more

            # Freshness bonus: prefer signals with more time remaining (0-0.15)
            freshness_bonus = min(0.15, remaining / 3000)

            # Preferred maker bonus
            preferred_bonus = 0.25 if (self.preferred_makers and maker_addr in self.preferred_makers) else 0

            rank_score = cc + diversity_bonus + freshness_bonus + preferred_bonus

            scored.append((rank_score, {
                **sig, "horizon": horizon, "cost": cost,
                "maker": sig.get("maker_address", sig.get("maker", "")),
                "confidence": confidence,
                "calibration": calibration,
                "conf_calib": round(cc, 4),
                "signal_type": sig_type,
            }))

        # Sort by rank score descending, pick up to deficit per horizon
        scored.sort(key=lambda x: x[0], reverse=True)
        selected: list[dict] = []
        picked: dict[str, int] = {}
        for _, candidate in scored:
            hz = candidate["horizon"]
            already = picked.get(hz, 0)
            if already >= deficits[hz]:
                continue
            selected.append(candidate)
            picked[hz] = already + 1
            if all(picked.get(h, 0) >= deficits[h] for h in deficits):
                break

        if reasons:
            logger.info("Filter rejections: %s | %d passed → %d selected", reasons, len(scored), len(selected))
        elif not scored:
            logger.warning("No candidates passed filters from %d signals (deficits=%s)", len(signals), deficits)
        else:
            logger.info("Filter: %d scored → %d selected (deficits=%s)", len(scored), len(selected), deficits)
        return selected

    def _rolling_cc_avg(self) -> float:
        """Average C*C from recent delivered purchases."""
        vals = [
            e.get("conf_calib", 0)
            for e in list(self.purchase_log)[:20]
            if e.get("conf_calib", 0) > 0
        ]
        return sum(vals) / len(vals) if vals else 0.0

    def _find_outlier(self, signals: list[dict]) -> dict | None:
        """Find a single exceptional C*C signal worth buying even if slot is filled."""
        avg_cc = self._rolling_cc_avg()
        if avg_cc <= 0:
            return None
        threshold = avg_cc * self.outlier_cc_multiplier
        now = time.time()

        best: tuple[float, dict] | None = None
        for sig in signals:
            commitment_hash = sig.get("commitment_hash", "")
            if commitment_hash in self.purchased_hashes:
                continue
            expiry = sig.get("expiry_time", 0)
            if isinstance(expiry, str):
                try:
                    expiry = int(expiry)
                except ValueError:
                    continue
            remaining = expiry - now
            if remaining < 60:
                continue
            horizon = sig.get("horizon_bucket") or _classify_horizon(remaining)
            if horizon and remaining < _MIN_REMAINING_SECS.get(horizon, 60):
                continue
            if horizon not in self.target_horizons:
                continue
            # Apply same signal type filters as _filter_candidates
            sig_type = sig.get("signal_type", "unknown")
            if self.allowed_signal_types and sig_type not in self.allowed_signal_types:
                continue
            if self.blocked_signal_types and sig_type in self.blocked_signal_types:
                continue
            confidence = float(sig.get("confidence", 0) or 0)
            maker_addr = sig.get("maker_address", sig.get("maker", ""))
            rep = sig.get("maker_track_record") or self._maker_cache.get(maker_addr, None) or {}
            calibration = float(rep.get("calibration_score", 0) or 0)
            cc = confidence * calibration
            if cc <= threshold:
                continue
            raw_cost = float(sig.get("cost_usdc", 0) or 0)
            cost = raw_cost / 1_000_000 if raw_cost > 100 else raw_cost
            can_afford, _ = self.budget.can_spend(cost)
            if not can_afford:
                continue
            if best is None or cc > best[0]:
                best = (cc, {
                    **sig, "horizon": horizon, "cost": cost,
                    "maker": maker_addr,
                    "confidence": confidence,
                    "calibration": calibration,
                    "conf_calib": round(cc, 4),
                    "signal_type": sig.get("signal_type", "unknown"),
                })

        if best:
            logger.info("Outlier signal found: C*C=%.3f (avg=%.3f, threshold=%.3f)",
                        best[0], avg_cc, threshold)
            return best[1]
        return None

    async def _purchase_and_receive(self, candidate: dict) -> dict | None:
        commitment_hash = candidate.get("commitment_hash", "")
        cost = candidate.get("cost", 0)
        log_base = {
            "commitment_hash": commitment_hash,
            "horizon": candidate.get("horizon"),
            "cost": cost, "purchased_at": time.time(),
            "maker": (candidate.get("maker", "") or "")[:12],
            "confidence": candidate.get("confidence", 0),
            "calibration": candidate.get("calibration", 0),
            "conf_calib": candidate.get("conf_calib", 0),
            "signal_type": candidate.get("signal_type", ""),
            "quality_score": candidate.get("quality_score", 0),
            "expiry_time": candidate.get("expiry_time", 0),
        }
        try:
            result = await self._call_tool("agdel_market_purchase_listing", {
                "commitment_hash": commitment_hash,
            })
            if isinstance(result, dict) and not result.get("purchase_ref"):
                return None
            self.purchased_hashes.add(commitment_hash)
            self.budget.record(cost)
            self._stats["purchases"] += 1
            self._last_buy_at[candidate.get("horizon", "")] = time.time()
            logger.info("Auto-purchased %s %s C*C=%.3f type=%s",
                        candidate.get("horizon", "?"), commitment_hash[:12],
                        candidate.get("conf_calib", 0), candidate.get("signal_type", "?"))

            purchase_time = time.time()
            maker = candidate.get("maker", "")
            horizon = candidate.get("horizon", "")
            expiry = candidate.get("expiry_time", 0)

            # Always try a short initial poll first (15s), regardless of webhook mode
            payload = await self._poll_delivery(commitment_hash, maker, timeout=15)
            now = time.time()
            if payload:
                self._delivered_hashes.add(commitment_hash)
                signal = self._convert_signal(payload, candidate)
                self.signals.setdefault(candidate["horizon"], []).append(signal)
                self._persist_purchase({**log_base, "delivered": True})
                self._update_purchase_log(commitment_hash, payload)
                self._record_delivery_metric(
                    commitment_hash, horizon, purchase_time, now,
                    method="poll", success=True, expiry_time=expiry, maker=maker)
                return signal

            # Initial poll didn't get it — queue for retry
            self._persist_purchase({**log_base, "delivered": False})
            self._pending_deliveries[commitment_hash] = {
                "candidate": candidate, "purchased_at": purchase_time,
                "maker": maker,
            }
            self._record_delivery_metric(
                commitment_hash, horizon, purchase_time, now,
                method="poll", success=False, expiry_time=expiry, maker=maker)
            return None
        except Exception as e:
            err_str = str(e)
            # Non-retryable errors: mark hash so we don't waste attempts
            if "AlreadyPurchased" in err_str or "3367b554" in err_str:
                self.purchased_hashes.add(commitment_hash)
                logger.info("Already purchased %s, skipping", commitment_hash[:12])
                return None
            if "buying window closed" in err_str.lower():
                self.purchased_hashes.add(commitment_hash)
                logger.info("Buying window closed for %s, skipping", commitment_hash[:12])
                return None
            self._stats["errors"] += 1
            logger.error("Purchase failed for %s: %s", commitment_hash[:12], e)
            self._persist_purchase({**log_base, "delivered": False, "error": str(e)})
            return None

    async def _poll_delivery(self, commitment_hash: str, maker_address: str,
                             timeout: int | None = None) -> dict | None:
        deadline = time.time() + (timeout if timeout is not None else self.delivery_timeout)
        while time.time() < deadline:
            try:
                delivery = await self._call_tool("agdel_exchange_get_my_delivery", {
                    "commitment_hash": commitment_hash,
                })
            except Exception:
                await asyncio.sleep(self.delivery_poll_seconds)
                continue
            if delivery and isinstance(delivery, dict) and delivery.get("ciphertext_b64"):
                if not self._buyer_private_key:
                    return None
                try:
                    payload = decrypt_delivery(
                        delivery, self._buyer_private_key,
                        commitment_hash, self._buyer_address, maker_address,
                    )
                    self._stats["deliveries"] += 1
                    return payload
                except Exception as e:
                    logger.error("Decryption failed: %s", e)
                    return None
            await asyncio.sleep(self.delivery_poll_seconds)
        return None

    def _record_delivery_metric(self, commitment_hash: str, horizon: str,
                                 purchased_at: float, delivered_at: float,
                                 method: str, success: bool,
                                 expiry_time: float = 0, maker: str = ""):
        """Log delivery timing to metrics file and update rolling stats."""
        delivery_time = delivered_at - purchased_at
        remaining_at_delivery = (expiry_time - delivered_at) if expiry_time else None
        expired_before_delivery = remaining_at_delivery is not None and remaining_at_delivery <= 0

        metric = {
            "ts": delivered_at,
            "hash": commitment_hash[:12],
            "horizon": horizon,
            "maker": maker[:12] if maker else "",
            "method": method,  # "poll", "webhook", "retry_webhook", "retry_poll"
            "success": success,
            "delivery_s": round(delivery_time, 2),
            "remaining_s": round(remaining_at_delivery, 1) if remaining_at_delivery is not None else None,
            "expired_before_delivery": expired_before_delivery,
        }

        if success:
            self._delivery_times.append(delivery_time)
            times = list(self._delivery_times)
            self._stats["delivery_avg_s"] = round(sum(times) / len(times), 2)
            self._stats["delivery_max_s"] = round(max(times), 2)
        if expired_before_delivery:
            self._stats["delivery_expired"] += 1
            logger.warning("Signal expired before delivery: %s %s (took %.1fs, expired %.1fs ago)",
                           horizon, commitment_hash[:12], delivery_time, -remaining_at_delivery)
        if not success:
            self._stats["delivery_timeout"] += 1

        try:
            self._delivery_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._delivery_log_path, "a") as f:
                f.write(json.dumps(metric) + "\n")
        except Exception as e:
            logger.debug("Failed to write delivery metric: %s", e)

        level = logging.WARNING if expired_before_delivery or not success else logging.INFO
        logger.log(level, "Delivery metric: %s %s method=%s %.1fs success=%s remaining=%s",
                   horizon, commitment_hash[:12], method, delivery_time,
                   success, f"{remaining_at_delivery:.0f}s" if remaining_at_delivery is not None else "?")

    def _convert_signal(self, payload: dict, meta: dict) -> dict:
        raw_dir = payload.get("direction", 0)
        # AGDEL convention: 0 / "long" = long, 1 / "short" = short
        if isinstance(raw_dir, str):
            is_long = raw_dir.lower() in ("long", "0")
        else:
            is_long = raw_dir == 0
        # Apply signal inversion if configured
        if self.invert_direction:
            is_long = not is_long
        confidence = meta.get("confidence", 0.5)
        score = confidence * (1 if is_long else -1) * self.score_multiplier
        signal = {
            "source": "agdel", "score": score, "confidence": confidence,
            "horizon": meta.get("horizon", "5m"),
            "direction": "long" if is_long else "short",
            "target_price": payload.get("target_price"),
            "maker": meta.get("maker", ""),
            "commitment_hash": payload.get("commitment_hash", ""),
            "cost_usdc": meta.get("cost", 0),
            "received_at": time.time(),
            "expiry_time": payload.get("expiry_time", 0),
            "calibration": meta.get("calibration", 0),
            "conf_calib": round(meta.get("confidence", 0.5) * meta.get("calibration", 0), 4),
        }
        # Extract rich metadata from delivery payload (regime, reasoning, etc.)
        delivery_meta = payload.get("metadata")
        if isinstance(delivery_meta, dict):
            signal["signal_metadata"] = delivery_meta
        return signal

    async def manual_purchase(self, commitment_hash: str) -> dict:
        """Purchase a specific signal by commitment hash (from dashboard button)."""
        if not self._mcp_session:
            return {"ok": False, "error": "MCP not connected"}
        sig = None
        for s in self.available_signals:
            if s.get("commitment_hash") == commitment_hash:
                sig = s
                break
        if not sig:
            return {"ok": False, "error": "Signal not found"}

        now = time.time()
        expiry = sig.get("expiry_time", 0)
        if isinstance(expiry, str):
            try:
                expiry = int(expiry)
            except ValueError:
                expiry = 0
        duration = expiry - now if expiry else 0
        horizon = sig.get("horizon_bucket") or _classify_horizon(duration) or "unknown"
        maker = sig.get("maker_address", sig.get("maker", ""))
        raw_cost = float(sig.get("cost_usdc", 0) or 0)
        cost = raw_cost / 1_000_000 if raw_cost > 100 else raw_cost

        rep = sig.get("maker_track_record", {})
        confidence = float(sig.get("confidence", 0) or 0)
        calibration = float(rep.get("calibration_score", 0) or 0)
        candidate = {
            "commitment_hash": commitment_hash, "horizon": horizon,
            "cost": cost, "maker": maker,
            "confidence": confidence,
            "calibration": calibration,
            "conf_calib": round(confidence * calibration, 4),
            "signal_type": sig.get("signal_type", ""),
            "quality_score": float(rep.get("avg_quality_score", rep.get("quality_score", 0)) or 0),
            "entry_price": sig.get("entry_price"),
            "created_at": sig.get("created_at"),
        }

        try:
            result = await self._call_tool("agdel_market_purchase_listing", {
                "commitment_hash": commitment_hash,
            })
            if isinstance(result, dict) and not result.get("purchase_ref"):
                error = result.get("error", str(result))
                self._persist_purchase({
                    "commitment_hash": commitment_hash, "horizon": horizon,
                    "cost": cost, "purchased_at": time.time(),
                    "delivered": False, "error": str(error),
                })
                return {"ok": False, "error": str(error)}

            self.purchased_hashes.add(commitment_hash)
            self.budget.record(cost)
            self._stats["purchases"] += 1
            self._persist_purchase({
                "commitment_hash": commitment_hash, "horizon": horizon,
                "cost": cost, "purchased_at": time.time(), "delivered": False,
                "maker": maker[:12] if maker else "",
                "confidence": candidate["confidence"],
                "calibration": candidate["calibration"],
                "conf_calib": candidate["conf_calib"],
                "signal_type": candidate["signal_type"],
                "quality_score": candidate["quality_score"],
                "entry_price": candidate.get("entry_price"),
                "created_at": candidate.get("created_at"),
                "expiry_time": expiry,
            })

            if self.webhook_url:
                self._pending_deliveries[commitment_hash] = {
                    "candidate": candidate, "purchased_at": time.time(),
                    "maker": maker,
                }
            else:
                asyncio.create_task(self._background_receive(candidate))

            return {"ok": True, "horizon": horizon, "cost": cost}
        except Exception as e:
            err_str = str(e)
            if "AlreadyPurchased" in err_str or "3367b554" in err_str:
                self.purchased_hashes.add(commitment_hash)
                return {"ok": False, "error": "Already purchased"}
            self._stats["errors"] += 1
            return {"ok": False, "error": err_str}

    async def _background_receive(self, candidate: dict):
        commitment_hash = candidate.get("commitment_hash", "")
        maker = candidate.get("maker", "")
        try:
            payload = await self._poll_delivery(commitment_hash, maker)
            if payload:
                signal = self._convert_signal(payload, candidate)
                self.signals.setdefault(candidate.get("horizon", "5m"), []).append(signal)
                self._update_purchase_log(commitment_hash, payload)
        except Exception as e:
            logger.error("Background delivery error: %s", e)

    async def handle_webhook_delivery(self, payload: dict) -> dict | None:
        commitment_hash = payload.get("commitment_hash", "")
        if commitment_hash in self._delivered_hashes:
            logger.debug("Webhook delivery skipped (already delivered): %s", commitment_hash[:12])
            return None
        logger.info("Webhook delivery for %s (pending keys: %s)",
                    commitment_hash[:12],
                    [k[:12] for k in self._pending_deliveries.keys()])
        pending = self._pending_deliveries.pop(commitment_hash, None)
        if not pending:
            logger.warning("No pending delivery for %s", commitment_hash[:12])
            return None
        candidate = pending["candidate"]
        purchased_at = pending.get("purchased_at", 0)
        envelope = {
            "ephemeral_pubkey_b64": payload.get("ephemeral_pubkey_b64"),
            "nonce_b64": payload.get("nonce_b64"),
            "ciphertext_b64": payload.get("ciphertext_b64"),
        }
        if not envelope.get("ciphertext_b64") or not self._buyer_private_key:
            self._record_delivery_metric(
                commitment_hash, candidate.get("horizon", ""),
                purchased_at, time.time(), method="webhook", success=False,
                expiry_time=candidate.get("expiry_time", 0),
                maker=candidate.get("maker", ""))
            return None
        try:
            decrypted = decrypt_delivery(
                envelope, self._buyer_private_key,
                commitment_hash, self._buyer_address,
                payload.get("maker_address", candidate.get("maker", "")),
            )
            self._delivered_hashes.add(commitment_hash)
            signal = self._convert_signal(decrypted, candidate)
            self.signals.setdefault(candidate.get("horizon", "5m"), []).append(signal)
            self._stats["deliveries"] += 1
            self._update_purchase_log(commitment_hash, decrypted)
            self._record_delivery_metric(
                commitment_hash, candidate.get("horizon", ""),
                purchased_at, time.time(), method="webhook", success=True,
                expiry_time=candidate.get("expiry_time", 0),
                maker=candidate.get("maker", ""))
            return signal
        except Exception as e:
            logger.error("Webhook decryption failed: %s", e)
            self._record_delivery_metric(
                commitment_hash, candidate.get("horizon", ""),
                purchased_at, time.time(), method="webhook", success=False,
                expiry_time=candidate.get("expiry_time", 0),
                maker=candidate.get("maker", ""))
            return None

    async def check_stale_deliveries(self):
        """Retry delivery for any purchased-but-undelivered signals.

        Covers both webhook mode (pending_deliveries) and poll mode (purchase_log).
        """
        now = time.time()

        # 1. Pending deliveries (from initial poll timeout) older than 15s
        stale = []
        for ch, info in list(self._pending_deliveries.items()):
            if ch in self._delivered_hashes:
                self._pending_deliveries.pop(ch, None)
                continue
            if now - info["purchased_at"] > 15:
                stale.append((ch, info))
        for ch, info in stale:
            try:
                payload = await self._poll_delivery(ch, info["maker"], timeout=10)
                if payload:
                    self._delivered_hashes.add(ch)
                    candidate = info["candidate"]
                    signal = self._convert_signal(payload, candidate)
                    self.signals.setdefault(candidate.get("horizon", "5m"), []).append(signal)
                    self._pending_deliveries.pop(ch, None)
                    self._update_purchase_log(ch, payload)
                    self._record_delivery_metric(
                        ch, candidate.get("horizon", ""),
                        info["purchased_at"], time.time(), method="retry",
                        success=True, expiry_time=candidate.get("expiry_time", 0),
                        maker=info.get("maker", ""))
                elif now - info["purchased_at"] > 300:
                    # Give up after 5 minutes
                    self._pending_deliveries.pop(ch, None)
                    self._record_delivery_metric(
                        ch, info.get("candidate", {}).get("horizon", ""),
                        info["purchased_at"], time.time(), method="retry",
                        success=False, expiry_time=info.get("candidate", {}).get("expiry_time", 0),
                        maker=info.get("maker", ""))
            except Exception as e:
                logger.debug("Stale delivery retry error for %s: %s", ch[:12], e)

        # 2. Scan purchase_log for undelivered signals that haven't expired
        retry_count = 0
        for entry in self.purchase_log:
            if entry.get("delivered"):
                continue
            if entry.get("error"):
                continue
            if entry.get("_delivery_gave_up"):
                continue
            ch = entry.get("commitment_hash", "")
            if not ch or ch in self._delivered_hashes:
                continue
            purchased_at = entry.get("purchased_at", 0)
            expiry = entry.get("expiry_time", 0)
            if expiry and expiry < now:
                entry["_delivery_gave_up"] = True
                continue
            # Don't retry if purchased less than 20s ago (initial poll is 15s)
            if now - purchased_at < 20:
                continue
            if now - purchased_at > 300:
                entry["_delivery_gave_up"] = True
                continue
            if retry_count >= 3:
                break
            maker = entry.get("maker", "")
            try:
                payload = await self._poll_delivery(ch, maker, timeout=10)
                horizon = entry.get("horizon", "5m")
                if payload:
                    self._delivered_hashes.add(ch)
                    candidate_meta = {
                        "horizon": horizon,
                        "maker": maker,
                        "confidence": entry.get("confidence", 0.5),
                        "calibration": entry.get("calibration", 0.5),
                        "cost": entry.get("cost", 0),
                    }
                    signal = self._convert_signal(payload, candidate_meta)
                    self.signals.setdefault(horizon, []).append(signal)
                    self._update_purchase_log(ch, payload)
                    self._record_delivery_metric(
                        ch, horizon, purchased_at, time.time(),
                        method="retry", success=True,
                        expiry_time=entry.get("expiry_time", 0), maker=maker)
                retry_count += 1
            except Exception as e:
                logger.debug("Delivery retry error for %s: %s", ch[:12], e)
                retry_count += 1
        self._persist_purchase_log()

    async def check_outcomes(self):
        """Poll AGDEL for resolution outcomes on recent purchases."""
        if not self._mcp_session:
            return
        now = time.time()
        for entry in self.purchase_log:
            if entry.get("outcome"):
                continue
            if not entry.get("delivered"):
                continue
            expiry = entry.get("expiry_time", 0)
            if not expiry or now < expiry:
                continue
            # Only check signals expired more than 30s ago (give keeper time)
            if now - expiry < 30:
                continue
            try:
                sig = await self._call_tool("agdel_market_get_signal", {
                    "commitment_hash": entry["commitment_hash"],
                })
                if isinstance(sig, dict):
                    status = sig.get("status", "")
                    if status in ("resolved", "settled"):
                        qs = sig.get("quality_score")
                        entry["outcome"] = "HIT" if qs and float(qs) > 0 else "MISS"
                        entry["quality_score"] = qs
                        entry["resolution_price"] = sig.get("resolution_price")
                        logger.info("Resolution %s: %s (quality=%s)",
                                    entry["commitment_hash"][:10], entry["outcome"], qs)
                    elif status == "defaulted":
                        entry["outcome"] = "DEFAULT"
                        logger.info("Resolution %s: DEFAULT", entry["commitment_hash"][:10])
            except Exception as e:
                logger.debug("Outcome check failed for %s: %s", entry["commitment_hash"][:10], e)
        self._persist_purchase_log()

    def handle_webhook_resolution(self, body: dict) -> dict | None:
        """Handle a resolution webhook event — instant outcome update."""
        commitment_hash = body.get("commitment_hash", "")
        if not commitment_hash:
            return None
        for entry in self.purchase_log:
            if entry.get("commitment_hash") == commitment_hash:
                if entry.get("outcome"):
                    return entry
                status = body.get("status", "")
                if status in ("resolved", "settled"):
                    qs = body.get("quality_score")
                    entry["outcome"] = "HIT" if qs and float(qs) > 0 else "MISS"
                    entry["quality_score"] = qs
                    entry["resolution_price"] = body.get("resolution_price")
                    logger.info("Webhook resolution %s: %s (quality=%s)",
                                commitment_hash[:10], entry["outcome"], qs)
                elif status == "defaulted":
                    entry["outcome"] = "DEFAULT"
                    logger.info("Webhook resolution %s: DEFAULT", commitment_hash[:10])
                self._persist_purchase_log()
                return entry
        return None

    def get_latest_signals(self) -> dict[str, dict | None]:
        """Return a C*C-weighted aggregate of all active signals per horizon.

        When multiple signals are active for a horizon, their scores and
        confidences are combined into a single synthetic signal weighted by
        each signal's conf_calib.  If signals disagree on direction, they
        partially cancel out — producing a weaker (or FLAT) aggregate.
        """
        now = time.time()
        result = {}
        for hz in self.target_horizons:
            active = []
            for sig in self.signals.get(hz, []):
                expiry = sig.get("expiry_time", 0)
                if expiry and now > expiry:
                    continue
                if now - sig.get("received_at", 0) > 960:
                    continue
                active.append(sig)
            if not active:
                result[hz] = None
                continue
            if len(active) == 1:
                result[hz] = active[0]
                continue
            # Aggregate: C*C-weighted mean of score and confidence
            total_w = 0.0
            w_score = 0.0
            w_conf = 0.0
            all_hashes = []
            best_sig = active[0]
            best_cc = -1.0
            for sig in active:
                cc = float(sig.get("conf_calib", 0) or 0)
                w = max(cc, 0.01)  # floor to avoid zero-weight
                w_score += float(sig.get("score", 0) or 0) * w
                w_conf += float(sig.get("confidence", 0) or 0) * w
                total_w += w
                h = sig.get("commitment_hash", "")
                if h:
                    all_hashes.append(h)
                if cc > best_cc:
                    best_cc = cc
                    best_sig = sig
            agg_score = w_score / total_w
            agg_conf = w_conf / total_w
            agg_direction = "long" if agg_score > 0 else "short"
            # Build synthetic signal, inheriting metadata from the best individual
            agg = {
                **best_sig,
                "score": round(agg_score, 4),
                "confidence": round(agg_conf, 4),
                "conf_calib": round(abs(agg_score) * agg_conf, 4),
                "direction": agg_direction,
                "aggregated_from": len(active),
                "all_hashes": all_hashes,
            }
            result[hz] = agg
        return result

    def reload_config(self, config: dict):
        """Hot-reload buyer settings from config."""
        ac = config.get("agdel", {})
        sel = ac.get("selection", {})
        self.min_confidence = sel.get("minSignalConfidence", 0.2)
        self.target_horizons = sel.get("targetHorizons", {"5m": 1, "15m": 1})
        mf = ac.get("makerFilters", {})
        self.min_maker_win_rate = mf.get("minWinRate", 0.3)
        self.allowed_signal_types = set(mf.get("allowedSignalTypes", []))
        self.blocked_signal_types = set(mf.get("blockedSignalTypes", []))
        self.blocked_makers = set(mf.get("blockedMakers", []))
        self.preferred_makers = set(mf.get("preferredMakers", []))
        sp = config.get("signalProcessing", {})
        self.invert_direction = sp.get("invertSignalDirection", False)
        self.score_multiplier = sp.get("scoreMultiplier", 1.0)
        logger.info("Buyer config reloaded: invert=%s multiplier=%.2f targets=%s "
                     "blocked_types=%s blocked_makers=%d preferred_makers=%d",
                     self.invert_direction, self.score_multiplier, self.target_horizons,
                     self.blocked_signal_types, len(self.blocked_makers),
                     len(self.preferred_makers))

    async def fetch_resolved_signals(self, limit: int = 100) -> list[dict]:
        """Fetch recently resolved signals from AGDEL for market-wide analysis."""
        if not self._mcp_session:
            return []
        try:
            for asset in self.assets:
                signals = await self._call_tool("agdel_market_list_signals", {
                    "asset": asset, "status": "resolved", "limit": limit,
                })
                if isinstance(signals, list):
                    return signals
                if isinstance(signals, dict):
                    return signals.get("items", signals.get("signals", []))
        except Exception as e:
            logger.debug("Failed to fetch resolved signals: %s", e)
        return []

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "autoBuy": self.auto_buy,
            "budget": self.budget.status(),
            "purchasedCount": len(self.purchased_hashes),
            "activeSignals": {hz: self._count_active(hz) for hz in self.target_horizons},
            "targetSignals": dict(self.target_horizons),
        }

    def get_wallet_info(self) -> dict:
        addr = self._buyer_address
        return {
            "address": addr,
            "addressShort": (addr[:8] + "..." + addr[-6:]) if len(addr) > 14 else addr,
            "usdcBalance": round(self._usdc_balance, 6),
        }

    def get_available_enriched(self) -> list[dict]:
        now = time.time()
        enriched = []
        skipped = 0
        for sig in self.available_signals:
            try:
                expiry = sig.get("expiry_time", 0)
                if isinstance(expiry, str):
                    try:
                        expiry = int(expiry)
                    except (ValueError, TypeError):
                        skipped += 1
                        continue
                # Handle ms timestamps (if > year 2100 in seconds, assume ms)
                if expiry > 4_102_444_800:
                    expiry = expiry / 1000
                if expiry <= now:
                    skipped += 1
                    continue
                duration = expiry - now
                horizon = sig.get("horizon_bucket") or _classify_horizon(duration)
                maker = sig.get("maker_address", sig.get("maker", ""))
                rep = sig.get("maker_track_record") or self._maker_cache.get(maker, {})
                confidence = float(sig.get("confidence", 0) or 0)
                calibration = float(rep.get("calibration_score", 0) or 0)
                if not calibration:
                    calibration = 0.5
                win_rate = float(rep.get("hit_rate", rep.get("win_rate", 0)) or 0)
                quality = float(rep.get("avg_quality_score", rep.get("quality_score", 0)) or 0)
                raw_cost = float(sig.get("cost_usdc", 0) or 0)
                cost = raw_cost / 1_000_000 if raw_cost > 100 else raw_cost
                created_at = float(sig.get("created_at", 0) or 0)
                posted_ago = int(now - created_at) if created_at else None
                enriched.append({
                    "commitmentHash": sig.get("commitment_hash", ""),
                    "commitmentHashShort": sig.get("commitment_hash", "")[:12],
                    "horizon": horizon or f"{int(duration)}s",
                    "maker": maker[:12] if maker else "",
                    "makerFull": maker or "",
                    "cost": cost, "confidence": confidence,
                    "signalType": sig.get("signal_type", ""),
                    "quality": quality, "winRate": win_rate,
                    "calibration": calibration,
                    "confCalib": round(confidence * calibration, 4),
                    "totalSignals": int(rep.get("total_signals", 0) or 0),
                    "expiresIn": int(duration),
                    "postedAgo": posted_ago,
                    "createdAt": created_at,
                })
            except Exception as e:
                logger.warning("Failed to enrich signal: %s (keys=%s)", e,
                               list(sig.keys())[:10])
                skipped += 1
        if skipped and not enriched:
            logger.warning("All %d available signals were skipped during enrichment "
                           "(raw count=%d)", skipped, len(self.available_signals))
        enriched.sort(key=lambda s: s["createdAt"] or 0, reverse=True)
        return enriched

    def _update_purchase_log(self, commitment_hash: str, payload: dict):
        """Update purchase log entry with decrypted delivery fields.

        Only overwrites existing values if the payload value is not None,
        so API-sourced fields like expiry_time aren't clobbered.
        """
        for entry in self.purchase_log:
            if entry.get("commitment_hash") == commitment_hash:
                entry["delivered"] = True
                for key in ("direction", "target_price", "expiry_time", "salt", "asset",
                            "entry_price", "created_at"):
                    val = payload.get(key)
                    if val is not None:
                        entry[key] = val
                break
        self._persist_purchase_log()

    async def get_signal_detail(self, commitment_hash: str) -> dict:
        """Fetch full signal detail from AGDEL API and merge with local purchase data."""
        result = {"local": None, "agdel": None}
        for entry in self.purchase_log:
            if entry.get("commitment_hash") == commitment_hash:
                result["local"] = dict(entry)
                break
        if self._mcp_session:
            try:
                sig = await self._call_tool("agdel_market_get_signal", {
                    "commitment_hash": commitment_hash,
                })
                if isinstance(sig, str):
                    sig = json.loads(sig)
                result["agdel"] = sig
            except Exception as e:
                result["agdel_error"] = str(e)
        return result

    def _derive_address_from_key(self) -> str:
        pk = os.environ.get("TRADERBOT_WALLET_PRIVATE_KEY", "") or os.environ.get("AGDEL_PRIVATE_KEY", "")
        if not pk:
            return ""
        try:
            from eth_account import Account
            return Account.from_key(pk).address
        except Exception:
            return ""

    async def _refresh_usdc_balance(self):
        if not self._buyer_address:
            return
        padded = self._buyer_address.lower().replace("0x", "").zfill(64)
        data = "0x70a08231" + padded
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._rpc_url, json={
                    "jsonrpc": "2.0", "method": "eth_call",
                    "params": [{"to": self._usdc_address, "data": data}, "latest"],
                    "id": 1,
                })
                raw = int(resp.json().get("result", "0x0"), 16)
                self._usdc_balance = raw / 1_000_000
        except Exception:
            pass

    def _load_or_generate_keypair(self):
        key_path = Path(self.key_file_path)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            self._buyer_private_key = X25519PrivateKey.from_private_bytes(key_path.read_bytes())
        else:
            self._buyer_private_key = X25519PrivateKey.generate()
            key_path.write_bytes(self._buyer_private_key.private_bytes_raw())
        pub_bytes = self._buyer_private_key.public_key().public_bytes_raw()
        self._buyer_public_key_b64 = base64.b64encode(pub_bytes).decode()
