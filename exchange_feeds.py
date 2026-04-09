"""Multi-exchange ETH price feeds — track lead/lag across venues.

Connects to Binance perps (price leader), Coinbase spot (US benchmark),
and OKX perps via WebSocket. Computes real-time basis vs Hyperliquid
to detect when HL price is about to move.

Price discovery order (typical):
  Binance Perps → Binance Spot → OKX/Bybit → Coinbase → DEXes (HL)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import websockets

logger = logging.getLogger("exchange_feeds")

# ─── Exchange configuration ──────────────────────────────────────

EXCHANGES = {
    "binance_perp": {
        "name": "Binance Perps",
        "short": "BIN-P",
        "ws_url": "wss://fstream.binance.com/ws/ethusdt@bookTicker",
        "type": "stream",  # no subscription message needed (stream in URL)
        "parser": "_parse_binance",
        "leader": True,
    },
    "coinbase": {
        "name": "Coinbase",
        "short": "CB",
        "ws_url": "wss://ws-feed.exchange.coinbase.com",
        "type": "subscribe",
        "subscribe_msg": {
            "type": "subscribe",
            "channels": [{"name": "ticker", "product_ids": ["ETH-USD"]}],
        },
        "parser": "_parse_coinbase",
        "leader": False,
    },
    "okx_perp": {
        "name": "OKX Perps",
        "short": "OKX-P",
        "ws_url": "wss://ws.okx.com:8443/ws/v5/public",
        "type": "subscribe",
        "subscribe_msg": {
            "op": "subscribe",
            "args": [{"channel": "tickers", "instId": "ETH-USDT-SWAP"}],
        },
        "parser": "_parse_okx",
        "leader": False,
    },
}


@dataclass
class ExchangePrice:
    """Latest price snapshot from an exchange."""
    exchange_id: str
    name: str
    short: str
    bid: float = 0.0
    ask: float = 0.0
    mid: float = 0.0
    last_update: float = 0.0
    connected: bool = False
    leader: bool = False
    # Lead/lag tracking
    delta_vs_hl: float = 0.0       # mid - HL mid (positive = exchange is higher)
    delta_vs_hl_pct: float = 0.0   # as percentage
    update_count: int = 0

    def to_dict(self) -> dict:
        age_ms = (time.time() - self.last_update) * 1000 if self.last_update else 0
        return {
            "exchangeId": self.exchange_id,
            "name": self.name,
            "short": self.short,
            "bid": round(self.bid, 2),
            "ask": round(self.ask, 2),
            "mid": round(self.mid, 2),
            "spread": round(self.ask - self.bid, 2) if self.bid and self.ask else 0,
            "connected": self.connected,
            "leader": self.leader,
            "deltaVsHl": round(self.delta_vs_hl, 2),
            "deltaVsHlPct": round(self.delta_vs_hl_pct, 4),
            "ageMs": round(age_ms),
            "updateCount": self.update_count,
        }


@dataclass
class BasisSnapshot:
    """Point-in-time basis measurement."""
    timestamp: float
    hl_mid: float
    leader_mid: float  # Binance perps
    basis: float       # leader - HL
    basis_pct: float

    def to_dict(self) -> dict:
        return {
            "t": self.timestamp,
            "hl": round(self.hl_mid, 2),
            "leader": round(self.leader_mid, 2),
            "basis": round(self.basis, 2),
            "basisPct": round(self.basis_pct, 4),
        }


class ExchangeFeeds:
    """Manages WebSocket connections to multiple exchanges."""

    def __init__(self):
        self.prices: dict[str, ExchangePrice] = {}
        self.basis_history: deque[BasisSnapshot] = deque(maxlen=500)
        self._tasks: list[asyncio.Task] = []
        self._hl_mid: float = 0.0
        self._on_update: Optional[Callable] = None
        self._last_basis_record: float = 0

        # Initialize price entries
        for ex_id, cfg in EXCHANGES.items():
            self.prices[ex_id] = ExchangePrice(
                exchange_id=ex_id,
                name=cfg["name"],
                short=cfg["short"],
                leader=cfg.get("leader", False),
            )

    def set_hl_price(self, mid: float):
        """Called by the trading server on each HL price tick."""
        self._hl_mid = mid
        # Recompute deltas
        for ep in self.prices.values():
            if ep.mid > 0 and mid > 0:
                ep.delta_vs_hl = ep.mid - mid
                ep.delta_vs_hl_pct = (ep.delta_vs_hl / mid) * 100

        # Record basis snapshot every 5 seconds
        now = time.time()
        if now - self._last_basis_record >= 5:
            leader = self.get_leader_price()
            if leader and leader.mid > 0 and mid > 0:
                basis = leader.mid - mid
                self.basis_history.append(BasisSnapshot(
                    timestamp=now,
                    hl_mid=mid,
                    leader_mid=leader.mid,
                    basis=basis,
                    basis_pct=(basis / mid) * 100,
                ))
                self._last_basis_record = now

    def get_leader_price(self) -> Optional[ExchangePrice]:
        """Get the price from the leading exchange (Binance perps)."""
        for ep in self.prices.values():
            if ep.leader and ep.mid > 0:
                return ep
        return None

    async def start(self, on_update: Callable | None = None):
        """Start all exchange WebSocket feeds."""
        self._on_update = on_update
        for ex_id, cfg in EXCHANGES.items():
            task = asyncio.create_task(self._ws_loop(ex_id, cfg))
            self._tasks.append(task)
        logger.info("Started %d exchange feeds: %s",
                     len(EXCHANGES), ", ".join(cfg["name"] for cfg in EXCHANGES.values()))

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()

    async def _ws_loop(self, ex_id: str, cfg: dict):
        """Reconnecting WebSocket loop for one exchange."""
        backoff = 1.0
        parser = getattr(self, cfg["parser"])
        ep = self.prices[ex_id]

        while True:
            try:
                ws = await asyncio.wait_for(
                    websockets.connect(cfg["ws_url"], ping_interval=20, ping_timeout=10,
                                       close_timeout=5, open_timeout=10),
                    timeout=15,
                )
                try:
                    if cfg["type"] == "subscribe" and "subscribe_msg" in cfg:
                        await ws.send(json.dumps(cfg["subscribe_msg"]))

                    ep.connected = True
                    backoff = 1.0
                    logger.info("%s WebSocket connected", cfg["name"])

                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            logger.warning("%s WS stale — reconnecting", cfg["name"])
                            break

                        try:
                            msg = json.loads(raw)
                            bid, ask = parser(msg)
                            if bid and ask and bid > 0 and ask > 0:
                                ep.bid = bid
                                ep.ask = ask
                                ep.mid = (bid + ask) / 2
                                ep.last_update = time.time()
                                ep.update_count += 1

                                if self._hl_mid > 0:
                                    ep.delta_vs_hl = ep.mid - self._hl_mid
                                    ep.delta_vs_hl_pct = (ep.delta_vs_hl / self._hl_mid) * 100
                        except (json.JSONDecodeError, ValueError, KeyError):
                            pass
                finally:
                    ep.connected = False
                    await ws.close()

            except asyncio.CancelledError:
                ep.connected = False
                break
            except Exception as e:
                ep.connected = False
                logger.warning("%s WS disconnected: %s — reconnecting in %.0fs",
                               cfg["name"], e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)

    # ─── Exchange-specific parsers ──────────────────────────────────

    @staticmethod
    def _parse_binance(msg: dict) -> tuple[float, float]:
        """Binance bookTicker: {"b": "1234.56", "a": "1234.78", ...}"""
        return float(msg.get("b", 0)), float(msg.get("a", 0))

    @staticmethod
    def _parse_coinbase(msg: dict) -> tuple[float, float]:
        """Coinbase ticker: {"best_bid": "1234.56", "best_ask": "1234.78", ...}"""
        if msg.get("type") != "ticker":
            return 0, 0
        return float(msg.get("best_bid", 0)), float(msg.get("best_ask", 0))

    @staticmethod
    def _parse_okx(msg: dict) -> tuple[float, float]:
        """OKX tickers: {"data": [{"bidPx": "1234.56", "askPx": "1234.78"}]}"""
        data = msg.get("data", [])
        if not data:
            return 0, 0
        tick = data[0]
        return float(tick.get("bidPx", 0)), float(tick.get("askPx", 0))

    # ─── State for dashboard ────────────────────────────────────────

    def get_snapshot(self) -> dict:
        """Full snapshot for API/dashboard."""
        return {
            "exchanges": {ex_id: ep.to_dict() for ex_id, ep in self.prices.items()},
            "hlMid": round(self._hl_mid, 2),
            "basisHistory": [b.to_dict() for b in list(self.basis_history)[-120:]],
            "leaderBasis": self._current_basis(),
        }

    def _current_basis(self) -> dict:
        """Current basis between leader and HL."""
        leader = self.get_leader_price()
        if not leader or leader.mid <= 0 or self._hl_mid <= 0:
            return {"basis": 0, "basisPct": 0, "leader": "none", "signal": "neutral"}

        basis = leader.mid - self._hl_mid
        basis_pct = (basis / self._hl_mid) * 100

        # Signal interpretation
        if basis_pct > 0.02:
            signal = "hl_lagging_up"  # HL hasn't caught up to Binance move up
        elif basis_pct < -0.02:
            signal = "hl_lagging_down"  # HL hasn't caught up to Binance move down
        else:
            signal = "neutral"

        return {
            "basis": round(basis, 2),
            "basisPct": round(basis_pct, 4),
            "leader": leader.short,
            "signal": signal,
        }
