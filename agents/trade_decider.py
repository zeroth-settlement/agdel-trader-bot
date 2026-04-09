"""Trade Decider — the core decision maker.

Assembles axiom + playbook + signal assessment CxUs into a trade decision.
Every decision must cite at least one CxU. The LLM's job is to reason about
whether the current setup meets the CxU-defined criteria.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.base import AgentOutput, BaseAgent
from cxu_store import CxU, CxUStore

logger = logging.getLogger("agents.trade_decider")

VALID_ACTIONS = {"open_long", "open_short", "close", "hold"}


class TradeDecider(BaseAgent):
    AGENT_ID = "trade-decider"
    AGENT_NAME = "Trade Decider"

    def __init__(self, config: dict, cxu_store: CxUStore):
        super().__init__(config)
        self.cxu_store = cxu_store

    async def decide(
        self,
        regime_output: AgentOutput,
        signal_output: AgentOutput,
        position: Dict[str, Any],
        portfolio: Dict[str, Any],
        risk_levels: Dict[str, Any],
        recent_trades: List[Dict[str, Any]],
        mark_price: float,
    ) -> AgentOutput:
        """Make a trade decision based on CxU-assembled context.

        This is the only agent that calls the LLM on every decision cycle,
        because trade decisions require nuanced reasoning.
        """
        # Collect CxUs for the decision
        axioms = self.cxu_store.axioms
        regime = regime_output.data.get("regime", "unknown")
        playbook = self.cxu_store.get_playbook_for_regime(regime)
        learnings = self.cxu_store.learnings

        all_cxus = axioms + ([playbook] if playbook else []) + learnings
        cxu_context = "\n\n".join(c.to_prompt_context() for c in all_cxus)

        # Build the system prompt from CxUs
        system = f"""You are a CxU-driven ETH perpetuals trade decision engine.

YOUR KNOWLEDGE BASE (these CxUs define your strategy — cite them):
{cxu_context}

RULES:
1. Every decision MUST cite at least one CxU by alias.
2. It is better to be in the market than out — per conviction-hold, once a position is entered on a valid thesis, hold through chop until target+fees unless the thesis is invalidated or safety stop is hit.
3. Only enter when the setup clearly meets the active playbook criteria.
4. CRITICAL FEE CHECK — per hyperliquid-fees, compute round-trip fee as 2 × takerFeePct × notional. Expected profit MUST exceed 2x the round-trip fee. If not, the answer is HOLD. Most of the time the answer should be HOLD.
5. Size based on conviction — per position-sizing, scale position size with conviction level. On autopilot (no human monitoring), use low leverage (2-3x max).
6. Build conviction from signals — per agdel-signal-scoring, interpret quality scores. Need strong consensus before entry.
7. Do NOT close a position just because it is temporarily underwater. Only close if: the regime has changed, signals have flipped against the thesis, or the safety stop is breached.
8. REGIME STABILITY — per learning-regime-flip-entry-block, do NOT enter within 5 minutes of a regime transition. If the regime just changed, HOLD and wait for stability.
9. FEE CIRCUIT BREAKER — per learning-fee-budget-circuit-breaker, if recent trades show $50+ in fees with zero P&L, block all entries for 30 minutes.
10. TRADE LESS — the biggest edge is NOT trading. 1-2 trades per day is better than 10. Every trade costs fees. Only enter with high conviction and a clear edge that exceeds fees by 2x or more.

Respond with JSON:
{{
  "action": "hold | open_long | open_short | close",
  "sizePct": 0-100,
  "confidence": 0.0-1.0,
  "reasoning": "explanation citing [CxU aliases]",
  "feeCheck": {{
    "estimatedEdge": dollar_amount,
    "minimumEdge": 13,
    "passesCheck": true/false
  }},
  "citations": [
    {{"cxu_id": "...", "alias": "..."}}
  ]
}}"""

        # Build user prompt with current market state
        regime_data = regime_output.data
        signal_data = signal_output.data
        consensus = signal_data.get("consensus", {})

        pos_side = position.get("side", "FLAT")
        pos_size = position.get("size", 0)
        equity = portfolio.get("equity", 0)
        pnl = portfolio.get("pnl", 0)
        unrealized = position.get("unrealizedPnl", 0)

        # Recent trade summary
        recent_summary = "No recent trades."
        if recent_trades:
            wins = sum(1 for t in recent_trades[-10:] if (t.get("pnl") or 0) > 0)
            losses = sum(1 for t in recent_trades[-10:] if (t.get("pnl") or 0) < 0)
            total_pnl = sum(t.get("pnl", 0) for t in recent_trades[-10:])
            total_fees = sum(t.get("fee", 0) for t in recent_trades[-10:])
            recent_summary = (
                f"Last {len(recent_trades[-10:])} trades: {wins}W/{losses}L, "
                f"net P&L: ${total_pnl:.2f}, fees: ${total_fees:.2f}"
            )

        # Playbook-specific criteria
        playbook_status = "No playbook loaded."
        if playbook:
            max_trades = playbook.param_value("maxTradesPerDay", 3)
            today_trades = sum(1 for t in recent_trades if self._is_today(t.get("timestamp")))
            playbook_status = (
                f"Active playbook: {playbook.alias} (regime: {regime})\n"
                f"  Trades today: {today_trades}/{max_trades}"
            )
            if playbook.alias == "playbook-ranging":
                entry_low = playbook.param_value("entryLowPct", 15)
                entry_high = playbook.param_value("entryHighPct", 85)
                bb_pos = regime_data.get("indicators", {}).get("bollingerPosition", 50)
                playbook_status += (
                    f"\n  Bollinger position: {bb_pos:.0f}% "
                    f"(entry zones: <{entry_low}% for long, >{entry_high}% for short)"
                )

        user = f"""## Current Market
