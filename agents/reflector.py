"""Reflector — post-trade analysis that evolves CxUs through structured learning.

Runs every 30 minutes. Analyzes recent trades, proposes CxU updates with evidence.
Only modifies playbook and learning CxUs — axioms and regime models are human-locked.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agents.base import AgentOutput, BaseAgent
from cxu_store import CxU, CxUStore

logger = logging.getLogger("agents.reflector")


class Reflector(BaseAgent):
    AGENT_ID = "reflector"
    AGENT_NAME = "Reflector"

    def __init__(self, config: dict, cxu_store: CxUStore):
        super().__init__(config)
        self.cxu_store = cxu_store
        self.cycle = 0

    async def reflect(
        self,
        recent_trades: List[Dict[str, Any]],
        settled_predictions: List[Dict[str, Any]],
    ) -> AgentOutput:
        """Analyze performance and propose CxU updates.

        Args:
            recent_trades: Trades since last reflection
            settled_predictions: Settled signal predictions with outcomes
        """
        self.cycle += 1
        min_trades = self.config.get("reflection", {}).get("minTradesForReflection", 3)
        min_signals = self.config.get("reflection", {}).get("minSignalsForReflection", 5)

        if len(recent_trades) < min_trades and len(settled_predictions) < min_signals:
            return self._make_output(
                data={
                    "cycle": self.cycle,
                    "tradesAnalyzed": len(recent_trades),
                    "signalsSettled": len(settled_predictions),
                    "summary": f"Insufficient data: {len(recent_trades)} trades (need {min_trades}), "
                               f"{len(settled_predictions)} signals (need {min_signals})",
                    "cxusCreated": 0,
                    "cxusUpdated": 0,
                    "pendingHumanReview": 0,
                    "changes": [],
                },
                citations=[],
                reasoning="Skipped — not enough data",
            )

        # Compute performance metrics
        perf = self._compute_performance(recent_trades)
        signal_accuracy = self._compute_signal_accuracy(settled_predictions)

        # Load current CxUs for context
        playbooks = self.cxu_store.playbooks
        learnings = self.cxu_store.learnings
        cxu_context = "\n\n".join(c.to_prompt_context() for c in playbooks + learnings)

        system = f"""You are a trading strategy reflector that evolves CxU knowledge.

CURRENT CxUs (playbooks and learnings you can modify):
{cxu_context}

GOVERNANCE RULES:
1. You can UPDATE playbook CxU parameters within their min/max bounds.
2. You can CREATE new learning CxUs to capture discovered patterns.
3. You CANNOT modify axioms or regime models (they are human-locked).
4. Every change must include evidence from the trade/signal data.
5. Be conservative — only propose changes with strong evidence (3+ data points).
6. Never shrink position sizing based on a few losses (reflection death spiral).

Respond with JSON:
{{
  "summary": "brief analysis",
  "changes": [
    {{
      "action": "update | create",
      "cxuAlias": "alias of CxU to update (or new alias for create)",
      "field": "parameters.fieldName (for updates)",
      "before": "old value (for updates)",
      "after": "new value (for updates)",
      "claim": "claim text (for creates)",
      "tier": "learning (for creates)",
      "evidence": "specific data supporting this change",
      "reason": "why this change improves performance"
    }}
  ],
  "performanceDelta": {{
    "winRate": current_win_rate,
    "avgPnl": avg_pnl_per_trade,
    "totalFees": total_fees
  }}
}}"""

        user = f"""## Trade Performance (since last reflection)
Trades: {perf['total']}
Wins: {perf['wins']} | Losses: {perf['losses']}
Win Rate: {perf['winRate']:.1%}
Total P&L: ${perf['totalPnl']:.2f}
Total Fees: ${perf['totalFees']:.2f}
Net after fees: ${perf['totalPnl'] - perf['totalFees']:.2f}
Avg hold time: {perf['avgHoldTime']}

## Trade Details
{self._format_trades(recent_trades)}

## Signal Accuracy (settled predictions)
{self._format_signal_accuracy(signal_accuracy)}

