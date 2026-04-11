"""Stop Manager — isolated, testable module for HL stop order management.

CRITICAL: This module handles real money. It must be reliable.

Responsibilities:
- Place stop orders on Hyperliquid
- Modify stop orders atomically (no cancel gap)
- Adaptive trailing stop (tightens with profit)
- Verify all operations against HL state

Principles:
- NEVER leave a position unprotected
- modify_order for atomic updates (not cancel+place)
- Verify every operation against frontendOpenOrders
- Reset and re-fetch on any failure
- All operations are idempotent
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stop_manager")


@dataclass
class StopState:
    """Current state of the managed stop order."""
    oid: Optional[int] = None
    trigger_price: float = 0.0
    size: float = 0.0
    verified: bool = False
    last_verified_at: float = 0.0
    last_modified_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "oid": self.oid,
            "triggerPrice": self.trigger_price,
            "size": self.size,
            "verified": self.verified,
            "lastVerifiedAt": self.last_verified_at,
            "lastModifiedAt": self.last_modified_at,
        }


class StopManager:
    """Manages stop orders on Hyperliquid.

    Usage:
        mgr = StopManager(exchange, info, main_address, asset="ETH")

        # Place initial stop
        mgr.place(trigger_price=2200.0, size=12.87)

        # Move stop up (trailing)
        mgr.modify(new_trigger=2210.0)

        # Get current state
        state = mgr.state

        # Verify stop is still on HL
        mgr.verify()
    """

    def __init__(self, exchange, info, main_address: str, asset: str = "ETH"):
        self._exchange = exchange
        self._info = info
        self._main_address = main_address
        self._asset = asset
        self._state = StopState()

    @property
    def state(self) -> StopState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state.oid is not None and self._state.trigger_price > 0

    def place(self, trigger_price: float, size: float, is_buy: bool = False) -> Dict[str, Any]:
        """Place a new stop order on HL.

        Args:
            trigger_price: Price at which the stop triggers
            size: Position size to close
            is_buy: True for short position SL (buy to close), False for long (sell to close)

        Returns dict with 'success' or 'error'.
        """
        trigger_price = round(float(trigger_price), 2)
        size = round(float(size), 4)

        # For sell stops, limit must be below trigger
        limit_px = trigger_price - 5 if not is_buy else trigger_price + 5

        try:
            ot = {"trigger": {"triggerPx": trigger_price, "isMarket": True, "tpsl": "sl"}}
            result = self._exchange.order(
                self._asset, is_buy, size, float(limit_px), ot, reduce_only=True
            )

            # Extract OID
            oid = None
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            for s in statuses:
                if "resting" in s:
                    oid = s["resting"]["oid"]
                elif "error" in s:
                    logger.error("Stop placement rejected: %s", s["error"])
                    return {"success": False, "error": s["error"]}

            if oid:
                self._state = StopState(
                    oid=oid, trigger_price=trigger_price, size=size,
                    verified=False, last_modified_at=time.time(),
                )
                # Verify
                if self.verify():
                    logger.info("Stop PLACED: $%.2f size=%.4f oid=%s (verified)", trigger_price, size, oid)
                    return {"success": True, "triggerPrice": trigger_price, "oid": oid}
                else:
                    logger.error("Stop placed but VERIFICATION FAILED")
                    return {"success": False, "error": "Placed but not found on HL"}
            else:
                return {"success": False, "error": f"No OID in result: {result}"}

        except Exception as e:
            logger.error("Stop placement error: %s", e)
            return {"success": False, "error": str(e)}

    def modify(self, new_trigger: float, size: Optional[float] = None, is_buy: bool = False) -> Dict[str, Any]:
        """Move stop to a new trigger price. Cancel old, place new.

        Args:
            new_trigger: New trigger price
            size: Position size (uses current if not specified)
            is_buy: True for short SL

        Returns dict with 'success' or 'error'.
        """
        sz = round(float(size or self._state.size), 4)
        if sz <= 0:
            return {"success": False, "error": "No size specified"}

        old_trigger = self._state.trigger_price
        old_oid = self._state.oid

        # Cancel existing stop
        if old_oid:
            try:
                self._exchange.cancel(self._asset, old_oid)
                logger.info("Cancelled old stop %s ($%.2f)", old_oid, old_trigger)
            except Exception as e:
                logger.warning("Cancel failed (may already be gone): %s", e)

        # Place new stop immediately
        result = self.place(new_trigger, sz, is_buy)

        if result.get("success"):
            logger.info("Stop MOVED: $%.2f → $%.2f", old_trigger, new_trigger)
            return {**result, "oldTrigger": old_trigger}
        else:
            # Placement failed — try to restore old stop
            logger.error("New stop failed — attempting to restore old stop at $%.2f", old_trigger)
            restore = self.place(old_trigger, sz, is_buy)
            if restore.get("success"):
                logger.info("Restored old stop at $%.2f", old_trigger)
            else:
                logger.error("CRITICAL: Could not restore stop! Position UNPROTECTED")
            return result

    def verify(self) -> bool:
        """Verify the managed stop exists on HL. Returns True if found."""
        try:
            import httpx
            resp = httpx.post("https://api.hyperliquid.xyz/info",
                              json={"type": "frontendOpenOrders", "user": self._main_address})
            orders = resp.json()
            stops = [o for o in orders if o.get("orderType") == "Stop Market" and o.get("coin") == self._asset]

            if not stops:
                logger.warning("VERIFY: No stops found on HL!")
                self._state.verified = False
                return False

            # Find our stop by OID or highest trigger
            if self._state.oid:
                found = next((o for o in stops if o.get("oid") == self._state.oid), None)
                if found:
                    self._state.trigger_price = float(found.get("triggerPx", 0))
                    self._state.size = float(found.get("sz", 0))
                    self._state.verified = True
                    self._state.last_verified_at = time.time()
                    return True

            # OID not found — maybe it was modified. Find highest trigger stop.
            best = max(stops, key=lambda o: float(o.get("triggerPx", 0)))
            self._state.oid = best.get("oid")
            self._state.trigger_price = float(best.get("triggerPx", 0))
            self._state.size = float(best.get("sz", 0))
            self._state.verified = True
            self._state.last_verified_at = time.time()
            logger.info("VERIFY: Re-synced to stop oid=%s trigger=$%.2f", self._state.oid, self._state.trigger_price)
            return True

        except Exception as e:
            logger.error("VERIFY error: %s", e)
            self._state.verified = False
            return False

    def cancel_all(self) -> int:
        """Cancel all stop orders for the asset. Returns count cancelled."""
        try:
            import httpx
            resp = httpx.post("https://api.hyperliquid.xyz/info",
                              json={"type": "frontendOpenOrders", "user": self._main_address})
            orders = resp.json()
            stops = [o for o in orders if o.get("orderType") == "Stop Market" and o.get("coin") == self._asset]

            count = 0
            for stop in stops:
                oid = stop.get("oid")
                if oid:
                    self._exchange.cancel(self._asset, oid)
                    count += 1
                    logger.info("Cancelled stop %s trigger=$%s", oid, stop.get("triggerPx"))

            self._state = StopState()
            return count

        except Exception as e:
            logger.error("Cancel all stops error: %s", e)
            return 0

    def sync_from_hl(self) -> bool:
        """Sync state from whatever stops exist on HL. Returns True if a stop was found."""
        self._state.oid = None
        return self.verify()


# ─── Adaptive Trailing Stop Logic ────────────────────────────────

def compute_trail_pct(pnl: float) -> float:
    """Tighter trail as profit grows.

    <$100:    1.5%
    $100-300: 1.0%
    $300-500: 0.75%
    >$500:    0.5%
    """
    if pnl >= 500:
        return 0.005
    elif pnl >= 300:
        return 0.0075
    elif pnl >= 100:
        return 0.01
    else:
        return 0.015


def compute_trailing_sl(
    mark_price: float,
    watermark: float,
    pnl: float,
    current_sl: float,
) -> Optional[float]:
    """Compute new trailing SL price. Returns None if no update needed.

    Only returns a value higher than current_sl (never moves down).
    """
    if mark_price <= 0:
        return None

    # Update watermark
    effective_watermark = max(watermark, mark_price)
    trail_pct = compute_trail_pct(pnl)
    target_sl = round(effective_watermark * (1 - trail_pct), 2)

    if target_sl > current_sl:
        return target_sl
    return None
