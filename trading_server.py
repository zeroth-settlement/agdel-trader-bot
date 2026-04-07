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

# New CxU-driven modules
from cxu_store import CxUStore
from agents.regime_classifier import RegimeClassifier
from agents.signal_assessor import SignalAssessor
from agents.trade_decider import TradeDecider
from agents.reflector import Reflector
from agents.trainer import Trainer, TrainingInstruction
from alerts import AlertManager

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

cxu_store: Optional[CxUStore] = None
regime_classifier: Optional[RegimeClassifier] = None
signal_assessor: Optional[SignalAssessor] = None
trade_decider: Optional[TradeDecider] = None
reflector: Optional[Reflector] = None
trainer: Optional[Trainer] = None
training_mode: bool = False
alert_manager: AlertManager = AlertManager()

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

    # Update all candle stores
    closed_candles = {}
    for tf, store in candle_stores.items():
        closed = store.update(price, ts)
        if closed:
            closed_candles[tf] = closed.to_dict()

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

    for ws in ws_clients[:]:
        try:
            await ws.send_json(msg)
        except Exception:
            pass


# ─── Lifespan ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global hl_trader, risk_manager, bounce_trigger, ratchet_tp
    global sentiment_bias, cluster_tracker
    global cxu_store, regime_classifier, signal_assessor, trade_decider, reflector, trainer
    global trade_history

    logger.info("=" * 50)
    logger.info("  AgDel Trader Bot — Starting")
    logger.info("=" * 50)

    # Load config
    load_config()

    # Load trade history
    trade_history = list(load_jsonl(TRADE_HISTORY_PATH, maxlen=200))
    logger.info("  Loaded %d historical trades", len(trade_history))

    # Initialize trading components
    trading_mode = "paper"  # Always start in paper mode
    paper_balance = config.get("trading", {}).get("paperStartingBalanceUsd", 5000)

    hl_trader = HLTrader(config, mode=trading_mode)
    logger.info("  HL Trader: %s mode ($%s paper balance)", trading_mode, paper_balance)

    risk_manager = RiskManager(config)

    bounce_trigger = BounceTrigger()
    ratchet_tp = RatchetTP()
    sentiment_bias = SentimentBias()
    cluster_tracker = ClusterTracker()

    # Initialize CxU store and agents
    cxu_store = CxUStore()
    regime_classifier = RegimeClassifier(config, cxu_store)
    signal_assessor = SignalAssessor(config, cxu_store)
    trade_decider = TradeDecider(config, cxu_store)
    reflector = Reflector(config, cxu_store)
    trainer = Trainer(config, cxu_store)

    # Connect to Hyperliquid
    try:
        await hl_trader.connect()
        logger.info("  Connected to Hyperliquid")
    except Exception as e:
        logger.warning("  HL connection failed (paper mode ok): %s", e)

    # Start real-time price feed via WebSocket
    try:
        await hl_trader.start_price_feed(callback=_on_price_tick)
        logger.info("  Real-time price feed started (WS allMids)")
    except Exception as e:
        logger.warning("  Price feed start failed: %s", e)

    # Start background loops
    tasks = []
    tasks.append(asyncio.create_task(tick_loop()))

    if config.get("reflection", {}).get("enabled", True):
        tasks.append(asyncio.create_task(reflection_loop()))

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

    # 3. Risk check (always runs, every tick)
    if risk_manager and pos_dict.get("side") and pos_dict["side"] != "FLAT":
        risk_levels = risk_manager.get_sl_tp_levels()

        # Stop loss check
        sl_triggered, sl_reason = risk_manager.check_stop_loss(mark_price)
        if sl_triggered:
            logger.info("STOP LOSS triggered at $%.2f: %s", mark_price, sl_reason)
            result = await hl_trader.execute("close", 100, mark_price)
            if result and result.success:
                _record_trade(result, f"SL: {sl_reason}", mark_price)
                risk_manager.clear_position()
            return

        # Take profit check
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

    # 4. Rate limit — only run agent pipeline at decision interval
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
        action = decision_output.data.get("action", "hold")
        if auto_trade and action != "hold" and decision_output.success:
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

    # 6. Check alerts
    if alert_manager.watches:
        regime = latest_regime.get("data", {}).get("regime", "unknown")
        indicators = latest_regime.get("data", {}).get("indicators", {})
        triggered = await alert_manager.check_all(mark_price, indicators, regime, pos_dict)
        for alert in triggered:
            # Send alert to dashboard via WebSocket
            for ws in ws_clients[:]:
                try:
                    await ws.send_json({"type": "alert", **alert})
                except Exception:
                    pass

    # 7. Broadcast state
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
    logger.info("TRADE: %s | %s | regime=%s | citations=%d",
                trade.get("action"), rationale[:60], regime, len(citations or []))


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


# ─── WebSocket ───────────────────────────────────────────────────
async def _broadcast_state(mark_price: float, position: dict):
    """Build and broadcast state to all WebSocket clients."""
    portfolio = {}
    hl_position = {}
    hl_portfolio = {}

    if hl_trader:
        try:
            portfolio = await hl_trader.get_portfolio() or {}
        except Exception:
            pass
        try:
            hl_pos = await hl_trader.get_position()
            hl_position = hl_pos.to_dict() if hl_pos else {}
        except Exception:
            pass
        hl_portfolio = portfolio

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

        # Signals
        "predictions": direct_predictions[:50],
        "purchases": purchased_signals[:50],
        "availableSignals": available_signals[:50],

        # AGDEL
        "agdel": agdel_stats,

        # Training mode
        "trainingMode": training_mode,

        # Performance (computed from trade history)
        "performance": _compute_performance(),

        # Agent outputs (for Agent Output tab)
        "agentOutputs": {
            "regime-classifier": latest_regime,
            "signal-assessor": latest_signal_assessment,
            "trade-decider": latest_decision,
            "reflector": latest_reflection,
        },
    }

    # Broadcast to all clients
    for ws in ws_clients[:]:
        try:
            await ws.send_json(state)
        except Exception:
            ws_clients.remove(ws)


