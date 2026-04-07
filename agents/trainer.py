"""Trainer — handles manual training mode.

When the user instructs "buy" or "sell", the trainer:
1. Captures current market context (price, regime, signals, indicators)
2. Checks if the instruction conflicts with existing CxUs
3. If conflict → challenges the user with specific CxU-backed reasoning
4. If no conflict or user confirms → executes the trade
5. Creates a learning CxU from the instruction + context
6. Tracks the outcome and updates the learning CxU when the trade closes

The training mode is the primary way humans teach the agent. Every manual
instruction becomes institutional knowledge via CxUs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agents.base import AgentOutput, BaseAgent
from cxu_store import CxU, CxUStore

logger = logging.getLogger("agents.trainer")


class TrainingInstruction:
    """A manual trading instruction from the user."""

    def __init__(
        self,
        action: str,  # "buy", "sell", "close"
        reasoning: str,  # User's stated reason
        conditions: Optional[str] = None,  # What conditions the user sees
        force: bool = False,  # Override agent challenge
    ):
        self.action = action
        self.reasoning = reasoning
        self.conditions = conditions or ""
        self.force = force
        self.timestamp = datetime.now(timezone.utc).isoformat()


class ChallengeResponse:
    """Agent's pushback when it disagrees with a training instruction."""

    def __init__(
        self,
        agrees: bool,
        confidence: float,
        reasoning: str,
        conflicting_cxus: List[Dict[str, str]],
        recommendation: str,
    ):
        self.agrees = agrees
        self.confidence = confidence
        self.reasoning = reasoning
        self.conflicting_cxus = conflicting_cxus
        self.recommendation = recommendation

    def to_dict(self) -> dict:
        return {
            "agrees": self.agrees,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "conflictingCxus": self.conflicting_cxus,
            "recommendation": self.recommendation,
        }


