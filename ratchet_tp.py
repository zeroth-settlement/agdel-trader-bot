"""Ratcheting take-profit — starts as stop loss, ratchets to breakeven, then rides the run.

Phase 1: PROTECT (entry - 1.5%) — hard stop, no loss bigger than this
Phase 2: BREAKEVEN (entry + fees) — once profitable, TP moves to breakeven
Phase 3: RATCHET — every tick, TP moves up. Buffer grows with profit distance.

The TP only moves UP (for longs) or DOWN (for shorts). Never backwards.

Future: Phase 4 = PYRAMID — add to position when profit buffer is large enough.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("ratchet_tp")


class RatchetTP:
    """Ratcheting take-profit manager for bounce trades."""

    def __init__(self):
        self.active: bool = False
        self.side: str = "flat"  # "long" or "short"
        self.entry_price: float = 0
        self.tp_price: float = 0  # current TP level — only ratchets in profit direction
        self.watermark: float = 0  # best price seen
        self.phase: str = "inactive"  # protect, breakeven, ratchet
        self.initial_stop_pct: float = 0.015  # 1.5% initial stop
        self.fee_buffer: float = 2.0  # $ buffer above breakeven for fees
        self._activated_at: float = 0

    def activate(self, side: str, entry_price: float, fee_estimate: float = 1.0, wide: bool = False):
        """Start ratcheting TP for a new position.

        Args:
            wide: True for long bull/bear runs — wider buffer to avoid shakeouts
        """
        self.active = True
        self.side = side
        self.entry_price = entry_price
        self.fee_buffer = max(fee_estimate * 2.5, 2.0)  # 2.5x fees as minimum buffer
        self.wide_mode = wide
        self._activated_at = time.time()

        if side == "long":
            self.tp_price = entry_price * (1 - self.initial_stop_pct)
            self.watermark = entry_price
        elif side == "short":
            self.tp_price = entry_price * (1 + self.initial_stop_pct)
            self.watermark = entry_price

        self.phase = "protect"
        logger.info("Ratchet TP activated: %s @ $%.2f, initial TP=$%.2f (%.1f%% stop)%s",
                    side, entry_price, self.tp_price, self.initial_stop_pct * 100,
                    " [WIDE MODE]" if wide else "")

    def update(self, mark_price: float) -> tuple[bool, str]:
        """Update TP level with current price. Returns (triggered, reason).

        Call this every tick. The TP ratchets up (long) or down (short).
        """
        if not self.active:
            return False, ""

        if self.side == "long":
            return self._update_long(mark_price)
        elif self.side == "short":
            return self._update_short(mark_price)
        return False, ""

    def _update_long(self, mark_price: float) -> tuple[bool, str]:
        """Ratchet logic for long positions."""
        # Update watermark
        if mark_price > self.watermark:
            self.watermark = mark_price

        profit = mark_price - self.entry_price
        profit_pct = profit / self.entry_price * 100 if self.entry_price else 0

        # Phase transition: protect → breakeven
        if self.phase == "protect" and profit > self.fee_buffer:
            self.phase = "breakeven"
            new_tp = self.entry_price + (self.fee_buffer * 0.5)  # TP just above breakeven
            if new_tp > self.tp_price:
                self.tp_price = new_tp
                logger.info("Ratchet → BREAKEVEN: TP=$%.2f (profit=$%.2f)", self.tp_price, profit)

        # Phase transition: breakeven → ratchet
        if self.phase == "breakeven" and profit > self.fee_buffer * 2:
            self.phase = "ratchet"
            logger.info("Ratchet → RATCHET: riding the run (profit=$%.2f)", profit)

        # Ratchet phase: move TP up every tick
        if self.phase == "ratchet":
            # Buffer scales with profit distance
            # Wide mode: for multi-hour runs, give it room to breathe
            # Normal mode: tighter for quick bounces
            if getattr(self, 'wide_mode', False):
                min_buffer = 4.0           # $4 minimum
                max_buffer_pct = 0.008     # 0.8% max — survives normal pullbacks
                scale_over_pct = 2.0       # scale up over 2% profit
            else:
                min_buffer = 1.5
                max_buffer_pct = 0.003     # 0.3% max
                scale_over_pct = 1.0

            buffer = max(min_buffer, mark_price * max_buffer_pct * min(1.0, profit_pct / scale_over_pct))
            new_tp = mark_price - buffer

            if new_tp > self.tp_price:
                self.tp_price = new_tp

        # Check if TP is triggered
        if mark_price <= self.tp_price:
            reason = f"Ratchet TP ({self.phase}): ${mark_price:.2f} <= TP ${self.tp_price:.2f} (entry ${self.entry_price:.2f}, profit ${profit:+.2f})"
            self.deactivate()
            return True, reason

        return False, ""

    def _update_short(self, mark_price: float) -> tuple[bool, str]:
        """Ratchet logic for short positions."""
        if mark_price < self.watermark:
            self.watermark = mark_price

        profit = self.entry_price - mark_price
        profit_pct = profit / self.entry_price * 100 if self.entry_price else 0

        if self.phase == "protect" and profit > self.fee_buffer:
            self.phase = "breakeven"
            new_tp = self.entry_price - (self.fee_buffer * 0.5)
            if new_tp < self.tp_price:
                self.tp_price = new_tp
                logger.info("Ratchet → BREAKEVEN: TP=$%.2f (profit=$%.2f)", self.tp_price, profit)

        if self.phase == "breakeven" and profit > self.fee_buffer * 2:
            self.phase = "ratchet"
            logger.info("Ratchet → RATCHET: riding the run (profit=$%.2f)", profit)

        if self.phase == "ratchet":
            if getattr(self, 'wide_mode', False):
                min_buffer = 4.0
                max_buffer_pct = 0.008
                scale_over_pct = 2.0
            else:
                min_buffer = 1.5
                max_buffer_pct = 0.003
                scale_over_pct = 1.0
            buffer = max(min_buffer, mark_price * max_buffer_pct * min(1.0, profit_pct / scale_over_pct))
            new_tp = mark_price + buffer
            if new_tp < self.tp_price:
                self.tp_price = new_tp

        if mark_price >= self.tp_price:
            reason = f"Ratchet TP ({self.phase}): ${mark_price:.2f} >= TP ${self.tp_price:.2f} (entry ${self.entry_price:.2f}, profit ${profit:+.2f})"
            self.deactivate()
            return True, reason

        return False, ""

    def deactivate(self):
        """Clear ratchet state."""
        self.active = False
        self.phase = "inactive"
        self.side = "flat"
        logger.info("Ratchet TP deactivated")

    def get_status(self) -> dict:
        profit = 0
        if self.active and self.entry_price:
            if self.side == "long":
                profit = self.watermark - self.entry_price
            elif self.side == "short":
                profit = self.entry_price - self.watermark
        return {
            "active": self.active,
            "phase": self.phase,
            "side": self.side,
            "entry_price": round(self.entry_price, 2),
            "tp_price": round(self.tp_price, 2),
            "watermark": round(self.watermark, 2),
            "current_profit": round(profit, 2),
            "fee_buffer": self.fee_buffer,
        }
