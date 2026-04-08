"""Bounce Detector — watches 1m candles for drop-then-stall pattern.

Reads parameters from the bounce-entry-strategy CxU so the reflector
can tune the detection thresholds based on outcomes.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bounce_detector")


@dataclass
class BounceSignal:
    """A detected bounce entry opportunity."""
    timestamp: float
    peak_price: float       # Pre-drop high
    bottom_price: float     # Low of the drop
    current_price: float    # Price at detection
    drop_pct: float         # Total drop percentage
    entry_price: float      # Suggested entry (current market)
    stop_loss: float        # SL price
    take_profit: float      # TP price (min of peak and +X%)
    size_pct: float         # Suggested position size %
    candle_count: int       # Total candles in pattern (drop + stall)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "peakPrice": self.peak_price,
            "bottomPrice": self.bottom_price,
            "currentPrice": self.current_price,
            "dropPct": round(self.drop_pct, 4),
            "entryPrice": self.entry_price,
            "stopLoss": self.stop_loss,
            "takeProfit": self.take_profit,
            "sizePct": self.size_pct,
            "candleCount": self.candle_count,
        }


class BounceDetector:
    """Detects drop-then-stall bounce patterns on 1m candles."""

    def __init__(self, cxu_store=None):
        self.cxu_store = cxu_store
        self._last_signal_time: float = 0
        self._cooldown: float = 300  # 5 min between signals
        self._load_params()

    def _load_params(self):
        """Load detection parameters from CxU."""
        defaults = {
            "dropThresholdPct": 0.3,
            "dropCandles": 3,
            "stallCandles": 2,
            "stallBodyRatio": 0.25,
            "sizePct": 65,
            "stopLossPct": 5.0,
            "takeProfitPct": 10.0,
        }

        if self.cxu_store:
            cxu = self.cxu_store.by_alias("bounce-entry-strategy")
            if cxu:
                for key in defaults:
                    val = cxu.param_value(key)
                    if val is not None:
                        defaults[key] = val

        self.drop_threshold = defaults["dropThresholdPct"]
        self.drop_candles = int(defaults["dropCandles"])
        self.stall_candles = int(defaults["stallCandles"])
        self.stall_body_ratio = defaults["stallBodyRatio"]
        self.size_pct = defaults["sizePct"]
        self.sl_pct = defaults["stopLossPct"]
        self.tp_pct = defaults["takeProfitPct"]

    def reload_params(self):
        """Reload params from CxU (call after CxU updates)."""
        self._load_params()

    def check(self, candles: List[Dict[str, float]]) -> Optional[BounceSignal]:
        """Check the latest candles for a bounce pattern.

        Args:
            candles: List of candle dicts with keys: open, high, low, close, timestamp
                     Most recent candle last. Need at least (dropCandles + stallCandles).

        Returns:
            BounceSignal if pattern detected, None otherwise.
        """
        needed = self.drop_candles + self.stall_candles
        if len(candles) < needed:
            return None

        # Cooldown check
        now = time.time()
        if now - self._last_signal_time < self._cooldown:
            return None

        # Get the relevant candles (most recent N)
        recent = candles[-needed:]
        drop_candles = recent[:self.drop_candles]
        stall_candles = recent[self.drop_candles:]

        # 1. Check drop: all drop candles should be red (close < open)
        for c in drop_candles:
            if c["close"] >= c["open"]:
                return None  # Not all red

        # 2. Check total drop magnitude
        peak = drop_candles[0]["open"]  # High before the drop started
        bottom = min(c["low"] for c in drop_candles)
        drop_pct = (peak - bottom) / peak * 100

        if drop_pct < self.drop_threshold:
            return None  # Drop not sharp enough

        # 3. Check stall: candle bodies should be small relative to drop candles
        drop_bodies = [abs(c["close"] - c["open"]) for c in drop_candles]
        avg_drop_body = sum(drop_bodies) / len(drop_bodies) if drop_bodies else 1

        for c in stall_candles:
            stall_body = abs(c["close"] - c["open"])
            if avg_drop_body > 0 and stall_body / avg_drop_body > self.stall_body_ratio:
                return None  # Stall candle too big — momentum hasn't exhausted

        # Pattern detected!
        current_price = stall_candles[-1]["close"]
        entry_price = current_price
        stop_loss = entry_price * (1 - self.sl_pct / 100)

        # TP is the lower of: pre-drop peak OR entry + tp_pct%
        tp_from_pct = entry_price * (1 + self.tp_pct / 100)
        take_profit = min(peak, tp_from_pct)

        self._last_signal_time = now

        signal = BounceSignal(
            timestamp=now,
            peak_price=peak,
            bottom_price=bottom,
            current_price=current_price,
            drop_pct=drop_pct,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            size_pct=self.size_pct,
            candle_count=needed,
        )

        logger.info(
            "BOUNCE DETECTED: drop=%.2f%% peak=$%.2f bottom=$%.2f entry=$%.2f SL=$%.2f TP=$%.2f",
            drop_pct, peak, bottom, entry_price, stop_loss, take_profit,
        )

        return signal