def _get_active_playbook() -> str:
    regime = latest_regime.get("data", {}).get("regime", "unknown")
    playbook = cxu_store.get_playbook_for_regime(regime) if cxu_store else None
    return playbook.alias if playbook else "none"


def _compute_performance() -> Dict[str, Any]:
    if not trade_history:
        return {"winRate": 0, "totalTrades": 0, "totalFees": 0, "tradesToday": 0}
    wins = sum(1 for t in trade_history if (t.get("pnl") or 0) > 0)
    total_fees = sum(t.get("fee", 0) for t in trade_history)
    today = datetime.now(timezone.utc).date()
    trades_today = 0
    for t in trade_history:
        try:
            ts = t.get("timestamp", "")
            if isinstance(ts, str) and ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.date() == today:
                    trades_today += 1
        except Exception:
            pass
    return {
        "winRate": wins / len(trade_history) if trade_history else 0,
        "totalTrades": len(trade_history),
        "totalFees": total_fees,
        "tradesToday": trades_today,
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
    if mode in ("paper", "live"):
        hl_trader.mode = mode
        logger.info("Mode switched to %s", mode)
        return {"mode": mode}
    return JSONResponse({"error": "Invalid mode"}, status_code=400)


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
async def get_candles(timeframe: str = "1m", limit: int = 200):
    """Return OHLC candles for the given timeframe."""
    store = candle_stores.get(timeframe)
    if not store:
        return JSONResponse({"error": f"Invalid timeframe. Use: {list(TIMEFRAMES.keys())}"}, status_code=400)
    return {"timeframe": timeframe, "candles": store.snapshot(limit)}


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
    # TODO: wire to agdel_buyer
    return {"status": "not_implemented"}


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
    """Submit a manual trading instruction.

    Body:
        action: "buy" | "sell" | "close"
        reasoning: "why you want to do this"
        conditions: "what conditions you see" (optional)
        force: true to skip challenge (optional)

    Returns a challenge response if the agent disagrees,
    or executes the trade and creates a learning CxU if it agrees.
    """
    if not trainer or not hl_trader:
        return JSONResponse({"error": "Trainer not initialized"}, status_code=400)

    action = body.get("action", "").lower()
    if action not in ("buy", "sell", "close"):
        return JSONResponse({"error": "action must be buy, sell, or close"}, status_code=400)

    reasoning = body.get("reasoning", "")
    if not reasoning:
        return JSONResponse({"error": "reasoning is required — tell the agent why"}, status_code=400)

    instruction = TrainingInstruction(
        action=action,
        reasoning=reasoning,
        conditions=body.get("conditions", ""),
        force=body.get("force", False),
    )

    # Get current market context
    mark_price = await hl_trader.get_mark_price()
    position = await hl_trader.get_position()
    pos_dict = position.to_dict() if position else {}

    regime = latest_regime.get("data", {}).get("regime", "unknown")
    indicators = latest_regime.get("data", {}).get("indicators", {})
    consensus = latest_signal_assessment.get("data", {}).get("consensus", {})

    # Evaluate the instruction against CxUs
    challenge = await trainer.evaluate_instruction(
        instruction=instruction,
        mark_price=mark_price,
        regime=regime,
        indicators=indicators,
        signal_consensus=consensus,
        position=pos_dict,
    )

    if not challenge.agrees and not instruction.force:
        # Return the challenge — user must force-override or accept
        return {
            "status": "challenged",
            "challenge": challenge.to_dict(),
            "message": "The agent disagrees with your instruction. Use force=true to override.",
        }

    # Agent agrees (or user forced) — execute the trade
    trade_action = "open_long" if action == "buy" else "open_short" if action == "sell" else "close"
    result = await hl_trader.execute(trade_action, 100, mark_price)

    if not result or not result.success:
        return JSONResponse({"error": "Trade execution failed"}, status_code=500)

    # Record the trade
    _record_trade(
        result,
        f"Training: {reasoning}",
        mark_price,
        regime=regime,
        citations=[c for c in challenge.conflicting_cxus],
    )

    # Update risk manager
    if risk_manager and trade_action != "close":
        new_pos = await hl_trader.get_position()
        if new_pos and new_pos.side != "FLAT":
            risk_manager.reset_watermark(new_pos.entry_price or mark_price, new_pos.side)

    # Create a learning CxU from this instruction
    learning_cxu = trainer.create_training_cxu(
        instruction=instruction,
        mark_price=mark_price,
        regime=regime,
        indicators=indicators,
        signal_consensus=consensus,
    )

    # Record pending outcome for when the trade closes
    trade_id = f"training-{instruction.timestamp}"
    trainer.record_pending_outcome(trade_id, {
        "cxu_alias": learning_cxu.alias,
        "instruction": instruction.__dict__,
    })

    return {
        "status": "executed",
        "action": trade_action,
        "price": mark_price,
        "challenge": challenge.to_dict(),
        "learningCxu": {
            "alias": learning_cxu.alias,
            "claim": learning_cxu.claim,
        },
        "message": f"Trade executed. Learning CxU '{learning_cxu.alias}' created.",
    }


# ─── Main ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9004)
