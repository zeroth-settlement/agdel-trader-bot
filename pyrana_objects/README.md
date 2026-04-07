# Pyrana Objects

Platform artifacts for the AgDel Trader Bot. These are the agent's "brain" — the CxU knowledge base that evolves through structured reflection.

## Directory Structure

- `cxus/` — Context/Understanding Units organized by tier (axioms, regime models, playbooks, learnings)
- `agents/` — Agent definitions (regime-classifier, signal-assessor, trade-decider, reflector)
- `prompts/` — LLM prompt templates for each agent
- `scripts/` — Signal processing and analysis scripts
- `skills/` — Reusable logic components

## CxU Tiers

| Tier | Tag | Governance |
|------|-----|-----------|
| Axioms | `tier:axiom` | `approval:human` |
| Regime Models | `tier:regime-model` | `approval:human` |
| Playbooks | `tier:playbook` | `approval:agent` |
| Learnings | `tier:learning` | `approval:agent` |

## Sync with Pyrana Services

```bash
# Export from services
python scripts/pyrana_sync.py export --tag agdel-trader-bot --output-dir ./pyrana_objects/

# Import to services
python scripts/pyrana_sync.py import --input-dir ./pyrana_objects/
```
