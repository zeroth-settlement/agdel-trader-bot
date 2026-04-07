"""Band bounce trigger — automatic entry when price hits band extreme + momentum stalls.

This is CODE, not a prompt instruction. When enabled, it fires independently
of the LLM decision. The LLM still manages the position after entry.

Toggle via API: POST /api/bounce/toggle
Status via API: GET /api/bounce/status

SAFETY: defaults to OFF. Must be explicitly enabled.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("bounce")


class BounceTrigger:
    """Fires a long/short entry when price hits a band extreme and momentum stalls."""

    def __init__(self):
        self.enabled: bool = False
        self.direction: str = "long"  # "long", "short", or "both" — default long for bounce
        self.in_bounce_trade: bool = False
        self.bounce_entry_price: float = 0
        self.last_fired: float = 0
        self.cooldown_seconds: float = 180
        self.band_threshold_low: float = 20
        self.band_threshold_high: float = 80
        self.momentum_stall_threshold: float = 0.20
        self.bounce_trailing_tp_pct: float = 0.015
        self.protection_seconds: float = 300
        self._fire_count: int = 0
        self._last_check: dict = {}

    def check(self, mark_price: float, position_in_range: float,
              trend_pct: float, momentum: str, current_side: str) -> str | None:
        """Check if bounce trigger should fire.

        Returns action string ('open_long', 'open_short') or None.
        """
        if not self.enabled:
            return None

        now = time.time()
        if now - self.last_fired < self.cooldown_seconds:
            return None

        # Don't trigger if already in a position
        if current_side != "flat":
            return None

        self._last_check = {
            "price": mark_price,
            "position_in_range": round(position_in_range, 1),
            "trend_pct": round(trend_pct, 4),
            "momentum": momentum,
            "timestamp": now,
        }

        # LONG bounce: price at lower band + momentum stalling/slowing
        if (self.direction in ("long", "both")
                and position_in_range <= self.band_threshold_low
                and abs(trend_pct) < self.momentum_stall_threshold
                and momentum in ("SLOWING", "steady")):
            self.last_fired = now
            self._fire_count += 1
            self.in_bounce_trade = True
            self.bounce_entry_price = mark_price
            logger.info("BOUNCE TRIGGER: LONG at %.0f%% of range, trend=%.3f%%, momentum=%s",
                        position_in_range, trend_pct, momentum)
            return "open_long"

        # SHORT bounce: price at upper band + momentum stalling/slowing
        if (self.direction in ("short", "both")
                and position_in_range >= self.band_threshold_high
                and abs(trend_pct) < self.momentum_stall_threshold
                and momentum in ("SLOWING", "steady")):
            self.last_fired = now
            self._fire_count += 1
            self.in_bounce_trade = True
            self.bounce_entry_price = mark_price
            logger.info("BOUNCE TRIGGER: SHORT at %.0f%% of range, trend=%.3f%%, momentum=%s",
                        position_in_range, trend_pct, momentum)
            return "open_short"

        return None

    def is_protected(self) -> bool:
        """True if a bounce trade is active and within the protection window."""
        if not self.in_bounce_trade:
            return False
        return (time.time() - self.last_fired) < self.protection_seconds

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "fire_count": self._fire_count,
            "last_fired": self.last_fired,
            "cooldown_seconds": self.cooldown_seconds,
            "thresholds": {
                "band_low": self.band_threshold_low,
                "band_high": self.band_threshold_high,
                "momentum_stall": self.momentum_stall_threshold,
            },
            "last_check": self._last_check,
        }
