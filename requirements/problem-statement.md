# Problem Statement

## Domain
Autonomous cryptocurrency trading on Hyperliquid ETH-USD perpetuals.

## Problem
The existing trader-bot-basic lost $289 (-5.4%) over one week of live trading despite having sophisticated signal integration, LLM reasoning, and risk management. The core issues are:

1. **No institutional memory** — the bot doesn't learn from its mistakes; knowledge lives in YAML configs and gets lost between sessions
2. **Signal direction is broken** — 8,000+ predictions show ~50% directional accuracy (coin flip)
3. **Fee destruction** — high-frequency trading strategies pay $13+ per round-trip, eating all alpha
4. **No regime awareness** — single strategy applied regardless of market conditions
5. **Complexity doesn't help** — matrix engines, complex signal aggregation, and clever algorithms underperform simple English-language rules

## Solution: CxU-Driven Trading
Use Context/Understanding Units (CxUs) as the agent's active knowledge repository:

- **Axioms** encode hard-won truths (human-locked, can't be overridden)
- **Regime Models** define market states (human-locked classification criteria)
- **Playbooks** specify strategy parameters per regime (agent-adjustable within bounds)
- **Learnings** capture what worked and what didn't (agent-created with evidence)

Every trade decision cites specific CxUs. The reflector agent proposes CxU updates after analyzing outcomes. Knowledge compounds across sessions.

## Audience
- James (primary) — trading strategist, monitoring and adjusting the bot's CxU knowledge base
- The agent itself — using CxUs as its decision-making substrate

## MVP Scope
1. Dashboard showing live trading with CxU citations on decisions
2. Dual signal feeds (AGDEL marketplace + direct signal bot)
3. CxU knowledge browser organized by tier
4. Trade history with full provenance chain
5. Reflection loop that proposes CxU updates

## Success Metrics
- Positive P&L over a 1-week period
- Fewer than 4 trades per day (fee discipline)
- CxU knowledge base grows with validated learnings
- Every trade has CxU citation chain
