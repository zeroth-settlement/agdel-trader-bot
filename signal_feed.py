"""Direct signal feed — polls the signal bot API for all signal outputs.

Unlike AGDEL buying (which only gets signals we purchase), this feed gets
EVERY signal the signal bot produces — all 16+ signal types, all horizons,
all metadata. This gives the LLM vastly more context for thesis formation.

AGDEL buying continues in parallel for marketplace traction.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque

import httpx

logger = logging.getLogger("signal_feed")


class SignalFeed:
    """Polls the signal bot for all signal outputs."""

    def __init__(self, config: dict):
        fc = config.get("signalFeed", {})
        self.enabled: bool = fc.get("enabled", False)

        # Use deployed URL from env if available, fallback to config/localhost
        env_url = os.environ.get("SIGNAL_FEED_URL", "")
        self.base_url: str = env_url or fc.get("baseUrl", "http://localhost:9502")

        # Basic auth from env (format: "user:pass")
        auth_str = os.environ.get("SIGNAL_FEED_AUTH", "")
        auth = None
        if auth_str and ":" in auth_str:
            user, pw = auth_str.split(":", 1)
            auth = httpx.BasicAuth(user, pw)

        self.poll_interval: float = fc.get("pollIntervalSeconds", 10)
        self._http = httpx.AsyncClient(timeout=10, base_url=self.base_url, auth=auth)

        if env_url:
            logger.info("Signal feed: using deployed URL %s", self.base_url)

        # Latest signal snapshot (all signals from last tick)
        self._latest_signals: list[dict] = []
        self._latest_composite: dict = {}
        self._latest_timestamp: float = 0
        # Outstanding predictions (all active, from all signal types)
        self._outstanding: list[dict] = []

        # Settled predictions for reflection (rolling 30-min window)
        self._settled: deque[dict] = deque(maxlen=500)
        self._last_settled_fetch: float = 0

        # Stats
        self._poll_count: int = 0
        self._error_count: int = 0
        self._consecutive_errors: int = 0
        self._last_poll_at: float = 0
        self._down_notified: bool = False

    async def poll_once(self) -> bool:
        """Fetch latest signals from the signal bot. Returns True if new data.

        Uses two endpoints:
        - /api/tick/latest for the composite + per-tick signals
        - /api/predictions/outstanding for ALL active predictions (richer, more complete)
        """
        if not self.enabled:
            return False

        try:
            # Get tick-level composite direction
            try:
                resp = await self._http.get("/api/tick/latest")
                resp.raise_for_status()
                tick_data = resp.json()
                self._latest_signals = tick_data.get("signals", [])
                self._latest_composite = tick_data.get("composite", {})
            except Exception:
                pass  # tick/latest may be empty between ticks, that's OK

            # Get all outstanding predictions (the main data source)
            resp = await self._http.get("/api/predictions/outstanding",
                                        params={"limit": 200})
            resp.raise_for_status()
            data = resp.json()
            self._outstanding = data.get("outstanding", data.get("items", []))
            self._latest_timestamp = time.time()
            self._poll_count += 1
            self._last_poll_at = time.time()

            if self._poll_count <= 1 or self._poll_count % 30 == 0:
                logger.info("Signal feed: %d outstanding predictions, %d tick signals, composite=%s (from %s)",
                            len(self._outstanding), len(self._latest_signals),
                            self._latest_composite.get("direction", "?"),
                            self.base_url)
            self._consecutive_errors = 0
            if self._down_notified:
                self._down_notified = False
                logger.info("Signal feed recovered after %d errors", self._error_count)
                self._send_notification("Signal Feed RECOVERED", "Signal bot is back online. Signals flowing.")
            return True

        except Exception as e:
            self._error_count += 1
            self._consecutive_errors += 1
            if self._error_count <= 3 or self._error_count % 30 == 0:
                logger.warning("Signal feed poll error (%d, %d consecutive): %s",
                               self._error_count, self._consecutive_errors, e)
            # Notify after 5 consecutive failures (~50 seconds of downtime)
            if self._consecutive_errors == 5 and not self._down_notified:
                self._down_notified = True
                logger.error("Signal feed DOWN — %d consecutive errors from %s", self._consecutive_errors, self.base_url)
                self._send_notification("ALERT: Signal Feed DOWN",
                    f"Signal bot unreachable at {self.base_url}. Trading without signals!")
            return False

    def _send_notification(self, title: str, message: str):
        """Send push notification via ntfy if configured."""
        topic = os.environ.get("NTFY_TOPIC", "")
        if not topic:
            return
        try:
            import httpx as _httpx
            _httpx.Client(timeout=5).post(
                f"https://ntfy.sh/{topic}",
                content=message.encode(),
                headers={"Title": title, "Priority": "urgent", "Tags": "warning"},
            )
        except Exception:
            pass

    async def fetch_settled(self, limit: int = 200) -> list[dict]:
        """Fetch recently settled predictions for reflection analysis."""
        if not self.enabled:
            return []

        # Only fetch every 60s to avoid hammering
        if time.time() - self._last_settled_fetch < 60:
            return list(self._settled)

        try:
            resp = await self._http.get(f"/api/predictions/settled",
                                        params={"limit": limit})
            resp.raise_for_status()
            data = resp.json()
            settled = data.get("settled", data.get("items", []))
            if isinstance(settled, list):
                self._settled = deque(settled, maxlen=500)
            self._last_settled_fetch = time.time()
            return list(self._settled)
        except Exception as e:
            logger.warning("Signal feed settled fetch error: %s", e)
            return list(self._settled)

    async def fetch_prediction_stats(self) -> dict:
        """Fetch per-agent prediction accuracy stats."""
        if not self.enabled:
            return {}
        try:
            resp = await self._http.get("/api/predictions/stats")
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}

    def get_all_signals(self) -> list[dict]:
        """Return all signals from the latest tick.

        Each signal has: source, domain, score, confidence, timeHorizon,
        weight, projections, metadata, etc.
        """
        return self._latest_signals

    def get_composite(self) -> dict:
        """Return the composite signal (aggregated consensus from all signals)."""
        return self._latest_composite

    def get_active_predictions_for_context(self) -> list[dict]:
        """Convert signal bot outstanding predictions into MarketContext format.

        Returns a list compatible with active_predictions in MarketContext,
        enriched with signal metadata that AGDEL deliveries don't have.
        Uses outstanding predictions (richer than tick-level signals).
        """
        predictions = []

        for pred_entry in self._outstanding:
            agent = pred_entry.get("agent", "unknown")
            direction = pred_entry.get("direction", "unknown")
            direction_score = pred_entry.get("direction_score", 0)
            current_price = pred_entry.get("current_price", 0)
            metadata = pred_entry.get("metadata", {})

            # Use direction_score if available (continuous -1 to +1, much better
            # than binary direction derived from range center)
            if not direction_score and isinstance(metadata, dict):
                for key in ("directionScore", "direction_score", "direction_bias"):
                    val = metadata.get(key)
                    if val is not None:
                        try:
                            direction_score = max(-1.0, min(1.0, float(val)))
                        except (TypeError, ValueError):
                            pass
                        break

            projections = pred_entry.get("projections", {})
            for hz, proj in projections.items():
                if not isinstance(proj, dict):
                    continue
                p_conf = proj.get("confidence", 0)
                if p_conf <= 0.05:
                    continue

                p_min = proj.get("min", 0)
                p_max = proj.get("max", 0)
                if not p_min or not p_max:
                    continue

                target = round((p_min + p_max) / 2, 2)

                # Use direction_score for direction (not range center vs price)
                if abs(direction_score) > 0.1:
                    hz_direction = "long" if direction_score > 0 else "short"
                elif current_price and current_price > 0:
                    hz_direction = "long" if target > current_price else "short" if target < current_price else "flat"
                else:
                    hz_direction = direction

                pred = {
                    "hash": f"direct:{agent}:{hz}",
                    "hz": hz,
                    "role": "fast" if hz in ("1m", "5m") else "slow",
                    "signal_type": agent,
                    "maker": "direct-feed",
                    "direction": hz_direction,
                    "direction_score": round(direction_score, 4),
                    "confidence": round(p_conf, 3),
                    "calibration": 1.0,
                    "cc": round(p_conf, 3),
                    "target_price": target,
                    "entry_price": round(current_price, 2) if current_price else None,
                    "outcome": "",
                    "expired": False,
                    "expiry_time": 0,
                    "source": "direct",
                    "signal_metadata": {
                        "signal_type": agent,
                        "data_quality": proj.get("dataQuality"),
                        "model_version": proj.get("modelVersion"),
                        "raw_confidence": proj.get("rawConfidence"),
                        "range_min": round(p_min, 2),
                        "range_max": round(p_max, 2),
                    },
                }

                # Add any rich metadata from signal scripts
                if isinstance(metadata, dict):
                    for key in ("regime", "reasoning", "trend_direction",
                                "exhaustion_score", "regime_confidence",
                                "vol_regime", "ema_alignment", "direction_bias",
                                "zScore", "indicators"):
                        if key in metadata:
                            pred["signal_metadata"][key] = metadata[key]

                predictions.append(pred)

        return predictions

    def get_stats(self) -> dict:
        """Return feed stats for dashboard."""
        return {
            "enabled": self.enabled,
            "pollCount": self._poll_count,
            "errorCount": self._error_count,
            "signalCount": len(self._latest_signals),
            "lastPollAt": self._last_poll_at,
            "compositeDirection": self._latest_composite.get("direction", "?"),
            "compositeConfidence": self._latest_composite.get("confidence", 0),
            "compositeScore": self._latest_composite.get("compositeScore", 0),
        }

    def reload_config(self, config: dict):
        fc = config.get("signalFeed", {})
        self.enabled = fc.get("enabled", False)
        new_url = fc.get("baseUrl", "http://localhost:9502")
        if new_url != self.base_url:
            self.base_url = new_url
            self._http = httpx.AsyncClient(timeout=10, base_url=self.base_url)
        self.poll_interval = fc.get("pollIntervalSeconds", 10)
