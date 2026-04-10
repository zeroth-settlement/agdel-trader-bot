"""Hyperliquid execution — unified paper + live trading interface."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx
import websockets

logger = logging.getLogger("hl_trader")

HL_API_URL = "https://api.hyperliquid.xyz"
HL_WS_URL = "wss://api.hyperliquid.xyz/ws"
TAKER_FEE_PCT = 0.000432  # 0.0432% per side (measured from actual HL trades)
MIN_ORDER_VALUE_USD = 11.0  # Hyperliquid requires $10 minimum; use $11 for safety


@dataclass
class Position:
    size: float = 0.0         # positive = long, negative = short, 0 = flat
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    leverage: int = 1
    paper: bool = True

    @property
    def side(self) -> str:
        if self.size > 0:
            return "long"
        elif self.size < 0:
            return "short"
        return "flat"

    def to_dict(self) -> dict:
        return {
            "size": self.size,
            "side": self.side,
            "entryPrice": self.entry_price,
            "unrealizedPnl": round(self.unrealized_pnl, 4),
            "leverage": self.leverage,
            "paper": self.paper,
        }


@dataclass
class TradeResult:
    success: bool
    action: str
    size: float
    price: float
    fee: float = 0.0
    pnl: float = 0.0
    error: str | None = None
    timestamp: float = field(default_factory=time.time)
    mode: str = "paper"  # "paper" or "live" — source of truth for PnL attribution

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "action": self.action,
            "size": round(self.size, 6),
            "price": round(self.price, 2),
            "fee": round(self.fee, 4),
            "pnl": round(self.pnl, 4),
            "error": self.error,
            "timestamp": self.timestamp,
            "mode": self.mode,
        }


class HLTrader:
    """Unified trading interface for Hyperliquid perpetuals."""

    def __init__(self, config: dict, mode: str = "paper"):
        self.mode = mode
        tc = config.get("trading", {})
        self.asset: str = tc.get("assets", ["ETH"])[0]
        self.max_leverage: int = tc.get("maxLeverage", 15)
        self.risk_per_trade: float = tc.get("riskPerTrade", 0.0075)

        # Paper state
        self._paper_balance: float = tc.get("paperStartingBalanceUsd", 1000.0)
        self._paper_starting_balance: float = self._paper_balance
        self._paper_position: Position | None = None
        self._paper_trades: list[dict] = []

        # Live state
        self._http = httpx.AsyncClient(timeout=15, base_url=HL_API_URL)
        self._exchange: Any = None  # hyperliquid Exchange instance
        self._info: Any = None      # hyperliquid Info instance
        self._main_address: str = ""
        self._asset_index: int | None = None
        self._sz_decimals: int = 4

    async def connect(self):
        """Initialize connections. For live mode, set up hyperliquid SDK."""
        self._main_address = os.environ.get("HYPERLIQUID_WALLET_ADDRESS", "")
        self._ws_price: float = 0.0
        self._ws_connected: bool = False
        self._ws_task: Optional[asyncio.Task] = None
        self._price_callback: Optional[Callable[[float], Any]] = None

        if self.mode == "live":
            try:
                from hyperliquid.exchange import Exchange
                from hyperliquid.info import Info
                from hyperliquid.utils import constants
                from eth_account import Account

                private_key = os.environ.get("TRADERBOT_WALLET_PRIVATE_KEY", "")
                wallet = Account.from_key(private_key)

                self._info = Info(constants.MAINNET_API_URL)
                # Agent/API wallet trades on behalf of the parent account
                self._exchange = Exchange(
                    wallet, constants.MAINNET_API_URL,
                    account_address=self._main_address or None,
                )

                # Fetch asset metadata for index and size decimals
                meta = self._info.meta()
                for i, asset_info in enumerate(meta.get("universe", [])):
                    if asset_info["name"] == self.asset:
                        self._asset_index = i
                        self._sz_decimals = asset_info.get("szDecimals", 4)
                        break

                logger.info("Live trading connected: wallet=%s asset=%s idx=%s",
                            wallet.address, self.asset, self._asset_index)
            except Exception as e:
                logger.error("Failed to init live trading: %s", e)
                raise
        else:
            logger.info("Paper trading mode: starting balance=$%.2f", self._paper_balance)

    async def start_price_feed(self, callback: Callable[[float], Any] | None = None):
        """Start WebSocket price feed from Hyperliquid. Calls callback(price) on each update."""
        self._price_callback = callback
        self._ws_task = asyncio.create_task(self._ws_price_loop())
        logger.info("Started Hyperliquid WebSocket price feed for %s", self.asset)

    async def stop_price_feed(self):
        """Stop the WebSocket price feed."""
        if self._ws_task:
            self._ws_task.cancel()
            self._ws_task = None
        self._ws_connected = False

    async def _ws_price_loop(self):
        """Reconnecting WebSocket loop for allMids subscription."""
        backoff = 1.0
        while True:
            try:
                # Timeout the connect itself to prevent hanging
                ws = await asyncio.wait_for(
                    websockets.connect(HL_WS_URL, ping_interval=20, ping_timeout=10,
                                       close_timeout=5, open_timeout=10),
                    timeout=15,
                )
                try:
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": {"type": "allMids"},
                    }))
                    self._ws_connected = True
                    backoff = 1.0
                    logger.info("Hyperliquid WS connected — streaming allMids")

                    # Read with per-message timeout to detect stale connections
                    msg_count = 0
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            logger.warning("Hyperliquid WS stale (no data 30s, %d msgs received) — reconnecting", msg_count)
                            break

                        msg_count += 1
                        try:
                            msg = json.loads(raw)
                            data = msg.get("data", {})
                            mids = data.get("mids", {})
                            price_str = mids.get(self.asset)
                            if price_str:
                                price = float(price_str)
                                self._ws_price = price
                                if self._price_callback:
                                    try:
                                        result = self._price_callback(price)
                                        if asyncio.iscoroutine(result):
                                            # Fire-and-forget with error logging
                                            async def _safe_cb(coro):
                                                try:
                                                    await coro
                                                except Exception as e:
                                                    logger.warning("Price callback error: %s", e)
                                            asyncio.create_task(_safe_cb(result))
                                    except Exception as cb_err:
                                        logger.warning("Price callback sync error: %s", cb_err)
                        except (json.JSONDecodeError, ValueError):
                            pass
                finally:
                    self._ws_connected = False
                    await ws.close()

            except asyncio.CancelledError:
                logger.info("Hyperliquid WS feed cancelled")
                break
            except Exception as e:
                self._ws_connected = False
                logger.warning("Hyperliquid WS disconnected: %s — reconnecting in %.0fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)

    @property
    def ws_connected(self) -> bool:
        return self._ws_connected

    async def get_hl_account(self) -> tuple[Position | None, dict]:
        """Always fetch position + portfolio from Hyperliquid API (single call).
        Uses a fresh HTTP client to avoid shared-state concurrency issues."""
        empty_portfolio = {"equity": 0, "availableBalance": 0, "pnl": 0, "paper": False}
        if not self._main_address:
            return None, empty_portfolio
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{HL_API_URL}/info", json={
                    "type": "clearinghouseState",
                    "user": self._main_address,
                })
            resp.raise_for_status()
            state = resp.json()

            # Position
            position = None
            for pos in state.get("assetPositions", []):
                p = pos.get("position", {})
                if p.get("coin") == self.asset:
                    size = float(p.get("szi", 0))
                    entry = float(p.get("entryPx", 0))
                    upnl = float(p.get("unrealizedPnl", 0))
                    lev = int(float(p.get("leverage", {}).get("value", 1)))
                    position = Position(size=size, entry_price=entry,
                                        unrealized_pnl=upnl, leverage=lev, paper=False)
                    break

            # Portfolio
            margin = state.get("marginSummary", {})
            equity = float(margin.get("accountValue", 0))
            available = float(margin.get("totalRawUsd", 0))

            # Unified accounts: spot USDC backs perp trading
            spot_usdc = await self._get_spot_usdc()
            if spot_usdc > equity:
                equity = spot_usdc
                available = max(available, spot_usdc)

            portfolio = {
                "equity": round(equity, 2),
                "availableBalance": round(available, 2),
                "pnl": 0.0,
                "paper": False,
            }

            return position, portfolio
        except Exception as e:
            logger.error("Failed to get HL account: %s", e)
            return None, empty_portfolio

    async def get_mark_price(self) -> float:
        """Return current mid price. Prefers real-time WS price, falls back to REST."""
        if self._ws_price > 0:
            return self._ws_price
        # Fallback to REST
        try:
            resp = await self._http.post("/info", json={"type": "allMids"})
            resp.raise_for_status()
            mids = resp.json()
            price_str = mids.get(self.asset, "0")
            return float(price_str)
        except Exception as e:
            logger.error("Failed to fetch mark price: %s", e)
            return 0.0

    async def get_position(self) -> Position | None:
        """Get current position (paper or live)."""
        if self.mode == "paper":
            return self._paper_position

        # Live mode
        try:
            resp = await self._http.post("/info", json={
                "type": "clearinghouseState",
                "user": self._main_address,
            })
            resp.raise_for_status()
            state = resp.json()
            for pos in state.get("assetPositions", []):
                p = pos.get("position", {})
                if p.get("coin") == self.asset:
                    size = float(p.get("szi", 0))
                    entry = float(p.get("entryPx", 0))
                    upnl = float(p.get("unrealizedPnl", 0))
                    lev = int(float(p.get("leverage", {}).get("value", 1)))
                    return Position(size=size, entry_price=entry,
                                    unrealized_pnl=upnl, leverage=lev, paper=False)
            return None
        except Exception as e:
            logger.error("Failed to get position: %s", e)
            return None

    async def get_portfolio(self) -> dict:
        """Get account equity and balance (includes spot USDC for unified accounts)."""
        if self.mode == "paper":
            upnl = 0.0
            if self._paper_position:
                upnl = self._paper_position.unrealized_pnl
            equity = self._paper_balance + upnl
            return {
                "equity": round(equity, 2),
                "availableBalance": round(self._paper_balance, 2),
                "pnl": round(equity - self._paper_starting_balance, 2),
                "paper": True,
            }

        try:
            resp = await self._http.post("/info", json={
                "type": "clearinghouseState",
                "user": self._main_address,
            })
            resp.raise_for_status()
            state = resp.json()
            margin = state.get("marginSummary", {})
            equity = float(margin.get("accountValue", 0))
            available = float(margin.get("totalRawUsd", 0))

            # Unified accounts: spot USDC backs perp trading
            spot_usdc = await self._get_spot_usdc()
            if spot_usdc > equity:
                equity = spot_usdc
                available = max(available, spot_usdc)

            return {
                "equity": round(equity, 2),
                "availableBalance": round(available, 2),
                "pnl": 0.0,
                "paper": False,
            }
        except Exception as e:
            logger.error("Failed to get portfolio: %s", e)
            return {"equity": 0, "availableBalance": 0, "pnl": 0, "paper": self.mode == "paper"}

    async def _get_spot_usdc(self) -> float:
        """Fetch spot USDC balance for unified account support."""
        if not self._main_address:
            return 0.0
        try:
            resp = await self._http.post("/info", json={
                "type": "spotClearinghouseState",
                "user": self._main_address,
            })
            resp.raise_for_status()
            data = resp.json()
            for bal in data.get("balances", []):
                if bal.get("coin") == "USDC":
                    return float(bal.get("total", 0))
        except Exception as e:
            logger.debug("Spot USDC check failed: %s", e)
        return 0.0

    async def execute_notional(self, action: str, notional_usd: float, mark_price: float) -> TradeResult | None:
        """Execute with a specific USD notional (for training mode — bypasses risk formula).
        For close actions, notional_usd is ignored."""
        if action == "hold":
            return None
        if action == "close":
            return await self.execute(action, 100, mark_price)

        size = round(notional_usd / mark_price, self._sz_decimals) if mark_price > 0 else 0
        fee = notional_usd * TAKER_FEE_PCT

        if self.mode == "paper":
            pos = self._paper_position
            pnl = 0.0
            if pos and pos.size != 0:
                pnl = pos.unrealized_pnl
                self._paper_balance += pnl - fee

            direction = 1 if action in ("open_long", "flip_long") else -1
            self._paper_position = Position(
                size=size * direction, entry_price=mark_price,
                leverage=self.max_leverage, paper=True,
            )
            result = TradeResult(
                success=True, action=action, size=size,
                price=mark_price, fee=fee, pnl=pnl, mode="paper",
            )
            self._paper_trades.append(result.to_dict())
            logger.info("Paper trade (notional): %s size=%.4f notional=$%.2f price=%.2f",
                         action, size, notional_usd, mark_price)
            return result
        else:
            # Live mode — use SDK directly with computed size
            if not self._exchange:
                return TradeResult(success=False, action=action, size=0,
                                   price=mark_price, error="Exchange not initialized", mode="live")
            if notional_usd < MIN_ORDER_VALUE_USD:
                return TradeResult(success=False, action=action, size=0,
                                   price=mark_price, error=f"Notional ${notional_usd:.2f} below minimum ${MIN_ORDER_VALUE_USD:.0f}", mode="live")
            try:
                is_buy = action in ("open_long", "flip_long")
                if action in ("flip_long", "flip_short"):
                    self._exchange.market_close(self.asset)
                result = self._exchange.market_open(self.asset, is_buy, size)
                if isinstance(result, dict) and result.get("status") == "ok":
                    return TradeResult(success=True, action=action, size=size,
                                       price=mark_price, fee=fee, pnl=0, mode="live")
                else:
                    err = str(result)[:200] if result else "SDK returned None"
                    return TradeResult(success=False, action=action, size=size,
                                       price=mark_price, error=err, mode="live")
            except Exception as e:
                return TradeResult(success=False, action=action, size=size,
                                   price=mark_price, error=str(e), mode="live")

    async def execute(self, action: str, size_pct: float, mark_price: float) -> TradeResult | None:
        """Execute a trade action. Returns None if action is hold."""
        if action == "hold":
            return None
        # Close/flip actions don't need a size — they operate on the existing position
        if size_pct <= 0 and action not in ("close", "flip_long", "flip_short"):
            return None

        if self.mode == "paper":
            return await self._execute_paper(action, size_pct, mark_price)
        else:
            return await self._execute_live(action, size_pct, mark_price)

    async def _execute_paper(self, action: str, size_pct: float, mark_price: float) -> TradeResult:
        """Simulate a trade in paper mode."""
        pos = self._paper_position
        portfolio = await self.get_portfolio()
        equity = portfolio["equity"]

        # Compute size in asset units
        notional = equity * self.risk_per_trade * self.max_leverage * size_pct
        size = notional / mark_price if mark_price > 0 else 0
        fee = notional * TAKER_FEE_PCT
        pnl = 0.0

        if action in ("open_long", "open_short"):
            # Close any existing position first
            if pos and pos.size != 0:
                pnl = pos.unrealized_pnl
                self._paper_balance += pnl - fee
            direction = 1 if action == "open_long" else -1
            self._paper_position = Position(
                size=size * direction, entry_price=mark_price,
                leverage=self.max_leverage, paper=True,
            )

        elif action == "increase" and pos:
            old_notional = abs(pos.size) * pos.entry_price
            new_notional = abs(size) * mark_price
            total_size = abs(pos.size) + size
            avg_entry = (old_notional + new_notional) / total_size if total_size > 0 else mark_price
            direction = 1 if pos.size > 0 else -1
            self._paper_position = Position(
                size=total_size * direction, entry_price=avg_entry,
                leverage=self.max_leverage, paper=True,
            )

        elif action in ("decrease_long", "decrease_short") and pos:
            reduce_size = min(abs(size), abs(pos.size) * self.risk_per_trade)
            reduce_fraction = reduce_size / abs(pos.size) if pos.size != 0 else 0
            pnl = pos.unrealized_pnl * reduce_fraction
            remaining = abs(pos.size) - reduce_size
            direction = 1 if pos.size > 0 else -1
            if remaining > 0.0001:
                self._paper_position = Position(
                    size=remaining * direction, entry_price=pos.entry_price,
                    leverage=self.max_leverage, paper=True,
                )
            else:
                self._paper_position = None
            self._paper_balance += pnl - fee

        elif action == "close" and pos:
            pnl = pos.unrealized_pnl
            self._paper_balance += pnl - fee
            self._paper_position = None

        elif action in ("flip_long", "flip_short") and pos:
            pnl = pos.unrealized_pnl
            self._paper_balance += pnl - fee
            direction = 1 if action == "flip_long" else -1
            self._paper_position = Position(
                size=size * direction, entry_price=mark_price,
                leverage=self.max_leverage, paper=True,
            )
            fee *= 2  # double fee for close + open

        else:
            return TradeResult(success=False, action=action, size=0, price=mark_price,
                               error=f"Invalid action '{action}' for current position", mode="paper")

        # Update unrealized PnL for new position
        if self._paper_position and self._paper_position.size != 0:
            price_diff = mark_price - self._paper_position.entry_price
            self._paper_position.unrealized_pnl = (
                price_diff * self._paper_position.size
            )

        result = TradeResult(
            success=True, action=action, size=size,
            price=mark_price, fee=fee, pnl=pnl, mode="paper",
        )
        self._paper_trades.append(result.to_dict())
        logger.info("Paper trade: %s size=%.4f price=%.2f pnl=%.4f",
                     action, size, mark_price, pnl)
        return result

    async def _execute_live(self, action: str, size_pct: float, mark_price: float) -> TradeResult:
        """Execute a real trade via Hyperliquid SDK."""
        if not self._exchange:
            return TradeResult(success=False, action=action, size=0,
                               price=mark_price, error="Exchange not initialized", mode="live")

        portfolio = await self.get_portfolio()
        equity = portfolio["equity"]
        notional = equity * self.risk_per_trade * self.max_leverage * size_pct
        # Enforce Hyperliquid minimum order value (skip for close — no size needed)
        if action != "close" and notional < MIN_ORDER_VALUE_USD:
            if equity >= MIN_ORDER_VALUE_USD:
                notional = MIN_ORDER_VALUE_USD
            else:
                return TradeResult(success=False, action=action, size=0,
                                   price=mark_price,
                                   error=f"Equity ${equity:.2f} below minimum order ${MIN_ORDER_VALUE_USD:.0f}",
                                   mode="live")
        size = round(notional / mark_price, self._sz_decimals) if mark_price > 0 else 0

        # Capture PnL before executing close/flip/decrease
        pre_pnl = 0.0
        if action in ("close", "flip_long", "flip_short", "decrease_long", "decrease_short"):
            pre_pos = await self.get_position()
            if pre_pos:
                pre_pnl = pre_pos.unrealized_pnl

        try:
            if action in ("open_long", "flip_long"):
                # Close existing position first if flipping
                if action == "flip_long":
                    pos = await self.get_position()
                    if pos and pos.size < 0:
                        self._exchange.market_close(self.asset)
                result = self._exchange.market_open(self.asset, True, size)

            elif action in ("open_short", "flip_short"):
                if action == "flip_short":
                    pos = await self.get_position()
                    if pos and pos.size > 0:
                        self._exchange.market_close(self.asset)
                result = self._exchange.market_open(self.asset, False, size)

            elif action == "increase":
                pos = await self.get_position()
                is_buy = pos.size > 0 if pos else True
                result = self._exchange.market_open(self.asset, is_buy, size)

            elif action in ("decrease_long", "decrease_short"):
                pos = await self.get_position()
                if pos:
                    reduce_size = min(size, abs(pos.size) * 0.5)
                    reduce_size = round(reduce_size, self._sz_decimals)
                    is_buy = pos.size < 0  # buy to reduce short, sell to reduce long
                    result = self._exchange.market_open(self.asset, is_buy, reduce_size)
                else:
                    return TradeResult(success=False, action=action, size=0,
                                       price=mark_price, error="No position to reduce", mode="live")

            elif action == "close":
                result = self._exchange.market_close(self.asset)

            else:
                return TradeResult(success=False, action=action, size=0,
                                   price=mark_price, error=f"Unknown action: {action}", mode="live")

            # Parse SDK result
            if result is None:
                logger.error("Live trade returned None for %s", action)
                return TradeResult(success=False, action=action, size=size,
                                   price=mark_price, error="SDK returned None", mode="live")
            logger.info("Live trade raw result for %s: %s", action, str(result)[:300])
            if isinstance(result, dict):
                status = result.get("status", "")
                # Check for nested order errors (SDK returns status=ok even on order rejection)
                resp = result.get("response", {})
                if isinstance(resp, dict):
                    statuses = resp.get("data", {}).get("statuses", [])
                    for s in statuses:
                        if isinstance(s, dict) and s.get("error"):
                            logger.error("Live trade order rejected: %s", s["error"])
                            return TradeResult(success=False, action=action, size=size,
                                               price=mark_price, error=s["error"], mode="live")
            else:
                status = str(result)
            if status == "ok":
                fee = notional * TAKER_FEE_PCT
                logger.info("Live trade: %s size=%.4f price=%.2f pnl=%.4f", action, size, mark_price, pre_pnl)
                return TradeResult(success=True, action=action, size=size,
                                   price=mark_price, fee=fee, pnl=pre_pnl, mode="live")
            else:
                err = result.get("response", str(result)) if isinstance(result, dict) else str(result)
                logger.error("Live trade failed: %s", err)
                return TradeResult(success=False, action=action, size=size,
                                   price=mark_price, error=str(err), mode="live")

        except Exception as e:
            logger.error("Live trade exception: %s", e)
            return TradeResult(success=False, action=action, size=size,
                               price=mark_price, error=str(e), mode="live")

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders for the asset. Returns count of cancelled orders."""
        if self.mode != "live" or not self._info or not self._exchange:
            return 0
        try:
            resp = await self._http.post("/info", json={
                "type": "openOrders",
                "user": self._main_address,
            })
            resp.raise_for_status()
            open_orders = resp.json()
            # Filter to our asset
            asset_orders = [o for o in open_orders if o.get("coin") == self.asset]
            if not asset_orders:
                return 0
            logger.warning("Found %d open orders for %s — cancelling all",
                           len(asset_orders), self.asset)
            for order in asset_orders:
                oid = order.get("oid")
                if oid is not None:
                    try:
                        self._exchange.cancel(self.asset, oid)
                        logger.info("Cancelled order %s: side=%s sz=%s px=%s",
                                    oid, order.get("side"), order.get("sz"), order.get("limitPx"))
                    except Exception as e:
                        logger.error("Failed to cancel order %s: %s", oid, e)
            return len(asset_orders)
        except Exception as e:
            logger.error("Failed to fetch/cancel open orders: %s", e)
            return 0

    async def place_stop_order(self, trigger_price: float, size: float, is_buy: bool) -> dict:
        """Place a trigger stop order on Hyperliquid.

        For a long position SL: is_buy=False (sell to close), trigger when price drops below trigger_price.
        For a short position SL: is_buy=True (buy to close), trigger when price rises above trigger_price.
        """
        if not self._exchange:
            return {"error": "Exchange not initialized — need live mode connection at startup"}

        try:
            trigger_price = float(trigger_price)
            size = float(size)
            # Round size to asset's decimal precision
            size = round(size, self._sz_decimals)

            order_type = {"trigger": {"triggerPx": round(trigger_price, 2), "isMarket": True, "tpsl": "sl"}}
            # limit_px must be a float — for market trigger orders, use trigger price
            limit_px = round(trigger_price, 2)
            result = self._exchange.order(
                self.asset,
                is_buy,
                float(size),
                float(limit_px),
                order_type,
                reduce_only=True,
            )
            logger.info("Stop order placed: trigger=%s size=%s side=%s", trigger_price, size, "buy" if is_buy else "sell")
            return {"success": True, "triggerPrice": trigger_price, "size": size, "result": str(result)}
        except Exception as e:
            logger.error("Failed to place stop order: %s", e, exc_info=True)
            return {"error": str(e)}

    async def update_stop_order(self, new_trigger_price: float) -> dict:
        """Place new stop order FIRST, then cancel old ones. Never leaves position unprotected."""
        if not self._exchange:
            return {"error": "Exchange not initialized — need live mode connection at startup"}

        # Get current position to determine size and direction
        pos = await self.get_position()
        if not pos or pos.side == "FLAT":
            return {"error": "No open position"}

        size = abs(float(pos.size))
        is_buy = str(pos.side).lower() == "short"

        # Get existing stop order IDs BEFORE placing new one
        old_oids = []
        try:
            resp = await self._http.post("/info", json={
                "type": "frontendOpenOrders",
                "user": self._main_address,
            })
            resp.raise_for_status()
            for order in resp.json():
                if order.get("coin") == self.asset and order.get("orderType") == "Stop Market":
                    oid = order.get("oid")
                    if oid:
                        old_oids.append((oid, order.get("triggerPx")))
        except Exception as e:
            logger.warning("Failed to fetch old stops: %s", e)

        # PLACE NEW STOP FIRST — position is always protected
        result = await self.place_stop_order(new_trigger_price, size, is_buy)

        if not result.get("success"):
            logger.error("Failed to place new stop — keeping old stop in place")
            return result

        # New stop is confirmed — NOW cancel old ones
        for oid, old_trigger in old_oids:
            try:
                self._exchange.cancel(self.asset, oid)
                logger.info("Cancelled old stop %s (trigger=$%s)", oid, old_trigger)
            except Exception as e:
                logger.warning("Failed to cancel old stop %s: %s (may have two stops briefly)", oid, e)

        return result

    def set_mode(self, mode: str):
        """Switch between paper and live trading."""
        if mode not in ("paper", "live"):
            raise ValueError(f"Invalid mode: {mode}")
        old = self.mode
        self.mode = mode
        if mode == "paper" and old == "live":
            logger.info("Switched to PAPER mode")
        elif mode == "live" and old == "paper":
            logger.warning("Switched to LIVE mode — real orders will be placed")

    def reset_paper(self, starting_balance: float | None = None):
        """Reset paper trading state."""
        if starting_balance is not None:
            self._paper_starting_balance = starting_balance
        self._paper_balance = self._paper_starting_balance
        self._paper_position = None
        self._paper_trades.clear()

    def update_paper_pnl(self, mark_price: float):
        """Update unrealized PnL for paper position."""
        if self._paper_position and self._paper_position.size != 0:
            price_diff = mark_price - self._paper_position.entry_price
            self._paper_position.unrealized_pnl = price_diff * self._paper_position.size
