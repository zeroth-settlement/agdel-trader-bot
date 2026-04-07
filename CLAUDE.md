# AgDel Trader Bot

CxU-driven autonomous trading agent for ETH-USD on Hyperliquid.

## Architecture

```
CxU Knowledge Base (pyrana_objects/cxus/)
  ├── Axioms (human-locked) ─────── Core trading truths
  ├── Regime Models (human-locked) ─ Market regime definitions
  ├── Playbooks (agent-adjustable) ─ Strategy parameters per regime
  └── Learnings (agent-created) ──── Observed patterns from outcomes
         │
         ▼
  ┌─────────────────────────────────────────────────┐
  │           Agent Pipeline (per tick)              │
  │  1. Regime Classifier → identify market state    │
  │  2. Signal Assessor → evaluate incoming signals  │
  │  3. Trade Decider → CxU-assembled decision       │
  │  4. Reflector → post-trade CxU evolution         │
  └─────────────────────────────────────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
  Signal    Hyperliquid
  Feeds     Execution
  (2 channels)
```

## Signal Channels

1. **AGDEL Marketplace** — Selective, high-quality purchased signals for confirming big trades
2. **Direct Signal Feed** — ~500 signals/tick from agdel-signal-bots for insights and signal quality assessment

## CxU Tiers

| Tier | Governance | Purpose |
|------|-----------|---------|
| Axioms | Human-locked | Core truths validated through experience |
| Regime Models | Human-locked | Market regime classification criteria |
| Playbooks | Agent-adjustable | Strategy parameters with bounds |
| Learnings | Agent-created | Patterns observed from trade outcomes |

## Project Structure

```
agdel-trader-bot/
├── dashboard.html          # Single-file trading dashboard
├── bridge_server.py        # Pyrana bridge (port 9002)
├── start.py                # Launcher
├── project.json            # Project manifest
├── shared/                 # Pyrana design guide + components
├── pyrana_objects/
│   ├── cxus/               # CxU knowledge base (the agent's brain)
│   ├── agents/             # Agent definitions
│   ├── prompts/            # LLM prompts
│   ├── scripts/            # Signal processing scripts
│   └── skills/             # Reusable logic
├── requirements/
│   ├── problem-statement.md
│   ├── output-contract.md
│   └── architecture.md
├── data/
│   ├── test-data/
│   ├── exports/
│   └── sample-output.json
└── logs/
```

## Running

```bash
pip install -r requirements.txt
python start.py              # Bridge server on :9002
```

The dashboard connects to:
- Bridge server at `localhost:9002` (CxUs, components, design guide)
- Trading server at `localhost:9004` (WebSocket state, trade execution)
- Signal bot at `localhost:9502` (direct signal feed)

## Key Principles (from Trading Wiki)

1. Fees kill: $13 minimum edge per trade
2. Hold is correct 80% of the time
3. Signal direction is ~50% accurate (coin flip)
4. Max size or no trade (small positions eaten by fees)
5. Regime classification matters most
6. Simplicity beats complexity
7. 2-3 trades/day maximum

## CxU Schema

All CxUs follow the Pyrana CxU schema with required fields:
- `cxu_id` (multihash SHA-256)
- `cxu_object.claim` (min 10 chars, min 5 words)
- `cxu_object.supporting_contexts` (min 1, each min 20 chars)
- `cxu_object.metadata.knowledge_type` (axiom | derived | prescribed)
- `cxu_object.metadata.claim_type` (definition | hypothesis | finding | procedure | etc.)
- `version.number`, `version.created_at`, `version.created_by`
- `mutable_metadata.status` (Active | Draft | Superseded | Retired)

Tags for tier classification:
- `tier:axiom` + `approval:human` + `cxu_class:hypothesis`
- `tier:regime-model` + `approval:human` + `cxu_class:hypothesis`
- `tier:playbook` + `approval:agent` + `cxu_class:parameter`
- `tier:learning` + `approval:agent` + `cxu_class:parameter`

## Integrations

- **Hyperliquid**: ETH perps, taker fee 0.0432%
- **AGDEL Marketplace**: Signal purchasing with budget controls
- **Signal Bot**: Direct feed for cluster analysis
- **Pyrana Services**: CxU CRUD at localhost:8001