Mark Price: ${mark_price:,.2f}
Regime: {regime} (confidence: {regime_data.get('confidence', 0):.0%})
Trend: {regime_data.get('indicators', {}).get('trendPct', 0):.4f}%

## Position
Side: {pos_side}
Size: {pos_size} ETH
Equity: ${equity:,.2f}
Unrealized P&L: ${unrealized:,.2f}
Net P&L: ${pnl:,.2f}

## Signal Assessment
{signal_data.get('summary', 'No signals')}
Consensus: {consensus.get('agreementPct', 0):.0f}% {consensus.get('direction', 'NEUTRAL')}
Meets threshold: {consensus.get('meetsThreshold', False)}
Recommendation: {signal_data.get('recommendation', 'none')}

## Risk Levels
{self._format_risk(risk_levels)}

## Recent Performance
{recent_summary}

## Playbook
{playbook_status}"""

        result = await self.call_llm(system, user)

        if not result:
            # Default to hold on LLM failure
            hold_cxu = self.cxu_store.by_alias("conviction-hold")
            return self._make_output(
                data={
                    "action": "hold",
                    "sizePct": 0,
                    "confidence": 0.5,
                    "feeCheck": {"estimatedEdge": 0, "minimumEdge": 13, "passesCheck": False},
                },
                citations=[hold_cxu.to_citation()] if hold_cxu else [],
                reasoning="LLM failed — defaulting to hold per conviction-hold",
            )

        metrics = result.pop("_metrics", {})

        # Validate action
        action = result.get("action", "hold")
        if action not in VALID_ACTIONS:
            action = "hold"

        # Validate citations
        raw_citations = result.get("citations", [])
        validated_citations = []
        for c in raw_citations:
            alias = c.get("alias", "")
            cxu = self.cxu_store.by_alias(alias) or self.cxu_store.by_id(c.get("cxu_id", ""))
            if cxu:
                validated_citations.append(cxu.to_citation())

        # Ensure at least one citation
        if not validated_citations:
            hold_cxu = self.cxu_store.by_alias("conviction-hold")
            if hold_cxu:
                validated_citations.append(hold_cxu.to_citation())

        # Add regime and signal citations
        for c in regime_output.citations + signal_output.citations:
            if c not in validated_citations:
                validated_citations.append(c)

        return self._make_output(
            data={
                "action": action,
                "sizePct": result.get("sizePct", 0),
                "confidence": result.get("confidence", 0.5),
                "reasoning": result.get("reasoning", ""),
                "feeCheck": result.get("feeCheck", {}),
            },
            citations=validated_citations,
            reasoning=result.get("reasoning", ""),
            metrics=metrics,
        )

    def _format_risk(self, risk: dict) -> str:
        if not risk:
            return "No open position"
        parts = []
        if risk.get("slPrice"):
            parts.append(f"Stop Loss: ${risk['slPrice']:.2f} ({risk.get('slMode', 'fixed')})")
        if risk.get("tpPrice"):
            parts.append(f"Take Profit: ${risk['tpPrice']:.2f}")
        if risk.get("cooldownRemaining", 0) > 0:
            parts.append(f"Cooldown: {risk['cooldownRemaining']}s remaining")
        return "\n".join(parts) if parts else "No risk levels set"

    def _is_today(self, timestamp) -> bool:
        if not timestamp:
            return False
        from datetime import datetime, timezone
        try:
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            return dt.date() == now.date()
        except Exception:
            return False
