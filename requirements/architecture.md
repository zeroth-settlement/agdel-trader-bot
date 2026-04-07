# Architecture

## System Overview

```
                    ┌─────────────────────┐
                    │   Pyrana Services    │
                    │  CxU Manager :8001  │
                    │  Script Mgr  :8002  │
                    │  Prompt Mgr  :8003  │
                    │  Agent Mgr   :8105  │
                    └─────────┬───────────┘
                              │ CRUD
                    ┌─────────▼───────────┐
                    │   CxU Knowledge     │
                    │   Base (Brain)      │
                    │                     │
                    │ Axioms  | Regime    │
                    │ Models  | Playbooks │
                    │ Learnings           │
                    └─────────┬───────────┘
                              │ cite
         ┌────────────────────┼────────────────────┐
         │                    │                    │
  ┌──────▼──────┐   ┌────────▼────────┐   ┌──────▼──────┐
  │   Regime     │   │  Signal         │   │   Trade     │
  │  Classifier  │   │  Assessor       │   │  Decider    │
  │              │   │                 │   │             │
  │ regime CxUs  │   │ learning CxUs   │   │ all CxUs    │
  │ → classify   │   │ → rate signals  │   │ → decide    │
  └──────┬───────┘   └────────┬────────┘   └──────┬──────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                    ┌─────────▼───────────┐
                    │  Trading Server     │
                    │  (port 9004)        │
                    │                     │
                    │  Risk Manager       │
                    │  HL Execution       │
                    │  WebSocket State    │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
     ┌────────▼──────┐  ┌────▼─────┐  ┌──────▼──────┐
     │ AGDEL Market  │  │ Signal   │  │ Hyperliquid │
     │ (purchased)   │  │ Bot Feed │  │ (execution) │
     │ selective,    │  │ :9502    │  │ ETH-USD     │
     │ high quality  │  │ ~500/tick│  │ perps       │
     └───────────────┘  └──────────┘  └─────────────┘

                    ┌─────────────────────┐
                    │   Reflector Agent   │
                    │                     │
                    │ Post-trade analysis │
                    │ → Create learnings  │
                    │ → Update playbooks  │
                    │ → Propose axioms    │
                    └─────────────────────┘
```

## Data Flow

### Per-Tick Loop (every 5 seconds)
1. Fetch mark price + position from Hyperliquid
2. Risk check: SL/TP on open positions (immediate close if hit)
3. Regime Classifier: classify market state using regime CxUs
4. Signal Assessor: evaluate signals against learning CxUs + current regime
5. Trade Decider: assemble axiom + playbook + assessment CxUs → decision
6. Execute trade if non-hold (via Hyperliquid)
7. Record trade with CxU citation chain
8. Broadcast state via WebSocket

### Reflection Loop (every 30 minutes)
1. Analyze last N trades: P&L, win rate, fee drag
2. Cross-reference with settled signal predictions
3. Propose CxU updates:
   - Playbook parameter adjustments (within bounds)
   - New learning CxUs (with evidence)
   - Flag axiom/regime proposals for human review
4. Apply approved changes via Pyrana services
5. Version-track all CxU modifications

### Signal Channels

**Channel A: AGDEL Marketplace (Selective)**
- Purchase high-quality signals to confirm big trade decisions
- Budget: $2/signal, $50/hr, $250/day
- Filter by maker reputation, win rate, calibration
- Used for: trade confirmation, not primary direction

**Channel B: Direct Signal Feed (High Volume)**
- ~500 signals per tick from agdel-signal-bots
- All 16+ signal types across 4 horizons
- Used for: cluster drift analysis, signal quality assessment
- Informs which signals the signal bot should publish to AGDEL

## CxU Governance

| Action | Axioms | Regime Models | Playbooks | Learnings |
|--------|--------|--------------|-----------|-----------|
| Create | Human only | Human only | Agent | Agent |
| Read | All agents | Regime Classifier | Trade Decider | Signal Assessor |
| Update | Human only | Human only | Agent (within bounds) | Agent |
| Delete | Human only | Human only | Human only | Agent (supersede) |

## Technology

- **Runtime**: Python 3.10+ (FastAPI, asyncio)
- **LLM**: Claude or GPT for agent reasoning
- **Execution**: Hyperliquid Python SDK
- **CxU Storage**: Pyrana Services (REST API) + local JSON exports
- **Dashboard**: Single-file HTML (Pyrana design guide)
- **Real-time**: WebSocket for dashboard state