## Current Time
{datetime.now(timezone.utc).isoformat()}"""

        result = await self.call_llm(system, user)

        changes_applied = []
        cxus_created = 0
        cxus_updated = 0

        if result:
            metrics = result.pop("_metrics", {})
            proposed_changes = result.get("changes", [])

            for change in proposed_changes:
                action = change.get("action")
                alias = change.get("cxuAlias", "")

                if action == "update":
                    field = change.get("field", "")
                    if field.startswith("parameters."):
                        param_key = field.replace("parameters.", "")
                        new_val = change.get("after")
                        if new_val is not None:
                            try:
                                new_val = float(new_val) if isinstance(new_val, str) and "." in new_val else new_val
                                if isinstance(new_val, str) and new_val.isdigit():
                                    new_val = int(new_val)
                            except (ValueError, TypeError):
                                pass

                            updated = self.cxu_store.update_cxu(
                                alias=alias,
                                param_updates={param_key: new_val},
                                change_description=change.get("reason", "Reflection update"),
                                modified_by="reflector-agent",
                            )
                            if updated:
                                cxus_updated += 1
                                changes_applied.append(change)

                elif action == "create":
                    claim = change.get("claim", "")
                    evidence = change.get("evidence", "")
                    if claim and len(claim) >= 10:
                        new_cxu = self.cxu_store.create_cxu(
                            alias=alias,
                            claim=claim,
                            supporting_contexts=[{"text": evidence, "line": None}],
                            knowledge_type="derived",
                            claim_type="finding",
                            tier="learning",
                            created_by="reflector-agent",
                        )
                        cxus_created += 1
                        changes_applied.append(change)

            summary = result.get("summary", "Reflection completed")
            perf_delta = result.get("performanceDelta", {})
        else:
            metrics = {}
            summary = "LLM reflection failed — no changes applied"
            perf_delta = {}

        return self._make_output(
            data={
                "cycle": self.cycle,
                "tradesAnalyzed": len(recent_trades),
                "signalsSettled": len(settled_predictions),
                "summary": summary,
                "cxusCreated": cxus_created,
                "cxusUpdated": cxus_updated,
                "pendingHumanReview": 0,
                "changes": changes_applied,
                "performanceDelta": perf_delta,
            },
            citations=[c.to_citation() for c in self.cxu_store.playbooks + self.cxu_store.learnings],
            reasoning=summary,
            metrics=metrics,
        )

    def _compute_performance(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not trades:
            return {"total": 0, "wins": 0, "losses": 0, "winRate": 0, "totalPnl": 0, "totalFees": 0, "avgHoldTime": "n/a"}
        wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
        losses = sum(1 for t in trades if (t.get("pnl") or 0) < 0)
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        total_fees = sum(t.get("fee", 0) for t in trades)
        return {
            "total": len(trades),
            "wins": wins,
            "losses": losses,
            "winRate": wins / len(trades) if trades else 0,
            "totalPnl": total_pnl,
            "totalFees": total_fees,
            "avgHoldTime": "n/a",  # TODO: compute from timestamps
        }

    def _compute_signal_accuracy(self, predictions: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
        accuracy = {}
        for p in predictions:
            sig_type = p.get("signal_type") or p.get("type") or p.get("agent", "unknown")
            if sig_type not in accuracy:
                accuracy[sig_type] = {"correct": 0, "incorrect": 0, "total": 0}
            accuracy[sig_type]["total"] += 1
            if p.get("outcome") == "win" or p.get("correct"):
                accuracy[sig_type]["correct"] += 1
            else:
                accuracy[sig_type]["incorrect"] += 1
        return accuracy

    def _format_trades(self, trades: List[Dict[str, Any]]) -> str:
        if not trades:
            return "No trades."
        lines = []
        for t in trades[-15:]:
            pnl = t.get("pnl", 0)
            fee = t.get("fee", 0)
            lines.append(
                f"  {t.get('action', '?'):12s} | size={t.get('size', '?')} | "
                f"price=${t.get('price', 0):,.2f} | pnl=${pnl:+.2f} | fee=${fee:.2f} | "
                f"regime={t.get('regime', '?')}"
            )
        return "\n".join(lines)

    def _format_signal_accuracy(self, accuracy: Dict[str, Dict[str, int]]) -> str:
        if not accuracy:
            return "No settled predictions."
        lines = []
        for sig_type, data in sorted(accuracy.items(), key=lambda x: x[1]["total"], reverse=True):
            rate = data["correct"] / data["total"] * 100 if data["total"] else 0
            lines.append(f"  {sig_type:25s} | {data['correct']}/{data['total']} ({rate:.0f}%)")
        return "\n".join(lines)
