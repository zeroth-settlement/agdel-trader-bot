"""Risk manager — stop loss, take profit, watermark tracking, and cooldown."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("risk_manager")


class RiskManager:
    """Manages SL/TP levels, watermark tracking, and trade cooldown."""

    def __init__(self, config: dict):
        at = config.get("autoTrade", {})

        sl = at.get("stopLoss", {})
        self.sl_mode: str = sl.get("mode", "trailing")  # fixed, trailing, off
        self.sl_fixed_pct: float = sl.get("fixedPct", 0.02)
        self.sl_trailing_pct: float = sl.get("trailingPct", 0.015)

        tp = at.get("takeProfit", {})
        self.tp_fixed_pct: float = tp.get("fixedPct", 0.03)
        self.tp_use_signal_target: bool = tp.get("useSignalTarget", True)
        self.tp_trailing_pct: float = tp.get("trailingPct", 0.02)

        cd = at.get("cooldown", {})
        self.cooldown_seconds: int = cd.get("minSecondsBetweenTrades", 900)
        self.strong_override: bool = cd.get("strongSignalOverride", True)
        self.override_min_cc: float = cd.get("overrideMinCC", 0.6)

        # Position state
        self._entry_price: float = 0.0
        self._side: str = "flat"  # long, short, flat
        self._signal_target: float | None = None
        self._watermark_high: float = 0.0
        self._watermark_low: float = float("inf")
        self._has_moved_in_favor: bool = False
        self._has_position: bool = False

        # Dollar-amount overrides (set via API — bypass % calculations)
        self._sl_price_override: float | None = None
        self._tp_price_override: float | None = None

        # Cooldown state
        self._last_trade_at: float = 0.0

    def reset_watermark(self, entry_price: float, side: str, signal_target: float | None = None):
        """Called on position open — initialize watermark tracking."""
        self._entry_price = entry_price
        self._side = side
        self._signal_target = signal_target
        self._watermark_high = entry_price
        self._watermark_low = entry_price
        self._has_moved_in_favor = False
        self._has_position = True
        logger.info("Risk watermark reset: entry=%.2f side=%s target=%s",
                     entry_price, side, signal_target)

    def clear_position(self):
        """Called on position close."""
        self._has_position = False
        self._entry_price = 0.0
        self._side = "flat"
        self._signal_target = None
        self._watermark_high = 0.0
        self._watermark_low = float("inf")
        self._has_moved_in_favor = False
        self._sl_price_override = None
        self._tp_price_override = None

    def set_dollar_targets(self, position_size: float, tp_dollars: float | None = None, sl_dollars: float | None = None):
        """Set SL/TP by dollar P&L targets. Computes exact price levels from position size.

        Args:
            position_size: absolute size in ETH (always positive)
            tp_dollars: take profit in dollars (positive = profit)
            sl_dollars: stop loss in dollars (positive = max loss, will be applied as negative)
        """
        if not self._has_position or position_size <= 0 or self._entry_price <= 0:
            return

        if tp_dollars is not None and tp_dollars > 0:
            price_move = tp_dollars / position_size
            if self._side == "long":
                self._tp_price_override = self._entry_price + price_move
            else:
                self._tp_price_override = self._entry_price - price_move
            logger.info("TP set: $%.2f profit → price $%.2f (entry $%.2f, size %.4f)",
                        tp_dollars, self._tp_price_override, self._entry_price, position_size)

        if sl_dollars is not None and sl_dollars > 0:
            price_move = sl_dollars / position_size
            if self._side == "long":
                self._sl_price_override = self._entry_price - price_move
            else:
                self._sl_price_override = self._entry_price + price_move
            logger.info("SL set: -$%.2f loss → price $%.2f (entry $%.2f, size %.4f)",
                        sl_dollars, self._sl_price_override, self._entry_price, position_size)

    def record_trade(self):
        """Record trade timestamp for cooldown tracking."""
        self._last_trade_at = time.time()

    def update_watermark(self, mark_price: float):
        """Update watermark high/low with current price."""
        if not self._has_position:
            return
        if mark_price > self._watermark_high:
            self._watermark_high = mark_price
        if mark_price < self._watermark_low:
            self._watermark_low = mark_price

        # Track whether price has moved in favor (for trailing TP guard)
        if self._side == "long" and mark_price > self._entry_price:
            self._has_moved_in_favor = True
        elif self._side == "short" and mark_price < self._entry_price:
            self._has_moved_in_favor = True

    def check_stop_loss(self, mark_price: float) -> tuple[bool, str]:
        """Check if stop loss is triggered. Returns (triggered, reason)."""
        if not self._has_position:
            return False, ""

        # Dollar-amount override takes priority
        if self._sl_price_override:
            if self._side == "long" and mark_price <= self._sl_price_override:
                return True, f"SL hit: price ${mark_price:.2f} <= ${self._sl_price_override:.2f}"
            elif self._side == "short" and mark_price >= self._sl_price_override:
                return True, f"SL hit: price ${mark_price:.2f} >= ${self._sl_price_override:.2f}"
            return False, ""

        if self.sl_mode == "off":
            return False, ""

        if self.sl_mode == "fixed":
            if self._side == "long":
                sl_price = self._entry_price * (1 - self.sl_fixed_pct)
                if mark_price <= sl_price:
                    return True, f"Fixed SL: price ${mark_price:.2f} <= ${sl_price:.2f} ({self.sl_fixed_pct*100:.1f}% from entry)"
            elif self._side == "short":
                sl_price = self._entry_price * (1 + self.sl_fixed_pct)
                if mark_price >= sl_price:
                    return True, f"Fixed SL: price ${mark_price:.2f} >= ${sl_price:.2f} ({self.sl_fixed_pct*100:.1f}% from entry)"

        elif self.sl_mode == "trailing":
            if self._side == "long":
                sl_price = self._watermark_high * (1 - self.sl_trailing_pct)
                if mark_price <= sl_price:
                    return True, f"Trailing SL: price ${mark_price:.2f} <= ${sl_price:.2f} ({self.sl_trailing_pct*100:.1f}% from high ${self._watermark_high:.2f})"
            elif self._side == "short":
                sl_price = self._watermark_low * (1 + self.sl_trailing_pct)
                if mark_price >= sl_price:
                    return True, f"Trailing SL: price ${mark_price:.2f} >= ${sl_price:.2f} ({self.sl_trailing_pct*100:.1f}% from low ${self._watermark_low:.2f})"

        return False, ""

    def check_take_profit(self, mark_price: float) -> tuple[bool, str]:
        """Check if take profit is triggered. First hit wins among three checks."""
        if not self._has_position:
            return False, ""

        # Dollar-amount override takes priority
        if self._tp_price_override:
            if self._side == "long" and mark_price >= self._tp_price_override:
                return True, f"TP hit: price ${mark_price:.2f} >= ${self._tp_price_override:.2f}"
            elif self._side == "short" and mark_price <= self._tp_price_override:
                return True, f"TP hit: price ${mark_price:.2f} <= ${self._tp_price_override:.2f}"
            return False, ""

        # 1. Signal target — only if target is ahead of entry (not already reached)
        if self.tp_use_signal_target and self._signal_target:
            if (self._side == "long"
                    and self._signal_target > self._entry_price
                    and mark_price >= self._signal_target):
                return True, f"Signal target TP: price ${mark_price:.2f} >= target ${self._signal_target:.2f}"
            elif (self._side == "short"
                    and self._signal_target < self._entry_price
                    and mark_price <= self._signal_target):
                return True, f"Signal target TP: price ${mark_price:.2f} <= target ${self._signal_target:.2f}"

        # 2. Fixed %
        if self._side == "long":
            tp_price = self._entry_price * (1 + self.tp_fixed_pct)
            if mark_price >= tp_price:
                return True, f"Fixed TP: price ${mark_price:.2f} >= ${tp_price:.2f} ({self.tp_fixed_pct*100:.1f}% from entry)"
        elif self._side == "short":
            tp_price = self._entry_price * (1 - self.tp_fixed_pct)
            if mark_price <= tp_price:
                return True, f"Fixed TP: price ${mark_price:.2f} <= ${tp_price:.2f} ({self.tp_fixed_pct*100:.1f}% from entry)"

        # 3. Trailing TP (only fires after price has moved in favor)
        # Use tighter trail for bounce trades if bounce_trigger is active
        trail_pct = self.tp_trailing_pct
        try:
            import server as _srv
            if hasattr(_srv, 'bounce_trigger') and _srv.bounce_trigger and _srv.bounce_trigger.in_bounce_trade:
                trail_pct = _srv.bounce_trigger.bounce_trailing_tp_pct
        except Exception:
            pass

        if self._has_moved_in_favor:
            if self._side == "long":
                tp_trail = self._watermark_high * (1 - trail_pct)
                if mark_price <= tp_trail:
                    # Clear bounce trade state on exit
                    try:
                        if hasattr(_srv, 'bounce_trigger') and _srv.bounce_trigger:
                            _srv.bounce_trigger.in_bounce_trade = False
                    except Exception:
                        pass
                    return True, f"Trailing TP: price ${mark_price:.2f} <= ${tp_trail:.2f} ({trail_pct*100:.1f}% pullback from high ${self._watermark_high:.2f})"
            elif self._side == "short":
                tp_trail = self._watermark_low * (1 + trail_pct)
                if mark_price >= tp_trail:
                    try:
                        if hasattr(_srv, 'bounce_trigger') and _srv.bounce_trigger:
                            _srv.bounce_trigger.in_bounce_trade = False
                    except Exception:
                        pass
                    return True, f"Trailing TP: price ${mark_price:.2f} >= ${tp_trail:.2f} ({trail_pct*100:.1f}% pullback from low ${self._watermark_low:.2f})"

        return False, ""

    def check_cooldown(self, fast_signal: dict | None, slow_signal: dict | None) -> tuple[bool, str]:
        """Check if cooldown blocks a trade. Returns (on_cooldown, reason)."""
        elapsed = time.time() - self._last_trade_at
        if elapsed >= self.cooldown_seconds:
            return False, ""

        remaining = int(self.cooldown_seconds - elapsed)

        # Strong signal override
        if self.strong_override and fast_signal and slow_signal:
            fast_cc = float(fast_signal.get("conf_calib", 0) or 0)
            slow_cc = float(slow_signal.get("conf_calib", 0) or 0)
            if fast_cc >= self.override_min_cc and slow_cc >= self.override_min_cc:
                logger.info("Cooldown override: fast C*C=%.3f slow C*C=%.3f >= %.3f",
                            fast_cc, slow_cc, self.override_min_cc)
                return False, ""

        return True, f"Cooldown: {remaining}s remaining (min {self.cooldown_seconds}s between trades)"

    def get_sl_tp_levels(self) -> dict:
        """Return computed SL/TP price levels for dashboard display."""
        if not self._has_position:
            return {}

        result = {
            "side": self._side,
            "entryPrice": self._entry_price,
            "watermarkHigh": self._watermark_high,
            "watermarkLow": self._watermark_low,
            "signalTarget": self._signal_target,
            "hasMovedInFavor": self._has_moved_in_favor,
        }

        # Compute SL price
        if self._sl_price_override:
            result["slPrice"] = self._sl_price_override
            result["slMode"] = "dollar"
        elif self.sl_mode == "fixed":
            if self._side == "long":
                result["slPrice"] = self._entry_price * (1 - self.sl_fixed_pct)
            elif self._side == "short":
                result["slPrice"] = self._entry_price * (1 + self.sl_fixed_pct)
            result["slMode"] = "fixed"
        elif self.sl_mode == "trailing":
            if self._side == "long":
                result["slPrice"] = self._watermark_high * (1 - self.sl_trailing_pct)
            elif self._side == "short":
                result["slPrice"] = self._watermark_low * (1 + self.sl_trailing_pct)
            result["slMode"] = "trailing"

        # Compute TP price
        if self._tp_price_override:
            result["tpPrice"] = self._tp_price_override
            result["tpMode"] = "dollar"
        elif self._side == "long":
            result["tpPrice"] = self._entry_price * (1 + self.tp_fixed_pct)
        elif self._side == "short":
            result["tpPrice"] = self._entry_price * (1 - self.tp_fixed_pct)

        # Cooldown info
        elapsed = time.time() - self._last_trade_at
        if elapsed < self.cooldown_seconds:
            result["cooldownRemaining"] = int(self.cooldown_seconds - elapsed)
        else:
            result["cooldownRemaining"] = 0

        return result

    def reload_config(self, config: dict):
        """Hot-reload risk settings from config without losing position state."""
        at = config.get("autoTrade", {})
        sl = at.get("stopLoss", {})
        self.sl_mode = sl.get("mode", "trailing")
        self.sl_fixed_pct = sl.get("fixedPct", 0.02)
        self.sl_trailing_pct = sl.get("trailingPct", 0.015)
        tp = at.get("takeProfit", {})
        self.tp_fixed_pct = tp.get("fixedPct", 0.03)
        self.tp_use_signal_target = tp.get("useSignalTarget", True)
        self.tp_trailing_pct = tp.get("trailingPct", 0.02)
        cd = at.get("cooldown", {})
        self.cooldown_seconds = cd.get("minSecondsBetweenTrades", 900)
        self.strong_override = cd.get("strongSignalOverride", True)
        self.override_min_cc = cd.get("overrideMinCC", 0.6)
        logger.info("Risk config reloaded: SL=%s/%.1f%% TP=%.1f%% cooldown=%ds",
                     self.sl_mode, self.sl_trailing_pct * 100, self.tp_fixed_pct * 100, self.cooldown_seconds)

    def recover_from_position(self, entry_price: float, side: str, mark_price: float):
        """Startup recovery: re-init watermark from existing position."""
        if side == "flat" or entry_price <= 0:
            return
        self.reset_watermark(entry_price, side)
        self.update_watermark(mark_price)
        logger.info("Risk manager recovered: entry=%.2f side=%s mark=%.2f", entry_price, side, mark_price)
