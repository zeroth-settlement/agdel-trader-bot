# AgDel Trader Bot — Session Summary

## Timeline: April 7–17, 2026 (10 days)

### What We Built

A CxU-driven autonomous trading agent for ETH-USD perpetuals on Hyperliquid, evolving from a broken prototype (trader-bot-basic that lost $289) into a working system with:

- **74 CxUs** — institutional knowledge base that grows from every trade and observation
- **Dashboard** at `localhost:9004` — candlestick chart, signal projection, order book panel, position tracker, conviction meter, training mode
- **3 autonomous monitors**: dip buyer, spike catcher, trailing stop ratchet
- **Signal feed** from agdel-signal-bots + AGDEL marketplace
- **Order book analysis** — wall detection, imbalance tracking, accumulation/markup phase detection, spoof identification
- **SQLite persistence** — candles, trades, signals survive restarts
- **HL integration** — stop orders via SDK, position tracking, candle backfill

### Key Trading Strategies (CxU-backed)

1. **Bounce Setup Strategy** (`bounce-setup-strategy`): Market read → counter-spike → regime-sized entry → adaptive trailing stop
2. **V-Dip Auto-Buy** (`v-dip-auto-buy`): $8+ red 5m candle → green recovery → auto-buy 1 ETH, pyramid up to 15 ETH cap
3. **Spike Top Auto-Sell** (`spike-top-auto-sell`): $10+ spike in 2 candles + stall → auto-sell 50%
4. **Graceful Unwind** (`graceful-unwind`): Oversized position → TP at breakeven for 50% + tight SL for 50% + safety SL for remainder
5. **Adaptive Trailing Stop**: 1.5% → 1.0% → 0.75% → 0.5% as profit grows

### Critical Learnings (Axioms)

- **Never test stop orders on live positions** — cost real money when test stops got cancelled
- **Training mode = human control only** — agent must never execute trades autonomously on live unless explicitly armed (dip buyer, spike catcher)
- **Hyperliquid fees** — 0.045% taker, round-trip costs must be estimated before every trade
- **Cancel paired orders on graceful unwind** — when SL half triggers, cancel the TP immediately

### Signal Analysis Results (80 hours, 4,812 data points)

| Signal | Directional Accuracy | Weight |
|--------|---------------------|--------|
| options-skew | 55-56% (best) | 3x |
| bb-reversal | 52% | 1.5x |
| mesa | 52% | 1.5x |
| regime | 38% (anti-useful) | IGNORED |
| oi | 42% | IGNORED |
| Most others | 48-52% (noise) | 0.5-1.0x |

Key finding: NEUTRAL predictions are 63% accurate — "nothing will happen" is the most reliable signal.

### Architecture

```
Monitors (always running):
  dip_buyer.py      — V-dip detection on 5m candles, auto-buy + pyramid
  spike_catcher.py  — Spike detection on 1m candles, auto-sell 50%
  ratchet_monitor.py — Adaptive trailing stop via HL stop orders

Trading Server (port 9004):
  trading_server.py — FastAPI, WebSocket, tick loop, agent pipeline
  dashboard.html    — Single-file trading dashboard

CxU Knowledge Base (74 CxUs):
  pyrana_objects/cxus/ — Axioms, regime models, playbooks, learnings

Data:
  data/trader.db          — SQLite (candles, trades, signals)
  data/conviction_tracker.db — Signal accuracy tracking
  data/trade_history.jsonl   — Trade log
```

### Stop Order Management

The trailing stop went through multiple iterations:
1. Software-only SL (server crash = unprotected) ❌
2. HL SDK `order()` with trigger type (works but cancel+place has gaps) ⚠️
3. `modify_order()` (atomic but HL rejects inconsistently) ⚠️
4. Cancel + 2s delay + place (current, mostly reliable) ✓
5. `stop_manager.py` — isolated module with place/modify/verify/sync

Key issues: HL `openOrders` doesn't show trigger orders (use `frontendOpenOrders`), can't have two reduce_only stops covering full position size, `triggerPx` must be float not string.

### What's Working

- Dip buyer auto-buying V-dips and pyramiding ✓
- Spike catcher detecting tops and auto-selling 50% ✓  
- Ratchet trailing stops up on HL ✓
- Order book wall detection and accumulation phase ✓
- Signal conviction meter (weighted by validated accuracy) ✓
- Position tracker with breakeven, fees, liquidation ✓
- ntfy push notifications ✓

### What Needs Work

- Paper trading P&L still needs validation
- Ratchet occasionally loses stops during cancel+place
- Signal accuracy could be improved with per-horizon analysis
- Auto-trading pipeline (agent decisions) not profitable yet — needs more CxU tuning
- Dip buyer `sizePct: 5` may not equal exactly 1 ETH depending on equity

### Running the System

```bash
# Start trading server (live mode for HL connection, then switch to paper)
TRADING_MODE=live python3 start_trading.py

# Start monitors (in separate terminals or background)
python3 -u ratchet_monitor.py    # Trailing stop
python3 -u dip_buyer.py          # V-dip auto-buy
python3 -u spike_catcher.py      # Spike top auto-sell
python3 -u conviction_tracker.py # Signal accuracy tracking
```

### Environment

- Python 3.14, FastAPI, Hyperliquid SDK
- ETH-USD perpetuals on Hyperliquid
- Signal feed from agdel-signal-bots (Coolify deployment)
- AGDEL marketplace for purchased signals
- ntfy.sh for push notifications
