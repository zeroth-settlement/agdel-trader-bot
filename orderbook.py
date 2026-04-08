"""Order book monitor — fetches L2 depth from Hyperliquid and detects walls/imbalance.

Polls the order book every few seconds and provides:
- Bid/ask imbalance ratio (buying vs selling pressure)
- Liquidity walls (price levels with abnormally large size)
- Thin zones (gaps where price can move fast)
- Summary for dashboard and bounce detector
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("orderbook")

HL_INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass
class LiquidityWall:
    """A price level with significantly more size than average."""
    price: float
    size: float
    side: str  # "bid" or "ask"
    multiple: float  # How many times larger than median

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "size": round(self.size, 4),
            "side": self.side,
            "multiple": round(self.multiple, 1),
        }


@dataclass
class OrderBookSnapshot:
    """Processed order book summary."""
    timestamp: float
    mark_price: float
    bid_ask_spread: float
    imbalance_ratio: float  # >1 = more bids (buying pressure), <1 = more asks
    total_bid_size: float
    total_ask_size: float
    bid_walls: List[LiquidityWall]
    ask_walls: List[LiquidityWall]
    nearest_bid_wall: Optional[LiquidityWall]
    nearest_ask_wall: Optional[LiquidityWall]
    bid_depth_10bps: float  # Total bid size within 0.1% of mid
    ask_depth_10bps: float  # Total ask size within 0.1% of mid
    thin_zones: List[Dict[str, float]]  # Gaps in the book

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "markPrice": self.mark_price,
            "spread": round(self.bid_ask_spread, 4),
            "imbalanceRatio": round(self.imbalance_ratio, 3),
            "pressure": "BUY" if self.imbalance_ratio > 1.3 else "SELL" if self.imbalance_ratio < 0.7 else "NEUTRAL",
            "totalBidSize": round(self.total_bid_size, 2),
            "totalAskSize": round(self.total_ask_size, 2),
            "bidWalls": [w.to_dict() for w in self.bid_walls[:3]],
            "askWalls": [w.to_dict() for w in self.ask_walls[:3]],
            "nearestBidWall": self.nearest_bid_wall.to_dict() if self.nearest_bid_wall else None,
            "nearestAskWall": self.nearest_ask_wall.to_dict() if self.nearest_ask_wall else None,
            "bidDepth10bps": round(self.bid_depth_10bps, 2),
            "askDepth10bps": round(self.ask_depth_10bps, 2),
            "thinZones": self.thin_zones[:3],
        }


class OrderBookMonitor:
    """Monitors Hyperliquid L2 order book for ETH."""

    def __init__(self, coin: str = "ETH", wall_threshold: float = 3.0, depth_levels: int = 20):
        self.coin = coin
        self.wall_threshold = wall_threshold  # Multiple of median to count as wall
        self.depth_levels = depth_levels
        self._http = httpx.AsyncClient(timeout=10)
        self._latest: Optional[OrderBookSnapshot] = None
        self._poll_count = 0

    @property
    def latest(self) -> Optional[OrderBookSnapshot]:
        return self._latest

    async def poll(self) -> Optional[OrderBookSnapshot]:
        """Fetch L2 order book and analyze."""
        try:
            resp = await self._http.post(
                HL_INFO_URL,
                json={"type": "l2Book", "coin": self.coin},
            )
            resp.raise_for_status()
            data = resp.json()
            self._poll_count += 1

            snapshot = self._analyze(data)
            self._latest = snapshot
            return snapshot

        except Exception as e:
            logger.error("Order book fetch failed: %s", e)
            return None

    def _analyze(self, data: dict) -> OrderBookSnapshot:
        """Analyze raw L2 book data into a snapshot."""
        levels = data.get("levels", [[], []])
        bids_raw = levels[0] if len(levels) > 0 else []  # [[price, size, numOrders], ...]
        asks_raw = levels[1] if len(levels) > 1 else []

        # Parse into (price, size) tuples
        def parse_level(lvl):
            if isinstance(lvl, dict):
                return float(lvl["px"]), float(lvl["sz"])
            return float(lvl[0]), float(lvl[1])

        bids = [parse_level(b) for b in bids_raw[:self.depth_levels]]
        asks = [parse_level(a) for a in asks_raw[:self.depth_levels]]

        if not bids or not asks:
            return self._empty_snapshot()

        best_bid = bids[0][0]
        best_ask = asks[0][0]
        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid

        # Total sizes
        total_bid = sum(s for _, s in bids)
        total_ask = sum(s for _, s in asks)
        imbalance = total_bid / total_ask if total_ask > 0 else 1.0

        # Depth within 10 basis points of mid
        threshold_10bps = mid * 0.001
        bid_depth_10bps = sum(s for p, s in bids if mid - p <= threshold_10bps)
        ask_depth_10bps = sum(s for p, s in asks if p - mid <= threshold_10bps)

        # Detect walls (levels with size > wall_threshold × median)
        all_sizes = [s for _, s in bids + asks if s > 0]
        if all_sizes:
            median_size = statistics.median(all_sizes)
        else:
            median_size = 1

        bid_walls = []
        for price, size in bids:
            if median_size > 0 and size / median_size >= self.wall_threshold:
                bid_walls.append(LiquidityWall(price, size, "bid", size / median_size))
        bid_walls.sort(key=lambda w: w.size, reverse=True)

        ask_walls = []
        for price, size in asks:
            if median_size > 0 and size / median_size >= self.wall_threshold:
                ask_walls.append(LiquidityWall(price, size, "ask", size / median_size))
        ask_walls.sort(key=lambda w: w.size, reverse=True)

        # Nearest walls to current price
        nearest_bid = min(bid_walls, key=lambda w: mid - w.price, default=None) if bid_walls else None
        nearest_ask = min(ask_walls, key=lambda w: w.price - mid, default=None) if ask_walls else None

        # Detect thin zones (large price gaps between consecutive levels)
        thin_zones = []
        for i in range(1, len(bids)):
            gap = bids[i - 1][0] - bids[i][0]
            if gap > spread * 3:  # Gap larger than 3x the spread
                thin_zones.append({
                    "side": "bid",
                    "from": round(bids[i][0], 2),
                    "to": round(bids[i - 1][0], 2),
                    "gap": round(gap, 2),
                })
        for i in range(1, len(asks)):
            gap = asks[i][0] - asks[i - 1][0]
            if gap > spread * 3:
                thin_zones.append({
                    "side": "ask",
                    "from": round(asks[i - 1][0], 2),
                    "to": round(asks[i][0], 2),
                    "gap": round(gap, 2),
                })

        return OrderBookSnapshot(
            timestamp=time.time(),
            mark_price=mid,
            bid_ask_spread=spread,
            imbalance_ratio=imbalance,
            total_bid_size=total_bid,
            total_ask_size=total_ask,
            bid_walls=bid_walls,
            ask_walls=ask_walls,
            nearest_bid_wall=nearest_bid,
            nearest_ask_wall=nearest_ask,
            bid_depth_10bps=bid_depth_10bps,
            ask_depth_10bps=ask_depth_10bps,
            thin_zones=thin_zones,
        )

    def _empty_snapshot(self) -> OrderBookSnapshot:
        return OrderBookSnapshot(
            timestamp=time.time(), mark_price=0, bid_ask_spread=0,
            imbalance_ratio=1.0, total_bid_size=0, total_ask_size=0,
            bid_walls=[], ask_walls=[], nearest_bid_wall=None,
            nearest_ask_wall=None, bid_depth_10bps=0, ask_depth_10bps=0,
            thin_zones=[],
        )
