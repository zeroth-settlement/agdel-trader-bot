"""Alert system — monitor conditions and notify when triggered.

Users define watches (conditions to monitor). Each tick, the alert manager
checks all active watches against current market state. When a watch triggers,
it sends a push notification via ntfy and a WebSocket alert to the dashboard.

Watches have cooldowns to prevent spam.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("alerts")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")


@dataclass
class Watch:
    """A condition to monitor."""
    id: str
    name: str
    description: str  # Human description of what we're watching for
    conditions: Dict[str, Any]  # Deterministic conditions to check
    cooldown_seconds: int = 300  # Min seconds between alerts (default 5 min)
    active: bool = True
    created_at: str = ""
    last_triggered: float = 0
    trigger_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "conditions": self.conditions,
            "cooldownSeconds": self.cooldown_seconds,
            "active": self.active,
            "createdAt": self.created_at,
            "lastTriggered": self.last_triggered,
            "triggerCount": self.trigger_count,
        }


class AlertManager:
    """Manages watches and checks them against market state each tick."""

    def __init__(self):
        self.watches: Dict[str, Watch] = {}
        self._http = httpx.AsyncClient(timeout=5)

    def add_watch(
        self,
        name: str,
        description: str,
        conditions: Dict[str, Any],
        cooldown_seconds: int = 300,
    ) -> Watch:
        """Add a new watch.

        Conditions dict supports:
            bb_below: float       — trigger when Bollinger position drops below this %
            bb_above: float       — trigger when Bollinger position rises above this %
            price_below: float    — trigger when price drops below this level
            price_above: float    — trigger when price rises above this level
            trend_below: float    — trigger when trend % drops below this
            trend_above: float    — trigger when trend % rises above this
            regime_is: str        — trigger when regime matches (e.g., "volatile")
            regime_not: str       — trigger when regime changes away from this
        """
        watch_id = f"watch-{int(time.time())}-{len(self.watches)}"
        watch = Watch(
            id=watch_id,
            name=name,
            description=description,
            conditions=conditions,
            cooldown_seconds=cooldown_seconds,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.watches[watch_id] = watch
        logger.info("Watch added: %s — %s", name, description)
        return watch

    def remove_watch(self, watch_id: str) -> bool:
        if watch_id in self.watches:
            del self.watches[watch_id]
            return True
        return False

    def list_watches(self) -> List[dict]:
        return [w.to_dict() for w in self.watches.values()]

    async def check_all(
        self,
        mark_price: float,
        indicators: Dict[str, Any],
        regime: str,
        position: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Check all active watches against current state. Returns triggered alerts."""
        triggered = []
        now = time.time()

        for watch in self.watches.values():
            if not watch.active:
                continue
            if now - watch.last_triggered < watch.cooldown_seconds:
                continue

            if self._check_conditions(watch.conditions, mark_price, indicators, regime, position):
                watch.last_triggered = now
                watch.trigger_count += 1

                alert = {
                    "watchId": watch.id,
                    "name": watch.name,
                    "description": watch.description,
                    "price": mark_price,
                    "regime": regime,
                    "indicators": indicators,
                    "triggeredAt": datetime.now(timezone.utc).isoformat(),
                    "triggerCount": watch.trigger_count,
                }
                triggered.append(alert)

                # Send push notification
                await self._send_notification(watch, mark_price, regime, indicators)

                logger.info("ALERT: %s triggered at $%.2f", watch.name, mark_price)

        return triggered

    def _check_conditions(
        self,
        conditions: Dict[str, Any],
        mark_price: float,
        indicators: Dict[str, Any],
        regime: str,
        position: Dict[str, Any],
    ) -> bool:
        """Check if ALL conditions are met (AND logic)."""
        bb_pos = indicators.get("bollingerPosition", 50)
        trend = indicators.get("trendPct", 0)

        for key, value in conditions.items():
            if key == "bb_below" and bb_pos >= value:
                return False
            elif key == "bb_above" and bb_pos <= value:
                return False
            elif key == "price_below" and mark_price >= value:
                return False
            elif key == "price_above" and mark_price <= value:
                return False
            elif key == "trend_below" and trend >= value:
                return False
            elif key == "trend_above" and trend <= value:
                return False
            elif key == "regime_is" and regime != value:
                return False
            elif key == "regime_not" and regime == value:
                return False

        return True

    async def _send_notification(
        self,
        watch: Watch,
        mark_price: float,
        regime: str,
        indicators: Dict[str, Any],
    ):
        """Send push notification via ntfy."""
        if not NTFY_TOPIC:
            return

        bb_pos = indicators.get("bollingerPosition", 50)
        trend = indicators.get("trendPct", 0)

        title = f"🔔 {watch.name}"
        message = (
            f"{watch.description}\n\n"
            f"Price: ${mark_price:,.2f}\n"
            f"Regime: {regime}\n"
            f"Bollinger: {bb_pos:.0f}%\n"
            f"Trend: {trend:.3f}%"
        )

        try:
            resp = await self._http.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                content=message.encode(),
                headers={
                    "Title": title,
                    "Priority": "high",
                    "Tags": "chart_with_downwards_trend,eth",
                },
            )
            logger.info("ntfy sent: %s (status=%s)", watch.name, resp.status_code)
        except Exception as e:
            logger.warning("Failed to send ntfy: %s — recreating client", e)
            self._http = httpx.AsyncClient(timeout=5)
