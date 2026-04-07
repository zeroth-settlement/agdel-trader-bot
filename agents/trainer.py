"""Trainer — handles manual training mode.

When the user provides an observation or trade instruction, the trainer:
1. Finds the most relevant existing CxU(s) in the knowledge base
2. Uses the LLM to decide: update existing CxU (strengthen/weaken) or create new
3. If updating: adds supporting context, adjusts confidence/parameters
4. If creating: only when a genuinely new hypothesis has no existing CxU to attach to
5. Challenges the user when an instruction conflicts with existing CxUs

CxUs are living documents — observations strengthen or weaken them over time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agents.base import AgentOutput, BaseAgent
from cxu_store import CxU, CxUStore

logger = logging.getLogger("agents.trainer")


class TrainingInstruction:
    """A manual trading instruction or observation from the user."""

    def __init__(
        self,
        action: str,  # "buy", "sell", "close", "observe-long", "observe-short", "observe-flat"
        reasoning: str,
        conditions: Optional[str] = None,
        force: bool = False,
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
        self._pending_learnings: Dict[str, dict] = {}

    async def process_observation(
        self,
        reasoning: str,
        mark_price: float,
        regime: str,
        indicators: Dict[str, Any],
        signal_consensus: Dict[str, Any],
        position: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Process a human observation and integrate it into the knowledge base.

        This is the core learning method. It uses the LLM to:
        1. Find which existing CxU(s) this observation relates to
        2. Decide whether to update an existing CxU or create a new one
        3. Execute the change

        Returns a dict with what was done.
        """
        # Build context of all current CxUs
        all_cxus = self.cxu_store.all()
        cxu_summaries = "\n".join(
            f"- [{c.tier}] {c.alias}: {c.claim[:120]}..."
            for c in all_cxus
        )

        pos_side = position.get("side", "FLAT")
        bb_pos = indicators.get("bollingerPosition", 50)
        trend = indicators.get("trendPct", 0)
        consensus_pct = signal_consensus.get("agreementPct", 0)
        consensus_dir = signal_consensus.get("direction", "NEUTRAL")

        system = f"""You are a knowledge base curator for a trading agent. The human trader has made an observation. Your job is to integrate this observation into the existing CxU knowledge base.

EXISTING CxUs:
{cxu_summaries}

RULES:
1. PREFER updating an existing CxU over creating a new one.
2. To UPDATE: add the observation as a new supporting context that strengthens or weakens the CxU's claim. You can adjust parameters within their bounds.
3. To CREATE: only when the observation represents a genuinely new hypothesis that no existing CxU covers. This should be rare.
4. An observation can relate to multiple CxUs — update the most relevant one.
5. If the observation contradicts an axiom (tier:axiom), note this but do NOT modify the axiom. Flag it for awareness.
6. Keep the knowledge base lean — don't create CxUs for one-off observations. Wait for patterns.

Respond with JSON:
{{
  "action": "update" | "create" | "note",
  "targetCxuAlias": "alias of CxU to update (for update action)",
  "newSupportingContext": "text to add as supporting evidence (for update action)",
  "parameterUpdates": {{"paramName": newValue}} or null,
  "changeDescription": "brief description of what changed and why",
  "newCxuAlias": "alias for new CxU (for create action only)",
  "newCxuClaim": "claim text (for create action only)",
  "newCxuTier": "playbook or learning (for create action only)",
  "reasoning": "why you chose this action over alternatives"
}}

"note" means the observation is interesting but doesn't warrant a CxU change yet — log it for future reference."""

        user = f"""## Human Observation
"{reasoning}"

## Market Context at Time of Observation
- Price: ${mark_price:,.2f}
- Regime: {regime}
- Position: {pos_side}
- Bollinger: {bb_pos:.0f}%
- Trend: {trend:.4f}%
- Signal consensus: {consensus_pct:.0f}% {consensus_dir}"""

        result = await self.call_llm(system, user)

        if not result:
            return {"action": "error", "error": "LLM call failed"}

        result.pop("_metrics", None)
        action = result.get("action", "note")

        if action == "update":
            alias = result.get("targetCxuAlias", "")
            cxu = self.cxu_store.by_alias(alias)
            if not cxu:
                return {"action": "error", "error": f"CxU '{alias}' not found"}
            if cxu.is_human_locked:
                return {
                    "action": "flagged",
                    "reasoning": f"Observation relates to human-locked CxU '{alias}'. Noted but not modified.",
                    "cxuAlias": alias,
                }

            # Update the CxU
            param_updates = result.get("parameterUpdates") or {}
            updated = self.cxu_store.update_cxu(
                alias=alias,
                param_updates=param_updates,
                change_description=result.get("changeDescription", f"Training observation: {reasoning[:80]}"),
                modified_by="human-trainer",
            )

            # Add supporting context by rewriting the CxU with the new context appended
            new_context = result.get("newSupportingContext", "")
            if updated and new_context:
                self._add_supporting_context(updated, new_context, mark_price, regime, indicators)

            logger.info("Training: updated CxU '%s' — %s", alias, result.get("changeDescription", ""))
            return {
                "action": "updated",
                "cxuAlias": alias,
                "changeDescription": result.get("changeDescription", ""),
                "reasoning": result.get("reasoning", ""),
                "cxu": {"alias": alias, "claim": cxu.claim[:150]},
            }

        elif action == "create":
            new_alias = result.get("newCxuAlias", "")
            new_claim = result.get("newCxuClaim", "")
            new_tier = result.get("newCxuTier", "learning")

            if not new_alias or not new_claim:
                return {"action": "error", "error": "LLM proposed create but missing alias or claim"}

            context_text = (
                f"Human observation at {datetime.now(timezone.utc).isoformat()}: {reasoning}. "
                f"Market context: {regime} regime, ${mark_price:.2f}, BB={bb_pos:.0f}%, "
                f"trend={trend:.4f}%, position={pos_side}."
            )

            new_cxu = self.cxu_store.create_cxu(
                alias=new_alias,
                claim=new_claim,
                supporting_contexts=[{"text": context_text, "line": None}],
                knowledge_type="derived",
                claim_type="hypothesis",
                tier=new_tier,
                created_by="human-trainer",
            )

            logger.info("Training: created new CxU '%s'", new_alias)
            return {
                "action": "created",
                "cxuAlias": new_alias,
                "changeDescription": result.get("changeDescription", ""),
                "reasoning": result.get("reasoning", ""),
                "cxu": {"alias": new_alias, "claim": new_claim[:150]},
            }

        else:
            # "note" — observation logged but no CxU change
            logger.info("Training: observation noted — %s", result.get("reasoning", ""))
            return {
                "action": "noted",
                "reasoning": result.get("reasoning", "No CxU change warranted yet."),
            }

    def _add_supporting_context(self, cxu: CxU, context_text: str, mark_price: float, regime: str, indicators: Dict):
        """Add a supporting context entry to an existing CxU file on disk."""
        import json
        filepath = self.cxu_store.cxus_dir / f"{cxu.alias}.json"
        if not filepath.exists():
            return
        with open(filepath) as f:
            data = json.load(f)

        contexts = data.get("cxu_object", {}).get("supporting_contexts", [])
        contexts.append({
            "text": context_text,
            "line": None,
        })
        data["cxu_object"]["supporting_contexts"] = contexts

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    async def evaluate_instruction(
        self,
        instruction: TrainingInstruction,
        mark_price: float,
        regime: str,
        indicators: Dict[str, Any],
        signal_consensus: Dict[str, Any],
        position: Dict[str, Any],
    ) -> ChallengeResponse:
        """Evaluate a manual trade instruction against existing CxUs."""
        conflicts = []
        confidence_to_agree = 1.0

        action = instruction.action.lower()

        # Fee check
        fee_cxu = self.cxu_store.by_alias("hyperliquid-fees")
        if fee_cxu and action in ("buy", "sell"):
            conflicts.append({
                "cxu": fee_cxu.to_citation(),
                "concern": "Ensure expected profit exceeds round-trip fee (2 × 0.045% taker at Tier 0)",
                "severity": "warning",
            })

        # Regime-playbook alignment
        playbook = self.cxu_store.get_playbook_for_regime(regime)
        if playbook and action in ("buy", "sell"):
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

        # Signal interpretation check
        sig_cxu = self.cxu_store.by_alias("agdel-signal-scoring")
        if sig_cxu and action in ("buy", "sell"):
            if "signal" in instruction.reasoning.lower():
                conflicts.append({
                    "cxu": sig_cxu.to_citation(),
                    "concern": "High conviction entries should be confirmed by AGDEL purchased signals with quality scores. Are you relying on direct feed only?",
                    "severity": "info",
                })

        agrees = confidence_to_agree > 0.6 or len([c for c in conflicts if c["severity"] in ("concern", "caution")]) == 0

        if not agrees and not instruction.force:
            challenge = await self._build_challenge(
                instruction, mark_price, regime, indicators, signal_consensus, conflicts
            )
            if challenge:
                return challenge

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
            conflicting_cxus=[c["cxu"] for c in conflicts],
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
    ) -> CxU:
        """Create a learning CxU from a manual training instruction."""
        bb_pos = indicators.get("bollingerPosition", 50)
        trend = indicators.get("trendPct", 0)
        consensus_pct = signal_consensus.get("agreementPct", 0)
        consensus_dir = signal_consensus.get("direction", "NEUTRAL")

        alias = f"training-{instruction.action}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        claim = (
            f"Human trader executed {instruction.action} at ${mark_price:,.2f} in {regime} regime. "
            f"Reasoning: {instruction.reasoning}"
        )
        context_text = (
            f"Manual {instruction.action} at {instruction.timestamp}. "
            f"Price: ${mark_price:,.2f}, regime: {regime}, BB: {bb_pos:.0f}%, "
            f"trend: {trend:.4f}%, signal consensus: {consensus_pct:.0f}% {consensus_dir}. "
            f"Conditions: {instruction.conditions or 'none stated'}."
        )

        return self.cxu_store.create_cxu(
            alias=alias,
            claim=claim,
            supporting_contexts=[{"text": context_text, "line": None}],
            knowledge_type="derived",
            claim_type="hypothesis",
            tier="learning",
            created_by="human-trainer",
        )

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

        return self.cxu_store.update_cxu(
            alias=alias,
            param_updates={},
            change_description=f"Outcome: P&L=${pnl:.2f}, fee=${fee:.2f}, {'win' if pnl > 0 else 'loss'}",
            modified_by="outcome-tracker",
        )
