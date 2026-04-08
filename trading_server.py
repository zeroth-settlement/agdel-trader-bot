"""
AgDel Trading Server — CxU-driven autonomous trading agent.

Port: 9004
WebSocket: /ws (real-time state broadcast)
REST API: /api/* (dashboard controls)

Instead of a monolithic LLM engine with YAML strategy policy, this server
runs a 4-agent pipeline where every decision cites CxUs from the knowledge base.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

# Local modules (copied from trader-bot-basic)
from hl_trader import HLTrader
from risk_manager import RiskManager
from persistence import append_jsonl, load_jsonl
from bounce_trigger import BounceTrigger
from ratchet_tp import RatchetTP
from sentiment_bias import SentimentBias
from cluster_tracker import ClusterTracker
from agdel_buyer import AgdelBuyer
from exchange_feeds import ExchangeFeeds
from signal_feed import SignalFeed

# New CxU-driven modules
from cxu_store import CxUStore
from agents.regime_classifier import RegimeClassifier
from agents.signal_assessor import SignalAssessor
from agents.trade_decider import TradeDecider
from agents.reflector import Reflector
from agents.trainer import Trainer, TrainingInstruction
from alerts import AlertManager
from bounce_detector import BounceDetector
from db import TraderDB
from orderbook import OrderBookMonitor

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("trading_server")

# ─── Paths ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config" / "trading.yaml"
TRADE_HISTORY_PATH = BASE_DIR / "data" / "trade_history.jsonl"
TRADE_LOG_PATH = BASE_DIR / "logs" / "trade_log.jsonl"
REFLECTION_LOG_PATH = BASE_DIR / "logs" / "reflection.jsonl"

# Ensure directories exist
(BASE_DIR / "data").mkdir(exist_ok=True)
(BASE_DIR / "logs").mkdir(exist_ok=True)

# ─── Global state ────────────────────────────────────────────────
config: Dict[str, Any] = {}
hl_trader: Optional[HLTrader] = None
risk_manager: Optional[RiskManager] = None
bounce_trigger: Optional[BounceTrigger] = None
ratchet_tp: Optional[RatchetTP] = None
sentiment_bias: Optional[SentimentBias] = None
cluster_tracker: Optional[ClusterTracker] = None
exchange_feeds: Optional[ExchangeFeeds] = None

cxu_store: Optional[CxUStore] = None
regime_classifier: Optional[RegimeClassifier] = None
signal_assessor: Optional[SignalAssessor] = None
trade_decider: Optional[TradeDecider] = None
reflector: Optional[Reflector] = None
trainer: Optional[Trainer] = None
training_mode: bool = False
alert_manager: AlertManager = AlertManager()
bounce_detector: Optional[BounceDetector] = None
trader_db: Optional[TraderDB] = None
ob_monitor: OrderBookMonitor = OrderBookMonitor()
agdel_buyer: Optional[AgdelBuyer] = None
signal_feed: Optional[SignalFeed] = None

trade_history: List[Dict] = []
tick_history: deque = deque(maxlen=720)
ws_clients: List[WebSocket] = []
auto_trade: bool = False
last_decision_time: float = 0

# Agent outputs (for dashboard)
latest_regime: Dict[str, Any] = {}
latest_signal_assessment: Dict[str, Any] = {}
latest_decision: Dict[str, Any] = {}
latest_reflection: Dict[str, Any] = {}

# Cached position/portfolio (avoid double-fetching HL API per tick)
cached_position: Dict[str, Any] = {}
cached_portfolio: Dict[str, Any] = {}

# Signal feed state
direct_predictions: List[Dict] = []
purchased_signals: List[Dict] = []
available_signals: List[Dict] = []
agdel_stats: Dict[str, Any] = {"autoBuy": False, "purchasedCount": 0, "budget": {}}

# ─── Candle aggregation ────────────────────────────────────────
TIMEFRAMES = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
}
MAX_CANDLES = 500  # per timeframe


@dataclass
class Candle:
    timestamp: float  # open time (unix seconds, aligned to boundary)
    open: float
    high: float
    low: float
    close: float
    ticks: int = 0

    def update(self, price: float):
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.ticks += 1

    def to_dict(self) -> dict:
        return {"t": self.timestamp, "o": self.open, "h": self.high, "l": self.low, "c": self.close}


class CandleStore:
    """Maintains OHLC candles for a single timeframe."""

    def __init__(self, interval_secs: int):
        self.interval = interval_secs
        self.closed: deque[Candle] = deque(maxlen=MAX_CANDLES)
        self.current: Optional[Candle] = None

    def _boundary(self, ts: float) -> float:
        """Align timestamp to candle open boundary."""
        return math.floor(ts / self.interval) * self.interval

    def update(self, price: float, ts: float | None = None) -> Optional[Candle]:
        """Feed a price tick. Returns a newly closed candle if boundary crossed, else None."""
        ts = ts or time.time()
        boundary = self._boundary(ts)

        if self.current is None:
            self.current = Candle(timestamp=boundary, open=price, high=price, low=price, close=price, ticks=1)
            return None

        if boundary > self.current.timestamp:
            # Boundary crossed — close current, start new
            closed = self.current
            self.closed.append(closed)
            self.current = Candle(timestamp=boundary, open=price, high=price, low=price, close=price, ticks=1)
            return closed

        # Same candle — update OHLC
        self.current.update(price)
        return None

    def snapshot(self, limit: int = 200) -> List[dict]:
        """Return closed candles + current as dicts."""
        candles = list(self.closed)[-limit:]
        if self.current:
            candles.append(self.current)
        return [c.to_dict() for c in candles]


# One store per timeframe
candle_stores: Dict[str, CandleStore] = {tf: CandleStore(secs) for tf, secs in TIMEFRAMES.items()}
_last_ws_broadcast: float = 0


# ─── Config ──────────────────────────────────────────────────────
def load_config():
    global config, auto_trade
    try:
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
        auto_trade = config.get("autoTrade", {}).get("enabled", False)
        logger.info("Config loaded from %s", CONFIG_PATH)
    except Exception as e:
        logger.error("Failed to load config: %s", e)
        config = {}


# ─── Real-time price handler ─────────────────────────────────────
async def _on_price_tick(price: float):
    """Called on every WS price update from Hyperliquid (~12/sec)."""
    global _last_ws_broadcast

    ts = time.time()

    # Feed HL price to exchange feeds for basis computation
    if exchange_feeds:
        exchange_feeds.set_hl_price(price)

    # Update all candle stores
    closed_candles = {}
    for tf, store in candle_stores.items():
        closed = store.update(price, ts)
        if closed:
            closed_candles[tf] = closed.to_dict()
            # Persist to SQLite
            if trader_db:
                try:
                    cd = closed_candles[tf]
                    trader_db.save_candle(tf, {
                        "timestamp": cd.get("t", cd.get("timestamp", 0)),
                        "open": cd.get("o", cd.get("open", 0)),
                        "high": cd.get("h", cd.get("high", 0)),
                        "low": cd.get("l", cd.get("low", 0)),
                        "close": cd.get("c", cd.get("close", 0)),
                        "ticks": cd.get("ticks", 0),
                    })
                except Exception:
                    pass

    # Throttle WS broadcasts to dashboard (max ~4/sec to avoid flooding)
    if ts - _last_ws_broadcast < 0.25:
        return
    _last_ws_broadcast = ts

    # Build lightweight price message
    msg = {
        "type": "priceUpdate",
        "price": price,
        "timestamp": ts,
    }
    # Include any newly closed candles
    if closed_candles:
        msg["closedCandles"] = closed_candles
    # Include current candle for the active timeframe (dashboard picks its own)
    msg["currentCandles"] = {}
    for tf, store in candle_stores.items():
        if store.current:
            msg["currentCandles"][tf] = store.current.to_dict()

    # Include exchange prices + basis (lightweight — just current values)
    if exchange_feeds:
        ex_prices = {}
        for ex_id, ep in exchange_feeds.prices.items():
            if ep.mid > 0:
                ex_prices[ex_id] = {
                    "mid": round(ep.mid, 2),
                    "delta": round(ep.delta_vs_hl, 2),
                    "deltaPct": round(ep.delta_vs_hl_pct, 4),
                    "connected": ep.connected,
                }
        msg["exchanges"] = ex_prices
        basis = exchange_feeds._current_basis()
        msg["basis"] = basis

    for ws in ws_clients[:]:
        try:
            await ws.send_json(msg)
        except Exception:
            pass


# ─── Lifespan ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global hl_trader, risk_manager, bounce_trigger, ratchet_tp
    global sentiment_bias, cluster_tracker, exchange_feeds
    global cxu_store, regime_classifier, signal_assessor, trade_decider, reflector, trainer
    global trade_history, agdel_buyer, signal_feed, bounce_detector, trader_db, ob_monitor

    logger.info("=" * 50)
    logger.info("  AgDel Trader Bot — Starting")
    logger.info("=" * 50)

    # Load config
    load_config()

    # Initialize SQLite DB
    trader_db = TraderDB()
    trader_db.connect()
    db_stats = trader_db.get_stats()
    logger.info("  SQLite DB: candles=%s, trades=%d, signals=%d, alerts=%d",
                db_stats["candles"], db_stats["trades"], db_stats["signals"], db_stats["alerts"])

    # Load candle history from DB into candle stores
    for tf in candle_stores:
        saved = trader_db.get_candles(tf, limit=500)
        if saved:
            store = candle_stores[tf]
            for c in saved:
                store.closed.append(Candle(
                    timestamp=c["timestamp"], open=c["open"], high=c["high"],
                    low=c["low"], close=c["close"], ticks=c.get("ticks", 0),
                ))
            logger.info("  Restored %d %s candles from DB", len(saved), tf)

    # Load trade history
    trade_history = list(load_jsonl(TRADE_HISTORY_PATH, maxlen=200))
    logger.info("  Loaded %d historical trades", len(trade_history))

    # Initialize trading components
    trading_mode = os.environ.get("TRADING_MODE", "paper")  # Set TRADING_MODE=live to start in live mode
    paper_balance = config.get("trading", {}).get("paperStartingBalanceUsd", 5000)

    hl_trader = HLTrader(config, mode=trading_mode)
    logger.info("  HL Trader: %s mode ($%s paper balance)", trading_mode, paper_balance)

    risk_manager = RiskManager(config)

    bounce_trigger = BounceTrigger()
    ratchet_tp = RatchetTP()
    sentiment_bias = SentimentBias()
    cluster_tracker = ClusterTracker()
    exchange_feeds = ExchangeFeeds()

    # Initialize CxU store and agents
    cxu_store = CxUStore()
    regime_classifier = RegimeClassifier(config, cxu_store)
    signal_assessor = SignalAssessor(config, cxu_store)
    trade_decider = TradeDecider(config, cxu_store)
    reflector = Reflector(config, cxu_store)
    trainer = Trainer(config, cxu_store)
    bounce_detector = BounceDetector(cxu_store)

    # Default alert watches — bounce setup zones
    alert_manager.add_watch(
        name="BB Lower Extreme",
        description="Price near lower Bollinger Band — potential long bounce setup",
        conditions={"bb_below": 15},
        cooldown_seconds=600,
    )
    alert_manager.add_watch(
        name="BB Upper Extreme",
        description="Price near upper Bollinger Band — potential short bounce setup",
        conditions={"bb_above": 85},
        cooldown_seconds=600,
    )
    alert_manager.add_watch(
        name="Regime Shift to Volatile",
        description="Regime changed to volatile — increased risk, tighten stops",
        conditions={"regime_is": "volatile"},
        cooldown_seconds=1800,
    )
    logger.info("  Default alert watches: %d active", len(alert_manager.watches))

    # Initialize direct signal feed
    if config.get("signalFeed", {}).get("enabled", False):
        signal_feed = SignalFeed(config)
        logger.info("  Signal feed: %s", signal_feed.base_url)
    else:
        logger.info("  Signal feed disabled")

    # Initialize AGDEL buyer
    if config.get("agdel", {}).get("enabled", True):
        agdel_buyer = AgdelBuyer(config)
        try:
            await agdel_buyer.start()
            logger.info("  AGDEL buyer started (wallet: %s)", agdel_buyer.buyer_address[:10] + "..." if hasattr(agdel_buyer, 'buyer_address') and agdel_buyer.buyer_address else "?")
        except Exception as e:
            logger.warning("  AGDEL buyer start failed: %s", e)
    else:
        logger.info("  AGDEL buyer disabled")

    # Connect to Hyperliquid
    try:
        for attempt in range(3):
            try:
                await hl_trader.connect()
                logger.info("  Connected to Hyperliquid")
                break
            except Exception as e:
                if attempt < 2:
                    logger.warning("  HL connection attempt %d failed: %s (retrying in 3s)", attempt + 1, e)
                    await asyncio.sleep(3)
                else:
                    logger.error("  HL connection failed after 3 attempts: %s", e)
    except Exception as e:
        logger.warning("  HL connection failed: %s", e)

    # Start real-time price feed via WebSocket
    try:
        await hl_trader.start_price_feed(callback=_on_price_tick)
        logger.info("  Real-time price feed started (WS allMids)")
    except Exception as e:
        logger.warning("  Price feed start failed: %s", e)

    # Start multi-exchange price feeds
    try:
        await exchange_feeds.start()
        logger.info("  Multi-exchange feeds started (Binance, Coinbase, OKX)")
    except Exception as e:
        logger.warning("  Exchange feeds start failed: %s", e)

    # Start background loops
    tasks = []
    tasks.append(asyncio.create_task(tick_loop()))

    tasks.append(asyncio.create_task(macro_sentiment_loop()))

    if config.get("reflection", {}).get("enabled", True):
        tasks.append(asyncio.create_task(reflection_loop()))

    if signal_feed and signal_feed.enabled:
        tasks.append(asyncio.create_task(signal_feed_loop()))
        logger.info("  Signal feed loop started (interval=%ds)", signal_feed.poll_interval)

    if agdel_buyer and agdel_buyer.enabled:
        tasks.append(asyncio.create_task(agdel_poll_loop()))
        logger.info("  AGDEL poll loop started (interval=%ds)", agdel_buyer.poll_interval)
    else:
        logger.warning("  AGDEL poll loop NOT started (buyer=%s, enabled=%s)",
                       agdel_buyer is not None, agdel_buyer.enabled if agdel_buyer else "N/A")

    tasks.append(asyncio.create_task(orderbook_poll_loop()))
    logger.info("  Order book monitor started")

    logger.info("  Background loops started")
    logger.info("=" * 50)
    logger.info("  Dashboard: http://localhost:9002/")
    logger.info("  Trading API: http://localhost:9004/")
    logger.info("  WebSocket: ws://localhost:9004/ws")
    logger.info("=" * 50)

    yield

    # Shutdown
    for t in tasks:
        t.cancel()
    if agdel_buyer:
        try:
            await agdel_buyer.stop()
        except Exception:
            pass
    if trader_db:
        trader_db.close()
    logger.info("Trading server stopped")


# ─── App ─────────────────────────────────────────────────────────
app = FastAPI(title="AgDel Trading Server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Tick Loop ───────────────────────────────────────────────────
async def tick_loop():
    interval = config.get("trading", {}).get("loopIntervalMs", 5000) / 1000
    while True:
        try:
            await _run_tick()
        except Exception as e:
            logger.error("Tick error: %s", e, exc_info=True)
        await asyncio.sleep(interval)


async def _run_tick():
    global last_decision_time, latest_regime, latest_signal_assessment, latest_decision
    global cached_position, cached_portfolio

    if not hl_trader:
        return

    # 1. Fetch mark price
    mark_price = await hl_trader.get_mark_price()
    if not mark_price:
        return
    tick_history.append(mark_price)

    # 2. Fetch position
    position = await hl_trader.get_position()
    pos_dict = position.to_dict() if hasattr(position, "to_dict") else (position or {})
    cached_position = pos_dict
    if pos_dict.get("side") and pos_dict["side"] not in ("flat", "FLAT"):
        logger.info("Position: %s %.4f ETH @ $%.2f", pos_dict["side"], pos_dict.get("size", 0), pos_dict.get("entryPrice", 0))
    # Cache portfolio too (separate call only when needed)
    if hl_trader.mode == "live" and not cached_portfolio:
        try:
            cached_portfolio = await hl_trader.get_portfolio() or {}
        except Exception:
            pass

    # 3. Risk check
    if risk_manager and pos_dict.get("side") and pos_dict["side"] != "FLAT":
        risk_levels = risk_manager.get_sl_tp_levels()

        # In training mode, ONLY execute SL/TP if the user explicitly set dollar targets
        # (override fields). Never auto-close based on agent % defaults.
        has_user_sl = risk_manager._sl_price_override is not None
        has_user_tp = risk_manager._tp_price_override is not None
        allow_sl = has_user_sl or not training_mode
        allow_tp = has_user_tp or not training_mode

        # Stop loss check
        if allow_sl:
            sl_triggered, sl_reason = risk_manager.check_stop_loss(mark_price)
            if sl_triggered:
                logger.info("STOP LOSS triggered at $%.2f: %s", mark_price, sl_reason)
                result = await hl_trader.execute("close", 100, mark_price)
                if result and result.success:
                    _record_trade(result, f"SL: {sl_reason}", mark_price)
                    risk_manager.clear_position()
                return

        # Take profit check
        if allow_tp:
            tp_triggered, tp_reason = risk_manager.check_take_profit(mark_price)
            if tp_triggered:
                logger.info("TAKE PROFIT triggered at $%.2f: %s", mark_price, tp_reason)
                result = await hl_trader.execute("close", 100, mark_price)
                if result and result.success:
                    _record_trade(result, f"TP: {tp_reason}", mark_price)
                    risk_manager.clear_position()
                return

        # Update watermarks
        risk_manager.update_watermark(mark_price)

    # 3b. Ratchet TP check (works in training mode — user explicitly activates it)
    if ratchet_tp and ratchet_tp.active:
        triggered, reason = ratchet_tp.update(mark_price)
        if triggered:
            logger.info("RATCHET TP triggered at $%.2f: %s", mark_price, reason)
            result = await hl_trader.execute("close", 100, mark_price)
            if result and result.success:
                _record_trade(result, f"Ratchet TP: {reason}", mark_price)
                if risk_manager:
                    risk_manager.clear_position()
            return

    # 4. Bounce detection + alerts — EVERY TICK, not rate-limited
    # Bounce detector (1m candles)
    if bounce_detector and "1m" in candle_stores:
        candles_1m_raw = candle_stores["1m"].snapshot(limit=10)
        if len(candles_1m_raw) >= 5:
            # Translate short keys (o/h/l/c) to full keys (open/high/low/close) for bounce detector
            candles_1m = [{"open": c["o"], "high": c["h"], "low": c["l"], "close": c["c"], "timestamp": c["t"]} for c in candles_1m_raw]
            signal = bounce_detector.check(candles_1m)
            if signal:
                alert_msg = {
                    "type": "alert",
                    "name": "Bounce Entry Detected",
                    "description": (
                        f"Drop {signal.drop_pct:.2f}% from ${signal.peak_price:.2f} to ${signal.bottom_price:.2f}, "
                        f"momentum stalled. Entry: ${signal.entry_price:.2f}, "
                        f"SL: ${signal.stop_loss:.2f}, TP: ${signal.take_profit:.2f}, "
                        f"Size: {signal.size_pct}%"
                    ),
                    "price": mark_price,
                    "signal": signal.to_dict(),
                    "triggeredAt": time.time(),
                }
                for ws in ws_clients[:]:
                    try:
                        await ws.send_json(alert_msg)
                    except Exception:
                        pass
                await alert_manager._send_notification(
                    type("W", (), {"name": "Bounce Entry", "description": alert_msg["description"]})(),
                    mark_price, latest_regime.get("data", {}).get("regime", "unknown"),
                    latest_regime.get("data", {}).get("indicators", {}),
                )

    # Alert watches
    if alert_manager.watches:
        _regime = latest_regime.get("data", {}).get("regime", "unknown")
        _indicators = latest_regime.get("data", {}).get("indicators", {})
        triggered = await alert_manager.check_all(mark_price, _indicators, _regime, pos_dict)
        for alert in triggered:
            for ws in ws_clients[:]:
                try:
                    await ws.send_json({"type": "alert", **alert})
                except Exception:
                    pass

    # 5. Rate limit — only run agent pipeline at decision interval
    min_interval = config.get("agentPipeline", {}).get("minDecisionIntervalMs", 120000) / 1000
    now = time.time()
    if now - last_decision_time < min_interval:
        # Still broadcast state even without new decision
        await _broadcast_state(mark_price, pos_dict)
        return

    # 5. AGENT PIPELINE
    try:
        # Agent 1: Regime Classification
        prices = list(tick_history)
        regime_output = await regime_classifier.classify(mark_price, prices)
        latest_regime = regime_output.to_dict()
        regime = regime_output.data.get("regime", "unknown")

        # Agent 2: Signal Assessment
        signal_output = await signal_assessor.assess(
            predictions=direct_predictions,
            purchased_signals=purchased_signals,
            regime=regime,
            mark_price=mark_price,
        )
        latest_signal_assessment = signal_output.to_dict()

        # Agent 3: Trade Decision
        port_dict = await hl_trader.get_portfolio() or {}
        risk_levels = risk_manager.get_sl_tp_levels() if risk_manager else {}

        decision_output = await trade_decider.decide(
            regime_output=regime_output,
            signal_output=signal_output,
            position=pos_dict,
            portfolio=port_dict,
            risk_levels=risk_levels,
            recent_trades=trade_history[-15:],
            mark_price=mark_price,
        )
        latest_decision = decision_output.to_dict()
        last_decision_time = now

        # Execute if auto-trade enabled and action is not hold
        # NEVER execute when training mode is on — the human controls the position
        action = decision_output.data.get("action", "hold")
        if auto_trade and not training_mode and action != "hold" and decision_output.success:
            # Sentiment gate
            blocked = False
            if sentiment_bias and config.get("sentimentBias", {}).get("enabled"):
                try:
                    bias_result = await sentiment_bias.check(action)
                    if bias_result and bias_result.get("blocked"):
                        blocked = True
                        logger.info("Sentiment gate blocked %s", action)
                except Exception:
                    pass  # Don't block trades on sentiment failure

            if not blocked:
                size_pct = decision_output.data.get("sizePct", 100)
                result = await hl_trader.execute(action, size_pct, mark_price)
                if result and result.success:
                    _record_trade(
                        result,
                        decision_output.data.get("reasoning", action),
                        mark_price,
                        regime=regime,
                        citations=decision_output.citations,
                    )
                    # Update risk manager
                    if risk_manager:
                        new_pos = await hl_trader.get_position()
                        new_pos_dict = new_pos.to_dict() if hasattr(new_pos, "to_dict") else {}
                        if new_pos_dict.get("side") and new_pos_dict["side"] != "FLAT":
                            risk_manager.reset_watermark(new_pos_dict.get("entryPrice", mark_price), new_pos_dict["side"])

    except Exception as e:
        logger.error("Agent pipeline error: %s", e, exc_info=True)
        latest_decision = {
            "agentId": "trade-decider",
            "success": False,
            "error": str(e),
            "data": {"action": "hold", "reasoning": f"Pipeline error: {e}"},
            "citations": [],
        }

    # 8. Broadcast state
    await _broadcast_state(mark_price, pos_dict)


def _record_trade(result, rationale: str, mark_price: float, regime: str = "", citations: list = None):
    """Record a trade to history and log."""
    trade = result.to_dict() if hasattr(result, "to_dict") else {"action": "unknown"}
    trade["rationale"] = rationale
    trade["regime"] = regime
    trade["citations"] = citations or []
    trade["timestamp"] = datetime.now(timezone.utc).isoformat()

    trade_history.append(trade)
    if len(trade_history) > 200:
        trade_history.pop(0)

    append_jsonl(TRADE_HISTORY_PATH, trade)
    append_jsonl(TRADE_LOG_PATH, {**trade, "markPrice": mark_price})
    if trader_db:
        try:
            trader_db.save_trade({**trade, "price": mark_price, "mode": hl_trader.mode if hl_trader else "paper"})
        except Exception:
            pass
    logger.info("TRADE: %s | %s | regime=%s | citations=%d",
                trade.get("action"), rationale[:60], regime, len(citations or []))


# ─── Macro Sentiment Loop ───────────────────────────────────────
async def macro_sentiment_loop():
    """Fetch macro sentiment every 5 minutes, LLM analysis every 15 minutes."""
    tick_count = 0
    while True:
        try:
            if sentiment_bias:
                # Quantitative update every tick (5 min)
                bias = await sentiment_bias.compute()
                stats = sentiment_bias.get_stats()
                macro = stats.get("macro") or {}

                # Adjust risk manager holding tolerance based on macro alignment
                if risk_manager and risk_manager._has_position:
                    _adjust_holding_tolerance(bias, macro.get("macro_bias", "NEUTRAL"))

                logger.info("Macro sentiment: crypto=%s macro=%s F&G=%s",
                            bias,
                            macro.get("macro_bias", "?"),
                            macro.get("fear_greed", {}).get("value", "?"))

                # LLM analysis every 3rd tick (15 min) — includes news + narrative
                if tick_count % 3 == 0:
                    try:
                        llm_result = await sentiment_bias.analyze_with_llm()
                        if llm_result:
                            # Use LLM score to refine holding tolerance
                            llm_bias = llm_result.get("bias", "NEUTRAL")
                            if risk_manager and risk_manager._has_position:
                                _adjust_holding_tolerance(bias, llm_bias)
                            logger.info("LLM macro: score=%s bias=%s — %s",
                                        llm_result.get("score"), llm_bias,
                                        (llm_result.get("narrative") or "")[:100])
                    except Exception as e:
                        logger.warning("LLM macro analysis error: %s", e)

                tick_count += 1
        except Exception as e:
            logger.warning("Macro sentiment error: %s", e)
        await asyncio.sleep(300)  # 5 minutes


def _adjust_holding_tolerance(crypto_bias: str, macro_bias: str):
    """Widen TP / tighten SL when macro opposes our position, and vice versa."""
    if not risk_manager or not risk_manager._has_position:
        return

    side = risk_manager._side
    base_sl = config.get("autoTrade", {}).get("stopLoss", {}).get("trailingPct", 0.03)
    base_tp = config.get("autoTrade", {}).get("takeProfit", {}).get("fixedPct", 0.08)

    # Determine if macro aligns with our position direction
    aligned = False
    opposed = False
    if side == "long":
        aligned = crypto_bias == "BULLISH" or macro_bias == "BULLISH"
        opposed = crypto_bias == "BEARISH" and macro_bias != "BULLISH"
    elif side == "short":
        aligned = crypto_bias == "BEARISH" or macro_bias == "BEARISH"
        opposed = crypto_bias == "BULLISH" and macro_bias != "BEARISH"

    if aligned:
        # Macro supports our trade → wider TP (let it run), standard SL
        risk_manager.tp_fixed_pct = base_tp * 1.25
        risk_manager.sl_trailing_pct = base_sl
        logger.info("Macro ALIGNED with %s → TP widened to %.1f%%", side, risk_manager.tp_fixed_pct * 100)
    elif opposed:
        # Macro opposes our trade → tighter SL, standard TP (take profit faster)
        risk_manager.sl_trailing_pct = base_sl * 0.75
        risk_manager.tp_fixed_pct = base_tp * 0.8
        logger.info("Macro OPPOSED to %s → SL tightened to %.1f%%", side, risk_manager.sl_trailing_pct * 100)
    else:
        # Neutral — use base config
        risk_manager.sl_trailing_pct = base_sl
        risk_manager.tp_fixed_pct = base_tp


# ─── Reflection Loop ────────────────────────────────────────────
async def reflection_loop():
    global latest_reflection
    interval = config.get("reflection", {}).get("intervalSeconds", 1800)
    last_trade_idx = 0

    while True:
        await asyncio.sleep(interval)
        try:
            # Get trades since last reflection
            new_trades = trade_history[last_trade_idx:]
            last_trade_idx = len(trade_history)

            output = await reflector.reflect(
                recent_trades=new_trades,
                settled_predictions=[],  # TODO: wire settled predictions
            )
            latest_reflection = output.to_dict()

            if output.success:
                append_jsonl(REFLECTION_LOG_PATH, output.to_dict())
                # Reload CxU store if changes were made
                if output.data.get("cxusCreated", 0) > 0 or output.data.get("cxusUpdated", 0) > 0:
                    cxu_store.reload()
                    logger.info("CxU store reloaded after reflection cycle %d", output.data.get("cycle", 0))

                # Broadcast reflection event
                for ws in ws_clients[:]:
                    try:
                        await ws.send_json({"type": "reflection", **output.to_dict()})
                    except Exception:
                        pass

        except Exception as e:
            logger.error("Reflection error: %s", e, exc_info=True)


# ─── Order Book Poll Loop ───────────────────────────────────────
async def orderbook_poll_loop():
    """Poll L2 order book every 5 seconds."""
    await asyncio.sleep(3)  # Startup delay
    while True:
        try:
            await ob_monitor.poll()
        except Exception as e:
            logger.error("Order book poll error: %s", e)
        await asyncio.sleep(5)


# ─── Signal Feed Loop ───────────────────────────────────────────
async def signal_feed_loop():
    """Poll the direct signal bot for predictions."""
    global direct_predictions

    if not signal_feed or not signal_feed.enabled:
        return
    interval = signal_feed.poll_interval
    logger.info("Signal feed loop: starting (url=%s, interval=%ds)", signal_feed.base_url, interval)

    while True:
        try:
            got_data = await signal_feed.poll_once()
            if got_data:
                direct_predictions = signal_feed.get_active_predictions_for_context()
                logger.info("Signal feed: %d active predictions", len(direct_predictions))
        except Exception as e:
            logger.error("Signal feed poll error: %s", e, exc_info=True)
        await asyncio.sleep(interval)


# ─── AGDEL Poll Loop ────────────────────────────────────────────
async def agdel_poll_loop():
    """Poll AGDEL marketplace for signals, auto-buy candidates, check deliveries."""
    global purchased_signals, available_signals, agdel_stats

    if not agdel_buyer or not agdel_buyer.enabled:
        logger.warning("AGDEL poll loop: buyer not available, exiting")
        return
    interval = agdel_buyer.poll_interval
    logger.info("AGDEL poll loop: starting (interval=%ds, autoBuy=%s)", interval, agdel_buyer.auto_buy)
    await asyncio.sleep(5)  # Startup delay
    poll_count = 0

    while True:
        try:
            logger.info("AGDEL poll: starting poll_once...")
            purchased = await agdel_buyer.poll_once()
            logger.info("AGDEL poll: poll_once returned %d purchased", len(purchased) if purchased else 0)

            await agdel_buyer.check_stale_deliveries()

            # Check outcomes less frequently (~every 60s)
            poll_count += 1
            if poll_count % max(1, 60 // interval) == 0:
                await agdel_buyer.check_outcomes()

            # Update state for dashboard and signal assessor
            purchased_signals = list(agdel_buyer.purchase_log)
            available_signals = agdel_buyer.get_available_enriched()
            agdel_stats = agdel_buyer.get_stats()
            logger.info("AGDEL poll: %d available, %d purchased, stats=%s",
                        len(available_signals), len(purchased_signals),
                        {k: v for k, v in agdel_stats.items() if k in ('polls', 'autoBuy', 'totalPurchased')})

        except Exception as e:
            logger.error("AGDEL poll error: %s", e, exc_info=True)
        await asyncio.sleep(interval)


# ─── WebSocket ───────────────────────────────────────────────────
async def _broadcast_state(mark_price: float, position: dict):
    """Build and broadcast state to all WebSocket clients."""
    # Use cached data from tick loop — no additional HL API calls
    portfolio = cached_portfolio or {}
    hl_position = position or cached_position or {}
    hl_portfolio = cached_portfolio or {}

    if hl_trader and hl_trader.mode == "paper" and not portfolio:
        try:
            portfolio = await hl_trader.get_portfolio() or {}
            hl_portfolio = portfolio
        except Exception:
            pass

    # Build state dict (compatible with dashboard expectations)
    state = {
        "timestamp": time.time(),
        "tradingMode": hl_trader.mode if hl_trader else "paper",
        "autoTrade": auto_trade,
        "asset": "ETH",
        "markPrice": mark_price,

        # Position
        "position": position,
        "hlPosition": hl_position,
        "hlPortfolio": hl_portfolio,
        "portfolio": portfolio,

        # Regime (new)
        "regime": latest_regime.get("data", {}),
        "strategy": {
            "activePlaybook": _get_active_playbook(),
        },

        # Decision (new format with citations)
        "lastDecision": latest_decision.get("data", {}),
        "lastLlmDecision": {
            "action": latest_decision.get("data", {}).get("action", "hold"),
            "confidence": latest_decision.get("data", {}).get("confidence", 0),
            "reasoning": latest_decision.get("data", {}).get("reasoning", ""),
            "citations": latest_decision.get("citations", []),
            "timestamp": latest_decision.get("data", {}).get("timestamp"),
        },

        # Risk
        "riskLevels": risk_manager.get_sl_tp_levels() if risk_manager else {},
        "ratchetTp": ratchet_tp.get_status() if ratchet_tp else {},

        # Signals
        "predictions": direct_predictions[:50],
        "purchases": purchased_signals[:50],
        "availableSignals": available_signals[:50],

        # AGDEL
        "agdel": agdel_stats,

        # Training mode
        "trainingMode": training_mode,

        # Order book
        "orderbook": ob_monitor.latest.to_dict() if ob_monitor and ob_monitor.latest else None,

        # Performance (computed from trade history)
        "performance": _compute_performance(),

        # Macro sentiment
        "macroSentiment": sentiment_bias.get_stats() if sentiment_bias else {},

        # Multi-exchange prices
        "exchangePrices": exchange_feeds.get_snapshot() if exchange_feeds else {},

        # Agent outputs (for Agent Output tab)
        "agentOutputs": {
            "regime-classifier": latest_regime,
            "signal-assessor": latest_signal_assessment,
            "trade-decider": latest_decision,
            "reflector": latest_reflection,
        },
    }

    # Broadcast to all clients
    if ws_clients:
        for ws in ws_clients[:]:
            try:
                await ws.send_json(state)
            except Exception as e:
                logger.warning("WS send failed: %s", e)
                ws_clients.remove(ws)


def _get_active_playbook() -> str:
    regime = latest_regime.get("data", {}).get("regime", "unknown")
    playbook = cxu_store.get_playbook_for_regime(regime) if cxu_store else None
    return playbook.alias if playbook else "none"


def _compute_performance() -> Dict[str, Any]:
    if not trade_history:
        return {"winRate": 0, "totalTrades": 0, "totalFees": 0, "tradesToday": 0,
                "netPnl": 0, "grossPnl": 0, "netPnl24h": 0, "grossPnl24h": 0,
                "totalFees24h": 0, "winRate24h": 0, "tradeCount24h": 0}

    today = datetime.now(timezone.utc).date()
    cutoff_24h = time.time() - 86400

    # All-time stats
    wins = sum(1 for t in trade_history if (t.get("pnl") or 0) > 0)
    total_pnl = sum(t.get("pnl", 0) for t in trade_history)
    total_fees = sum(t.get("fee", 0) for t in trade_history)

    # 24h stats
    trades_24h = []
    trades_today = 0
    for t in trade_history:
        try:
            ts = t.get("timestamp", "")
            if isinstance(ts, str) and ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.date() == today:
                    trades_today += 1
                if dt.timestamp() >= cutoff_24h:
                    trades_24h.append(t)
        except Exception:
            pass

    wins_24h = sum(1 for t in trades_24h if (t.get("pnl") or 0) > 0)
    pnl_24h = sum(t.get("pnl", 0) for t in trades_24h)
    fees_24h = sum(t.get("fee", 0) for t in trades_24h)

    return {
        "winRate": wins / len(trade_history) if trade_history else 0,
        "totalTrades": len(trade_history),
        "totalFees": round(total_fees, 2),
        "grossPnl": round(total_pnl, 2),
        "netPnl": round(total_pnl - total_fees, 2),
        "tradesToday": trades_today,
        # 24h window
        "winRate24h": wins_24h / len(trades_24h) if trades_24h else 0,
        "tradeCount24h": len(trades_24h),
        "grossPnl24h": round(pnl_24h, 2),
        "totalFees24h": round(fees_24h, 2),
        "netPnl24h": round(pnl_24h - fees_24h, 2),
    }


# ─── REST API ────────────────────────────────────────────────────
@app.get("/")
async def serve_dashboard():
    """Serve dashboard directly from trading server."""
    dashboard = BASE_DIR / "dashboard.html"
    if dashboard.exists():
        return FileResponse(str(dashboard), media_type="text/html")
    return RedirectResponse("http://localhost:9002/")


# Serve shared assets so dashboard works from :9004 too
from fastapi.staticfiles import StaticFiles
_shared = BASE_DIR / "shared"
_pyrana = BASE_DIR / "pyrana_objects"
_data = BASE_DIR / "data"
if (_shared / "components").exists():
    app.mount("/components", StaticFiles(directory=str(_shared / "components")), name="components")
if (_shared / "design-guide").exists():
    app.mount("/design-guide", StaticFiles(directory=str(_shared / "design-guide")), name="design-guide")
if _pyrana.exists():
    app.mount("/pyrana-objects", StaticFiles(directory=str(_pyrana)), name="pyrana-objects")
if _data.exists():
    app.mount("/data", StaticFiles(directory=str(_data)), name="data")


# ─── Local Pyrana Object API (for PyranaLibrary component) ───────
# These endpoints mirror what Pyrana services provide, but read from local files.
# PyranaLibrary uses empty-string API bases → relative paths to these endpoints.

def _load_json_objects(subdir: str) -> list:
    """Load all JSON files from a pyrana_objects subdirectory."""
    d = BASE_DIR / "pyrana_objects" / subdir
    if not d.exists():
        return []
    items = []
    for f in sorted(d.glob("*.json")):
        try:
            with open(f) as fp:
                items.append(json.load(fp))
        except Exception:
            pass
    return items


def _find_json_object(subdir: str, obj_id: str, id_field: str):
    """Find a single object by its ID field."""
    for item in _load_json_objects(subdir):
        if item.get(id_field) == obj_id or item.get("alias") == obj_id:
            return item
    return None


@app.get("/cxus")
async def list_cxus_local():
    return _load_json_objects("cxus")


@app.get("/cxus/{cxu_id}")
async def get_cxu_local(cxu_id: str):
    cxu = _find_json_object("cxus", cxu_id, "cxu_id")
    if not cxu:
        return JSONResponse({"error": f"CxU {cxu_id} not found"}, status_code=404)
    return cxu


# Library component expects /api/prompts, /api/scripts, /api/agents
@app.get("/api/prompts")
async def list_prompts_local():
    return _load_json_objects("prompts")


@app.get("/api/prompts/{prompt_id}")
async def get_prompt_local(prompt_id: str):
    p = _find_json_object("prompts", prompt_id, "prompt_id")
    if not p:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return p


@app.get("/api/scripts")
async def list_scripts_local():
    return _load_json_objects("scripts")


@app.get("/api/scripts/{script_id}")
async def get_script_local(script_id: str):
    s = _find_json_object("scripts", script_id, "script_id")
    if not s:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return s


@app.get("/api/agents")
async def list_agents_local():
    return _load_json_objects("agents")


@app.get("/api/skills")
async def list_skills_local():
    return _load_json_objects("skills")


@app.get("/api/skills/{skill_id}")
async def get_skill_local(skill_id: str):
    s = _find_json_object("skills", skill_id, "skill_id")
    if not s:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return s


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "agdel-trader-bot",
        "mode": hl_trader.mode if hl_trader else "unknown",
        "activeCxus": len(cxu_store.all()) if cxu_store else 0,
        "regime": latest_regime.get("data", {}).get("regime", "unknown"),
        "wsClients": len(ws_clients),
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    logger.info("WebSocket client connected (%d total)", len(ws_clients))
    try:
        while True:
            await ws.receive_text()  # Keep alive
    except WebSocketDisconnect:
        ws_clients.remove(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(ws_clients))


@app.get("/api/state")
async def get_state():
    mark_price = await hl_trader.get_mark_price() if hl_trader else 0
    return {
        "markPrice": mark_price,
        "regime": latest_regime.get("data", {}),
        "decision": latest_decision.get("data", {}),
        "autoTrade": auto_trade,
        "mode": hl_trader.mode if hl_trader else "paper",
    }


@app.get("/api/trades")
async def get_trades():
    return {"trades": trade_history}


@app.post("/api/autotrade/toggle")
async def toggle_autotrade():
    global auto_trade
    auto_trade = not auto_trade
    logger.info("Auto trade: %s", "ON" if auto_trade else "OFF")
    return {"autoTrade": auto_trade}


@app.post("/api/risk/ratchet")
async def activate_ratchet(body: dict):
    """Activate ratcheting take-profit on current position.

    Body:
        wide: true for multi-hour runs (wider buffer, default true)
    """
    if not ratchet_tp or not hl_trader:
        return JSONResponse({"error": "Not initialized"}, status_code=400)

    position = await hl_trader.get_position()
    if not position or position.side == "flat":
        return JSONResponse({"error": "No open position"}, status_code=400)

    wide = body.get("wide", True)
    fee_estimate = abs(position.size) * position.entry_price * 0.000432  # one-side fee

    ratchet_tp.activate(
        side=position.side,
        entry_price=position.entry_price,
        fee_estimate=fee_estimate,
        wide=wide,
    )

    status = ratchet_tp.get_status()
    return {
        "success": True,
        "ratchet": status,
        "message": f"Ratchet TP active: {status['phase']} phase, TP=${status['tp_price']:.2f}, {'wide' if wide else 'tight'} mode",
    }


@app.get("/api/risk/ratchet")
async def get_ratchet_status():
    if not ratchet_tp:
        return {"active": False}
    return ratchet_tp.get_status()


@app.post("/api/risk/set")
async def set_risk_targets(body: dict):
    """Set SL/TP by dollar P&L targets.

    Body:
        tpDollars: take profit target in dollars (e.g., 300 = close at +$300)
        slDollars: stop loss target in dollars (e.g., 500 = close at -$500)
    """
    if not risk_manager or not hl_trader:
        return JSONResponse({"error": "Not initialized"}, status_code=400)

    position = await hl_trader.get_position()
    if not position or position.side == "flat":
        return JSONResponse({"error": "No open position"}, status_code=400)

    pos_size = abs(position.size)
    tp = body.get("tpDollars")
    sl = body.get("slDollars")

    if tp is not None:
        tp = abs(float(tp))
    if sl is not None:
        sl = abs(float(sl))

    risk_manager.set_dollar_targets(pos_size, tp_dollars=tp, sl_dollars=sl)

    levels = risk_manager.get_sl_tp_levels()

    # Broadcast updated state immediately
    mark_price = await hl_trader.get_mark_price()
    pos_dict = position.to_dict()
    await _broadcast_state(mark_price, pos_dict)

    return {
        "success": True,
        "position": {"side": position.side, "size": pos_size, "entryPrice": position.entry_price},
        "slPrice": levels.get("slPrice"),
        "tpPrice": levels.get("tpPrice"),
        "message": f"SL=${levels.get('slPrice', 0):.2f} TP=${levels.get('tpPrice', 0):.2f}",
    }


@app.post("/api/risk/sl")
async def set_stop_loss(body: dict):
    """Set stop loss. Body: {"price": 2100.00} or {"pct": 3.0}"""
    if not risk_manager:
        return JSONResponse({"error": "Risk manager not initialized"}, status_code=400)
    sl_price = body.get("price")
    sl_pct = body.get("pct")
    if sl_price:
        risk_manager.sl_fixed_price = float(sl_price)
        risk_manager.sl_mode = "fixed"
        return {"stopLoss": sl_price, "mode": "fixed"}
    elif sl_pct:
        risk_manager.sl_trailing_pct = float(sl_pct) / 100
        risk_manager.sl_mode = "trailing"
        return {"stopLoss": f"{sl_pct}%", "mode": "trailing"}
    return JSONResponse({"error": "Provide 'price' or 'pct'"}, status_code=400)


@app.post("/api/risk/tp")
async def set_take_profit(body: dict):
    """Set take profit. Body: {"price": 2200.00} or {"pct": 5.0}"""
    if not risk_manager:
        return JSONResponse({"error": "Risk manager not initialized"}, status_code=400)
    tp_price = body.get("price")
    tp_pct = body.get("pct")
    if tp_price:
        risk_manager.tp_fixed_price = float(tp_price)
        return {"takeProfit": tp_price}
    elif tp_pct:
        risk_manager.tp_fixed_pct = float(tp_pct) / 100
        return {"takeProfit": f"{tp_pct}%"}
    return JSONResponse({"error": "Provide 'price' or 'pct'"}, status_code=400)


@app.post("/api/risk/sync")
async def sync_risk_from_position():
    """Sync the risk manager with the current HL position.
    Use this when you opened a position outside the bot.
    """
    if not risk_manager or not hl_trader:
        return JSONResponse({"error": "Not initialized"}, status_code=400)

    pos = await hl_trader.get_position()
    if not pos or pos.side == "FLAT":
        return JSONResponse({"error": "No open position to sync"}, status_code=400)

    mark_price = await hl_trader.get_mark_price()
    entry = pos.entry_price or mark_price

    # Use recover_from_position if available, otherwise reset_watermark
    if hasattr(risk_manager, 'recover_from_position'):
        risk_manager.recover_from_position(entry, pos.side, mark_price)
    else:
        risk_manager.reset_watermark(entry, pos.side)
        risk_manager.update_watermark(mark_price)

    levels = risk_manager.get_sl_tp_levels()
    logger.info("Risk synced: entry=$%.2f side=%s watermark=$%.2f levels=%s",
                entry, pos.side, mark_price, levels)
    return {
        "synced": True,
        "entry": entry,
        "side": pos.side,
        "markPrice": mark_price,
        "levels": levels,
    }


@app.get("/api/orderbook")
async def get_orderbook():
    """Get latest order book analysis."""
    if ob_monitor and ob_monitor.latest:
        return ob_monitor.latest.to_dict()
    return {"error": "No order book data yet"}


@app.get("/api/db/stats")
async def get_db_stats():
    if not trader_db:
        return {}
    return trader_db.get_stats()


@app.get("/api/risk/levels")
async def get_risk_levels():
    """Get current SL/TP levels."""
    if not risk_manager:
        return {}
    return risk_manager.get_sl_tp_levels()


@app.get("/api/position")
async def get_position_detail():
    """Detailed position tracker with breakeven, fees, and signal context."""
    if not hl_trader:
        return JSONResponse({"error": "Not initialized"}, status_code=400)

    pos = await hl_trader.get_position()
    if not pos or pos.side == "FLAT":
        return {"position": None, "status": "flat"}

    mark_price = await hl_trader.get_mark_price()
    portfolio = await hl_trader.get_portfolio() or {}

    entry = pos.entry_price or 0
    size = abs(pos.size) if hasattr(pos, 'size') else 0
    notional = size * entry
    side = pos.side.lower()

    # Fee calculation from hyperliquid-fees CxU
    fee_cxu = cxu_store.by_alias("hyperliquid-fees") if cxu_store else None
    taker_fee_pct = 0.045  # default Tier 0
    if fee_cxu:
        taker_fee_pct = fee_cxu.param_value("takerFeePct", 0.045)

    # Round-trip fees (entry taker + exit taker)
    rt_fee_pct = taker_fee_pct * 2 / 100  # convert from basis points style
    rt_fee_usd = notional * rt_fee_pct
    fee_per_side_usd = notional * (taker_fee_pct / 100)

    # Breakeven: entry adjusted by round-trip fee
    if side == "long":
        breakeven = entry * (1 + rt_fee_pct)
        distance_to_breakeven = mark_price - breakeven
        distance_pct = (mark_price - breakeven) / breakeven * 100
    else:  # short
        breakeven = entry * (1 - rt_fee_pct)
        distance_to_breakeven = breakeven - mark_price
        distance_pct = (breakeven - mark_price) / breakeven * 100

    # P&L
    if side == "long":
        gross_pnl = (mark_price - entry) * size
    else:
        gross_pnl = (entry - mark_price) * size
    net_pnl = gross_pnl - fee_per_side_usd  # already paid entry fee

    # Leverage and liquidation
    leverage = pos.leverage if hasattr(pos, 'leverage') else 1
    margin = notional / leverage if leverage else notional
    if side == "long":
        liq_price = entry * (1 - 1 / leverage) if leverage > 1 else 0
    else:
        liq_price = entry * (1 + 1 / leverage) if leverage > 1 else float('inf')
    distance_to_liq = abs(mark_price - liq_price)
    distance_to_liq_pct = distance_to_liq / mark_price * 100

    # Signal context
    regime = latest_regime.get("data", {}).get("regime", "unknown")
    consensus = latest_signal_assessment.get("data", {}).get("consensus", {})
    decision = latest_decision.get("data", {})

    # Risk levels
    risk = risk_manager.get_sl_tp_levels() if risk_manager else {}

    return {
        "position": {
            "side": side,
            "size": size,
            "entryPrice": entry,
            "markPrice": mark_price,
            "notional": round(notional, 2),
            "leverage": leverage,
            "margin": round(margin, 2),
        },
        "pnl": {
            "grossPnl": round(gross_pnl, 2),
            "entryFee": round(fee_per_side_usd, 2),
            "exitFeeEstimate": round(fee_per_side_usd, 2),
            "roundTripFee": round(rt_fee_usd, 2),
            "netPnl": round(net_pnl, 2),
            "unrealizedPnl": round(pos.unrealized_pnl if hasattr(pos, 'unrealized_pnl') else gross_pnl, 2),
        },
        "breakeven": {
            "price": round(breakeven, 2),
            "distanceUsd": round(distance_to_breakeven, 2),
            "distancePct": round(distance_pct, 3),
            "profitable": distance_to_breakeven > 0,
        },
        "liquidation": {
            "price": round(liq_price, 2),
            "distanceUsd": round(distance_to_liq, 2),
            "distancePct": round(distance_to_liq_pct, 2),
        },
        "risk": risk,
        "signals": {
            "regime": regime,
            "consensus": consensus.get("direction", "NEUTRAL"),
            "consensusPct": consensus.get("agreementPct", 0),
            "agentRecommendation": decision.get("action", "hold"),
            "agentConfidence": decision.get("confidence", 0),
        },
        "fees": {
            "takerFeePct": taker_fee_pct,
            "feePerSideUsd": round(fee_per_side_usd, 2),
            "roundTripPct": round(rt_fee_pct * 100, 4),
        },
    }


@app.post("/api/close")
async def close_position():
    if not hl_trader:
        return JSONResponse({"error": "No trader"}, status_code=400)
    mark_price = await hl_trader.get_mark_price()
    result = await hl_trader.execute("close", 100, mark_price)
    if result and result.success:
        _record_trade(result, "Manual close", mark_price)
        if risk_manager:
            risk_manager.clear_position()
        return {"success": True}
    return JSONResponse({"error": "Close failed"}, status_code=500)


@app.post("/api/config/reload")
async def reload_config():
    load_config()
    return {"status": "reloaded"}


@app.get("/api/config")
async def get_config():
    return config


@app.post("/api/config/mode")
async def set_mode(body: dict):
    if not hl_trader:
        return JSONResponse({"error": "No trader"}, status_code=400)
    mode = body.get("mode", "paper")
    if mode not in ("paper", "live"):
        return JSONResponse({"error": "Invalid mode"}, status_code=400)

    # Initialize live SDK if switching to live for the first time
    if mode == "live" and not hl_trader._exchange:
        try:
            old_mode = hl_trader.mode
            hl_trader.mode = "live"
            await hl_trader.connect()
            logger.info("Live SDK initialized on mode switch")
        except Exception as e:
            hl_trader.mode = old_mode if 'old_mode' in dir() else "paper"
            logger.error("Failed to init live SDK: %s", e)
            return JSONResponse({"error": f"Live SDK init failed: {e}"}, status_code=500)
    else:
        hl_trader.mode = mode

    logger.info("Mode switched to %s", mode)
    return {"mode": mode}


@app.post("/api/reflection/trigger")
async def trigger_reflection():
    global latest_reflection
    try:
        output = await reflector.reflect(
            recent_trades=trade_history[-20:],
            settled_predictions=[],
        )
        latest_reflection = output.to_dict()
        if output.success and (output.data.get("cxusCreated", 0) > 0 or output.data.get("cxusUpdated", 0) > 0):
            cxu_store.reload()
        return output.to_dict()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/reflection/history")
async def get_reflection_history():
    history = load_jsonl(REFLECTION_LOG_PATH, maxlen=50)
    return {"history": history}


@app.get("/api/cxus")
async def get_cxus():
    if not cxu_store:
        return {"cxus": []}
    return {
        "cxus": [c.to_dict() for c in cxu_store.all()],
        "counts": {
            "axioms": len(cxu_store.axioms),
            "regime_models": len(cxu_store.regime_models),
            "playbooks": len(cxu_store.playbooks),
            "learnings": len(cxu_store.learnings),
        },
    }


@app.get("/api/ticks")
async def get_ticks():
    return {"ticks": list(tick_history)}


@app.get("/api/candles")
async def get_candles(timeframe: str = "1m", limit: int = 300):
    """Return OHLC candles. Fetches from Hyperliquid API if local data is insufficient."""
    store = candle_stores.get(timeframe)
    if not store:
        return JSONResponse({"error": f"Invalid timeframe. Use: {list(TIMEFRAMES.keys())}"}, status_code=400)

    local_candles = store.snapshot(limit)

    # If we have enough local data AND it's fresh, return it
    secs = TIMEFRAMES.get(timeframe, 60)
    is_fresh = False
    if local_candles:
        last_t = local_candles[-1].get("t", local_candles[-1].get("timestamp", 0))
        is_fresh = (time.time() - last_t) < secs * 3  # Within 3 candle periods
    if len(local_candles) >= limit * 0.8 and is_fresh:
        return {"timeframe": timeframe, "candles": local_candles, "source": "local"}

    # Fetch from Hyperliquid candle API to backfill
    try:
        hl_interval = timeframe  # HL uses same names: 1m, 3m, 5m, 15m, 1h
        start_ms = int((time.time() - secs * limit) * 1000)
        end_ms = int(time.time() * 1000)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.hyperliquid.xyz/info",
                json={
                    "type": "candleSnapshot",
                    "req": {
                        "coin": "ETH",
                        "interval": hl_interval,
                        "startTime": start_ms,
                        "endTime": end_ms,
                    }
                }
            )
            if resp.status_code == 200:
                hl_candles = resp.json()
                candles = []
                for c in hl_candles:
                    candles.append({
                        "t": c["t"] / 1000,
                        "o": float(c["o"]),
                        "h": float(c["h"]),
                        "l": float(c["l"]),
                        "c": float(c["c"]),
                        "v": float(c.get("v", 0)),
                        "n": int(c.get("n", 0)),
                    })

                # Save to DB
                if trader_db and candles:
                    trader_db.save_candles_batch(timeframe, [
                        {"timestamp": c["t"], "open": c["o"], "high": c["h"],
                         "low": c["l"], "close": c["c"], "ticks": c.get("n", 0)}
                        for c in candles
                    ])

                # Backfill in-memory store
                for c in candles:
                    if not any(abs(existing.timestamp - c["t"]) < 1 for existing in store.closed):
                        store.closed.append(Candle(
                            timestamp=c["t"], open=c["o"], high=c["h"],
                            low=c["l"], close=c["c"], ticks=c.get("n", 0),
                        ))
                sorted_candles = sorted(store.closed, key=lambda x: x.timestamp)
                store.closed.clear()
                store.closed.extend(sorted_candles)

                return {"timeframe": timeframe, "candles": candles[-limit:], "source": "hyperliquid", "count": len(candles)}
    except Exception as e:
        logger.warning("HL candle fetch failed: %s", e)

    return {"timeframe": timeframe, "candles": local_candles, "source": "local"}


@app.get("/api/macro")
async def get_macro():
    """Return current macro sentiment data."""
    if not sentiment_bias:
        return {"error": "Sentiment bias not initialized"}
    # Trigger a fresh compute if stale
    await sentiment_bias.compute()
    return sentiment_bias.get_stats()


@app.get("/api/exchanges")
async def get_exchanges():
    """Return multi-exchange price data and basis history."""
    if not exchange_feeds:
        return {"error": "Exchange feeds not initialized"}
    return exchange_feeds.get_snapshot()


@app.get("/api/predictions")
async def get_predictions():
    return {"predictions": direct_predictions}


# ─── Alert / Watch API ───────────────────────────────────────────

@app.post("/api/alerts/watch")
async def add_watch(body: dict):
    """Add a watch condition.

    Body:
        name: "Bounce Entry Dip"
        description: "Alert when price dips to lower BB band in ranging regime"
        conditions: {
            "bb_below": 20,          # BB position drops below 20%
            "regime_is": "ranging"    # only in ranging regime
        }
        cooldownSeconds: 300         # optional, default 5 min
    """
    name = body.get("name", "")
    description = body.get("description", "")
    conditions = body.get("conditions", {})

    if not name or not conditions:
        return JSONResponse({"error": "name and conditions required"}, status_code=400)

    watch = alert_manager.add_watch(
        name=name,
        description=description,
        conditions=conditions,
        cooldown_seconds=body.get("cooldownSeconds", 300),
    )
    return {"status": "created", "watch": watch.to_dict()}


@app.get("/api/alerts/watches")
async def list_watches():
    return {"watches": alert_manager.list_watches()}


@app.delete("/api/alerts/watch/{watch_id}")
async def remove_watch(watch_id: str):
    if alert_manager.remove_watch(watch_id):
        return {"status": "removed"}
    return JSONResponse({"error": "Watch not found"}, status_code=404)


@app.post("/api/agdel/autobuy")
async def toggle_autobuy():
    agdel_stats["autoBuy"] = not agdel_stats.get("autoBuy", False)
    return {"autoBuy": agdel_stats["autoBuy"]}


@app.post("/api/agdel/buy")
async def buy_signal(body: dict):
    if not agdel_buyer:
        return JSONResponse({"error": "AGDEL buyer not initialized"}, status_code=400)
    commitment_hash = body.get("commitmentHash", "")
    if not commitment_hash:
        return JSONResponse({"error": "commitmentHash required"}, status_code=400)
    try:
        result = await agdel_buyer.manual_purchase(commitment_hash)
        return {"status": "purchased", "result": result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/agdel/available")
async def get_available_signals():
    if not agdel_buyer:
        return []
    if hasattr(agdel_buyer, 'get_available_enriched'):
        return agdel_buyer.get_available_enriched()
    return []


@app.get("/api/agdel/purchases")
async def get_purchases():
    if not agdel_buyer:
        return {"purchases": []}
    return {"purchases": list(agdel_buyer.purchase_log)}


@app.post("/api/agdel/webhook/delivery")
async def agdel_webhook_delivery(body: dict):
    """Webhook endpoint for AGDEL signal delivery (encrypted)."""
    if not agdel_buyer:
        return JSONResponse({"error": "AGDEL buyer not initialized"}, status_code=400)
    try:
        if hasattr(agdel_buyer, 'handle_webhook_delivery'):
            await agdel_buyer.handle_webhook_delivery(body)
        return {"status": "ok"}
    except Exception as e:
        logger.error("AGDEL webhook error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/agdel/budget/reset")
async def reset_agdel_budget():
    if not agdel_buyer:
        return JSONResponse({"error": "AGDEL buyer not initialized"}, status_code=400)
    if hasattr(agdel_buyer, 'budget'):
        agdel_buyer.budget.reset_hourly()
    return {"status": "reset"}


# ─── Training Mode API ───────────────────────────────────────────

@app.post("/api/training/toggle")
async def toggle_training():
    global training_mode
    training_mode = not training_mode
    logger.info("Training mode: %s", "ON" if training_mode else "OFF")
    return {"trainingMode": training_mode}


@app.post("/api/training/observe")
async def training_observe(body: dict):
    """Record an observation and integrate it into the knowledge base.

    The LLM decides whether to update an existing CxU (strengthen/weaken it)
    or create a new one (only for genuinely new hypotheses).

    Body:
        reasoning: "what you observe and why it matters"
    """
    if not trainer or not hl_trader:
        return JSONResponse({"error": "Trainer not initialized"}, status_code=400)

    reasoning = body.get("reasoning", "")
    if not reasoning:
        return JSONResponse({"error": "reasoning is required"}, status_code=400)

    mark_price = await hl_trader.get_mark_price()
    position = await hl_trader.get_position()
    pos_dict = position.to_dict() if position else {}

    regime = latest_regime.get("data", {}).get("regime", "unknown")
    indicators = latest_regime.get("data", {}).get("indicators", {})
    consensus = latest_signal_assessment.get("data", {}).get("consensus", {})

    result = await trainer.process_observation(
        reasoning=reasoning,
        mark_price=mark_price,
        regime=regime,
        indicators=indicators,
        signal_consensus=consensus,
        position=pos_dict,
    )

    action = result.get("action", "error")

    if action in ("updated", "created"):
        # Reload CxU store so changes are visible
        cxu_store.reload()
        return {
            "status": "recorded",
            "learningCxu": result.get("cxu", {}),
            "action": action,
            "changeDescription": result.get("changeDescription", ""),
            "reasoning": result.get("reasoning", ""),
        }
    elif action == "noted":
        return {
            "status": "recorded",
            "learningCxu": {"alias": "n/a", "claim": "Observation noted — no CxU change warranted yet."},
            "action": "noted",
            "reasoning": result.get("reasoning", ""),
        }
    elif action == "flagged":
        return {
            "status": "recorded",
            "learningCxu": {"alias": result.get("cxuAlias", ""), "claim": "Relates to human-locked CxU — noted but not modified."},
            "action": "flagged",
            "reasoning": result.get("reasoning", ""),
        }
    else:
        return JSONResponse({"error": result.get("error", "Unknown error")}, status_code=500)


@app.post("/api/training/instruct")
async def training_instruct(body: dict):
    """Training mode: execute immediately, no challenge. Speed is critical.

    Body:
        action: "buy" | "sell" | "close"
        reasoning: "why you're making this trade"
        sizePct: 1-100 (% of available balance to use, default 100)
    """
    if not hl_trader:
        return JSONResponse({"error": "Trader not initialized"}, status_code=400)

    action = body.get("action", "").lower()
    if action not in ("buy", "sell", "close"):
        return JSONResponse({"error": "action must be buy, sell, or close"}, status_code=400)

    reasoning = body.get("reasoning", "")
    if not reasoning:
        return JSONResponse({"error": "reasoning is required"}, status_code=400)

    size_pct = body.get("sizePct", 100)
    try:
        size_pct = max(1, min(100, float(size_pct)))
    except (TypeError, ValueError):
        size_pct = 100

    # ── EXECUTE FAST ──────────────────────────────────────────────
    mark_price = await hl_trader.get_mark_price()
    if not mark_price:
        return JSONResponse({"error": "No price available"}, status_code=500)

    trade_action = "open_long" if action == "buy" else "open_short" if action == "sell" else "close"

    if trade_action == "close":
        result = await hl_trader.execute("close", 100, mark_price)
    else:
        # Compute notional from available balance (like HL UI)
        portfolio = await hl_trader.get_portfolio() or {}
        available = portfolio.get("availableBalance", 0)
        leverage = hl_trader.max_leverage
        notional = available * (size_pct / 100) * leverage

        logger.info("Training execute: %s %.0f%% of $%.2f avail × %dx lev = $%.2f notional",
                     trade_action, size_pct, available, leverage, notional)

        result = await hl_trader.execute_notional(trade_action, notional, mark_price)

    if not result or not result.success:
        error_msg = result.error if result else "Execution failed"
        return JSONResponse({"error": error_msg}, status_code=500)

    # ── REGIME + PLAYBOOK SL/TP ───────────────────────────────────
    regime = latest_regime.get("data", {}).get("regime", "unknown")
    sl_info = {}
    tp_info = {}

    if risk_manager and trade_action != "close":
        side = "long" if trade_action == "open_long" else "short"

        # Look up active playbook for SL/TP parameters
        playbook = cxu_store.get_playbook_for_regime(regime) if cxu_store else None
        if playbook:
            # Regime-specific SL/TP from CxU playbook
            pb_sl = playbook.param_value("trailingStopPct", None) or playbook.param_value("stopLossPct", None)
            pb_tp = playbook.param_value("tpFixedPct", None) or playbook.param_value("tpZoneHighPct", None)

            if pb_sl is not None:
                sl_pct = float(pb_sl) / 100  # playbook stores as %, risk_manager uses fraction
                risk_manager.sl_mode = "trailing"
                risk_manager.sl_trailing_pct = sl_pct
                logger.info("Playbook SL: trailing %.2f%% (from %s)", sl_pct * 100, playbook.alias)

            if pb_tp is not None:
                tp_pct = float(pb_tp) / 100
                risk_manager.tp_fixed_pct = tp_pct
                logger.info("Playbook TP: fixed %.2f%% (from %s)", tp_pct * 100, playbook.alias)

        # Activate risk tracking
        risk_manager.reset_watermark(mark_price, side)
        risk_manager.record_trade()

        # Compute the actual SL/TP prices for response
        levels = risk_manager.get_sl_tp_levels()
        sl_info = {"price": levels.get("slPrice"), "mode": levels.get("slMode"), "pct": risk_manager.sl_trailing_pct * 100}
        tp_info = {"price": levels.get("tpPrice"), "pct": risk_manager.tp_fixed_pct * 100}
    elif risk_manager and trade_action == "close":
        risk_manager.clear_position()

    # ── RECORD & BROADCAST ────────────────────────────────────────
    _record_trade(result, f"Training: {reasoning}", mark_price, regime=regime)

    # Create learning CxU (non-blocking — don't slow down the response)
    indicators = latest_regime.get("data", {}).get("indicators", {})
    consensus = latest_signal_assessment.get("data", {}).get("consensus", {})
    learning_alias = ""
    if trainer:
        try:
            instruction = TrainingInstruction(action=action, reasoning=reasoning)
            learning_cxu = trainer.create_training_cxu(
                instruction=instruction, mark_price=mark_price, regime=regime,
                indicators=indicators, signal_consensus=consensus,
            )
            learning_alias = learning_cxu.alias
            trainer.record_pending_outcome(f"training-{instruction.timestamp}", {
                "cxu_alias": learning_alias, "instruction": instruction.__dict__,
            })
        except Exception as e:
            logger.warning("Failed to create training CxU: %s", e)

    # Broadcast state immediately so position shows on dashboard
    new_pos = await hl_trader.get_position()
    new_pos_dict = new_pos.to_dict() if new_pos else {}
    await _broadcast_state(mark_price, new_pos_dict)

    return {
        "status": "executed",
        "action": trade_action,
        "price": mark_price,
        "size": result.size,
        "sizePct": size_pct,
        "fee": result.fee,
        "mode": hl_trader.mode,
        "regime": regime,
        "stopLoss": sl_info,
        "takeProfit": tp_info,
        "playbook": playbook.alias if (trade_action != "close" and cxu_store and cxu_store.get_playbook_for_regime(regime)) else None,
        "learningCxu": learning_alias,
    }


# ─── Main ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9004)