class Trainer(BaseAgent):
    AGENT_ID = "trainer"
    AGENT_NAME = "Trainer"

    def __init__(self, config: dict, cxu_store: CxUStore):
        super().__init__(config)
        self.cxu_store = cxu_store
        self._pending_learnings: Dict[str, dict] = {}  # trade_id → context snapshot

    async def evaluate_instruction(
        self,
        instruction: TrainingInstruction,
        mark_price: float,
        regime: str,
        indicators: Dict[str, Any],
        signal_consensus: Dict[str, Any],
        position: Dict[str, Any],
    ) -> ChallengeResponse:
        """Evaluate a manual instruction against existing CxUs.

        Returns a ChallengeResponse. If the agent disagrees, it explains why
        with specific CxU citations. The user can then force-override or accept.
        """
        conflicts = []
        confidence_to_agree = 1.0

        # Check against axioms
        action = instruction.action.lower()

        # Fee check
        fee_cxu = self.cxu_store.by_alias("axiom-fee-kill")
        if fee_cxu and action in ("buy", "sell"):
            # Can't check exact edge without target, but flag the concern
            conflicts.append({
                "cxu": fee_cxu.to_citation(),
                "concern": "Ensure minimum $13 edge available (round-trip fee cost)",
                "severity": "warning",
            })

        # Hold default check
        hold_cxu = self.cxu_store.by_alias("axiom-hold-default")
        if hold_cxu and action in ("buy", "sell"):
            # Not a hard conflict, just a reminder
            pass

        # Regime-playbook alignment
        playbook = self.cxu_store.get_playbook_for_regime(regime)
        if playbook and action in ("buy", "sell"):
            # Check consensus threshold
            threshold = playbook.param_value("consensusThresholdPct", 75)
            consensus_pct = signal_consensus.get("agreementPct", 0)
            consensus_dir = signal_consensus.get("direction", "NEUTRAL")

            if consensus_pct < threshold:
                conflicts.append({
                    "cxu": playbook.to_citation(),
                    "concern": f"Signal consensus at {consensus_pct:.0f}% is below {threshold}% threshold for {regime} regime",
                    "severity": "caution",
                })
                confidence_to_agree -= 0.2

            # Check direction alignment
            if action == "buy" and consensus_dir == "SHORT":
                conflicts.append({
                    "cxu": playbook.to_citation(),
                    "concern": f"You want to buy but signal consensus is SHORT ({consensus_pct:.0f}%)",
                    "severity": "caution",
                })
                confidence_to_agree -= 0.15
            elif action == "sell" and consensus_dir == "LONG":
                conflicts.append({
                    "cxu": playbook.to_citation(),
                    "concern": f"You want to sell but signal consensus is LONG ({consensus_pct:.0f}%)",
                    "severity": "caution",
                })
                confidence_to_agree -= 0.15

            # Check max trades per day
            max_trades = playbook.param_value("maxTradesPerDay", 3)
            # TODO: count today's trades

            # Regime-specific checks
            if playbook.alias == "playbook-ranging":
                bb_pos = indicators.get("bollingerPosition", 50)
                entry_low = playbook.param_value("entryLowPct", 15)
                entry_high = playbook.param_value("entryHighPct", 85)

                if action == "buy" and bb_pos > entry_low:
                    conflicts.append({
                        "cxu": playbook.to_citation(),
                        "concern": f"Bollinger position at {bb_pos:.0f}% — ranging playbook says buy below {entry_low}%",
                        "severity": "concern",
                    })
                    confidence_to_agree -= 0.25
                elif action == "sell" and bb_pos < entry_high:
                    conflicts.append({
                        "cxu": playbook.to_citation(),
                        "concern": f"Bollinger position at {bb_pos:.0f}% — ranging playbook says sell above {entry_high}%",
                        "severity": "concern",
                    })
                    confidence_to_agree -= 0.25

        # Signal direction broken axiom
        sig_broken_cxu = self.cxu_store.by_alias("axiom-signal-direction-broken")
        if sig_broken_cxu and action in ("buy", "sell"):
            # Remind that signals are coin flips for direction
            if "signal" in instruction.reasoning.lower():
                conflicts.append({
                    "cxu": sig_broken_cxu.to_citation(),
                    "concern": "Signal direction is ~50% accurate. Are you using price action to confirm?",
                    "severity": "info",
                })

        # Max size axiom
        size_cxu = self.cxu_store.by_alias("axiom-max-size-or-skip")
        if size_cxu and action in ("buy", "sell"):
            # Just a reminder to use max size
            pass

        # Use LLM for nuanced challenge if there are concerns
        agrees = confidence_to_agree > 0.6 or len([c for c in conflicts if c["severity"] in ("concern", "caution")]) == 0
        conflicting_citations = [c["cxu"] for c in conflicts]

        if not agrees and not instruction.force:
            # Build a proper challenge with LLM reasoning
            challenge = await self._build_challenge(
                instruction, mark_price, regime, indicators, signal_consensus, conflicts
            )
            if challenge:
                return challenge

        # Build response
        if agrees:
            reasoning = f"Instruction aligns with CxU knowledge. {len(conflicts)} minor notes."
            rec = f"Proceed with {action}."
        else:
            concern_text = "; ".join(c["concern"] for c in conflicts if c["severity"] in ("concern", "caution"))
            reasoning = f"CxU concerns: {concern_text}"
            rec = "Consider holding. Use 'force' to override."

        return ChallengeResponse(
            agrees=agrees,
            confidence=max(0, confidence_to_agree),
            reasoning=reasoning,
            conflicting_cxus=conflicting_citations,
            recommendation=rec,
        )

    async def _build_challenge(
        self,
        instruction: TrainingInstruction,
        mark_price: float,
        regime: str,
        indicators: Dict[str, Any],
        signal_consensus: Dict[str, Any],
        conflicts: List[dict],
    ) -> Optional[ChallengeResponse]:
        """Use LLM to build a nuanced challenge explanation."""
        axiom_context = "\n".join(c.to_prompt_context() for c in self.cxu_store.axioms)
        playbook = self.cxu_store.get_playbook_for_regime(regime)
        playbook_context = playbook.to_prompt_context() if playbook else "No playbook loaded"

        conflict_text = "\n".join(
            f"- [{c['severity']}] {c['concern']} (CxU: {c['cxu'].get('alias', '?')})"
            for c in conflicts
        )

        system = f"""You are a trading mentor reviewing a manual trade instruction.
Your knowledge:
{axiom_context}

Active playbook:
{playbook_context}

Respond with JSON:
{{
  "agrees": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "concise explanation of agreement or disagreement, citing CxUs",
  "recommendation": "what you think the trader should do instead (or confirmation)"
}}"""

        user = f"""The trader wants to: {instruction.action.upper()}
Their reasoning: {instruction.reasoning}
{f'Conditions they see: {instruction.conditions}' if instruction.conditions else ''}

Current market:
- Price: ${mark_price:,.2f}
- Regime: {regime}
- Trend: {indicators.get('trendPct', 0):.4f}%
- Bollinger: {indicators.get('bollingerPosition', 50):.0f}%
- Signal consensus: {signal_consensus.get('agreementPct', 0):.0f}% {signal_consensus.get('direction', 'NEUTRAL')}

CxU concerns flagged:
{conflict_text}"""

        result = await self.call_llm(system, user)
        if not result:
            return None

        result.pop("_metrics", None)
        return ChallengeResponse(
            agrees=result.get("agrees", False),
            confidence=result.get("confidence", 0.5),
            reasoning=result.get("reasoning", ""),
            conflicting_cxus=[c["cxu"] for c in conflicts],
            recommendation=result.get("recommendation", ""),
        )

    def create_training_cxu(
        self,
        instruction: TrainingInstruction,
        mark_price: float,
        regime: str,
        indicators: Dict[str, Any],
        signal_consensus: Dict[str, Any],
        outcome: Optional[Dict[str, Any]] = None,
    ) -> CxU:
        """Create a learning CxU from a manual training instruction.

        This is how the agent learns from human expertise.
        """
        action = instruction.action.lower()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        alias = f"training-{action}-{regime}-{ts}"

        # Build claim from instruction context
        bb_pos = indicators.get("bollingerPosition", 50)
        trend = indicators.get("trendPct", 0)
        consensus = signal_consensus.get("agreementPct", 0)
        consensus_dir = signal_consensus.get("direction", "NEUTRAL")

        claim = (
            f"In a {regime} regime at price ${mark_price:.2f} with Bollinger at {bb_pos:.0f} percent "
            f"and trend at {trend:.3f} percent the human trader instructed {action} because "
            f"{instruction.reasoning}"
        )

        supporting = [
            {
                "text": (
                    f"Manual training instruction at {instruction.timestamp}. "
                    f"Market: {regime} regime, ${mark_price:.2f}, BB={bb_pos:.0f}%, "
                    f"trend={trend:.3f}%, consensus={consensus:.0f}% {consensus_dir}. "
                    f"Conditions observed: {instruction.conditions or 'not specified'}."
                ),
                "line": None,
            }
        ]

        if outcome:
            pnl = outcome.get("pnl", 0)
            result_text = "profitable" if pnl > 0 else "unprofitable"
            supporting.append({
                "text": f"Trade outcome: {result_text}, P&L=${pnl:.2f}, fee=${outcome.get('fee', 0):.2f}",
                "line": None,
            })

        keywords = [action, regime, "training", "manual"]
        if instruction.conditions:
            keywords.extend(w.lower() for w in instruction.conditions.split()[:5])

        cxu = self.cxu_store.create_cxu(
            alias=alias,
            claim=claim,
            supporting_contexts=supporting,
            knowledge_type="derived",
            claim_type="observation",
            tier="learning",
            parameters={
                "regime": {"value": regime, "description": "Regime when instruction was given"},
                "action": {"value": action, "description": "Instructed action"},
                "bollingerPosition": {"value": round(bb_pos, 1), "min": 0, "max": 100, "step": 1, "description": "BB position at time of instruction"},
                "trendPct": {"value": round(trend, 4), "min": -5, "max": 5, "step": 0.01, "description": "Trend % at time of instruction"},
            },
            keywords=keywords,
            created_by="human-trainer",
        )

        logger.info("Created training CxU: %s", alias)
        return cxu

    def record_pending_outcome(self, trade_id: str, context: dict):
        """Record context for a pending trade so we can update the CxU on close."""
        self._pending_learnings[trade_id] = context

    def resolve_pending_outcome(self, trade_id: str, outcome: dict) -> Optional[CxU]:
        """When a training trade closes, update its learning CxU with outcome."""
        context = self._pending_learnings.pop(trade_id, None)
        if not context:
            return None

        alias = context.get("cxu_alias")
        if not alias:
            return None

        pnl = outcome.get("pnl", 0)
        fee = outcome.get("fee", 0)

        # Update the CxU with outcome data
        return self.cxu_store.update_cxu(
            alias=alias,
            param_updates={},  # No param changes, but we update the version
            change_description=f"Outcome: P&L=${pnl:.2f}, fee=${fee:.2f}, {'win' if pnl > 0 else 'loss'}",
            modified_by="outcome-tracker",
        )
