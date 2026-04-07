"""Signal Assessor — evaluates incoming signals against CxU-stored quality ratings.

Hybrid agent: deterministic blocklist + consensus calculation, with optional
LLM for nuanced assessment when consensus is near the threshold.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.base import AgentOutput, BaseAgent
from cxu_store import CxU, CxUStore

logger = logging.getLogger("agents.signal_assessor")


class SignalAssessor(BaseAgent):
    AGENT_ID = "signal-assessor"
    AGENT_NAME = "Signal Assessor"

    def __init__(self, config: dict, cxu_store: CxUStore):
        super().__init__(config)
        self.cxu_store = cxu_store

    async def assess(
        self,
        predictions: List[Dict[str, Any]],
        purchased_signals: List[Dict[str, Any]],
        regime: str,
        mark_price: float,
    ) -> AgentOutput:
        """Assess signal quality and consensus.

        Args:
            predictions: Active predictions from direct signal feed
            purchased_signals: Purchased signals from AGDEL marketplace
            regime: Current regime classification
            mark_price: Current ETH mark price
        """
        # Load relevant CxUs
        accuracy_cxu = self.cxu_store.by_alias("learning-signal-accuracy-by-type")
        playbook = self.cxu_store.get_playbook_for_regime(regime)

        citations = []
        if accuracy_cxu:
            citations.append(accuracy_cxu.to_citation())
        if playbook:
            citations.append(playbook.to_citation())

        # Get blocklist from learning CxU
        blocked_types = set()
        if accuracy_cxu:
            blocked_str = accuracy_cxu.param_value("blockedSignalTypes", "")
            blocked_types = set(blocked_str.split(",")) if blocked_str else set()

        # Get consensus threshold from playbook
        consensus_threshold = 75
        if playbook:
            consensus_threshold = playbook.param_value("consensusThresholdPct", 75)

        # Filter and assess predictions
        all_signals = []

        # Direct feed signals
        for pred in predictions:
            sig_type = pred.get("signal_type") or pred.get("type") or pred.get("agent", "")
            if sig_type in blocked_types:
                continue
            all_signals.append({
                "source": "direct",
                "signalType": sig_type,
                "horizon": pred.get("horizon", "5m"),
                "direction": self._extract_direction(pred, mark_price),
                "confidence": pred.get("confidence", 0.5),
                "confCalib": pred.get("confCalib", pred.get("confidence", 0.5)),
                "targetPrice": pred.get("targetPrice") or pred.get("target_price"),
            })

        # AGDEL purchased signals
        for sig in purchased_signals:
            sig_type = sig.get("signalType") or sig.get("signal_type") or sig.get("type", "")
            if sig_type in blocked_types:
                continue
            all_signals.append({
                "source": "agdel",
                "signalType": sig_type,
                "horizon": sig.get("horizon", "5m"),
                "direction": sig.get("direction", "NEUTRAL"),
                "confidence": sig.get("confidence", 0.5),
                "confCalib": sig.get("confCalib", sig.get("confidence", 0.5)),
                "targetPrice": sig.get("targetPrice") or sig.get("target_price"),
            })

        if not all_signals:
            return self._make_output(
                data={
                    "summary": "No active signals after filtering",
                    "consensus": {"direction": "NEUTRAL", "agreementPct": 0, "meetsThreshold": False, "threshold": consensus_threshold},
                    "signalQuality": [],
                    "blockedSignals": list(blocked_types),
                    "signalCount": {"direct": len(predictions), "agdel": len(purchased_signals), "afterFilter": 0},
                    "recommendation": "hold — no signals to assess",
                },
                citations=citations,
                reasoning="All signals blocked or none available",
            )

        # Compute consensus
        long_count = sum(1 for s in all_signals if s["direction"] == "LONG")
        short_count = sum(1 for s in all_signals if s["direction"] == "SHORT")
        total_directional = long_count + short_count

        if total_directional > 0:
            if long_count >= short_count:
                consensus_dir = "LONG"
                agreement_pct = (long_count / total_directional) * 100
            else:
                consensus_dir = "SHORT"
                agreement_pct = (short_count / total_directional) * 100
        else:
            consensus_dir = "NEUTRAL"
            agreement_pct = 0

        meets_threshold = agreement_pct >= consensus_threshold

        # Signal quality breakdown by type
        type_quality = {}
        for s in all_signals:
            st = s["signalType"]
            if st not in type_quality:
                type_quality[st] = {"long": 0, "short": 0, "neutral": 0, "total_conf": 0, "count": 0}
            d = s["direction"].lower()
            if d in type_quality[st]:
                type_quality[st][d] += 1
            type_quality[st]["total_conf"] += s["confidence"]
            type_quality[st]["count"] += 1

        signal_quality = []
        for st, q in type_quality.items():
            dominant = "LONG" if q["long"] > q["short"] else "SHORT" if q["short"] > q["long"] else "NEUTRAL"
            signal_quality.append({
                "signalType": st,
                "direction": dominant,
                "count": q["count"],
                "avgConfidence": round(q["total_conf"] / q["count"], 3) if q["count"] else 0,
                "agreesWithConsensus": dominant == consensus_dir,
            })

        # Build recommendation
        if not meets_threshold:
            recommendation = f"hold — consensus {agreement_pct:.0f}% below {consensus_threshold}% threshold for {regime}"
        elif agreement_pct >= 90:
            recommendation = f"strong {consensus_dir.lower()} — {agreement_pct:.0f}% consensus exceeds threshold"
        else:
            recommendation = f"moderate {consensus_dir.lower()} — {agreement_pct:.0f}% consensus meets threshold"

        return self._make_output(
            data={
                "summary": f"{len(all_signals)} signals ({len(predictions)} direct, {len(purchased_signals)} AGDEL). "
                           f"Consensus: {agreement_pct:.0f}% {consensus_dir}.",
                "consensus": {
                    "direction": consensus_dir,
                    "agreementPct": round(agreement_pct, 1),
                    "meetsThreshold": meets_threshold,
                    "threshold": consensus_threshold,
                },
                "signalQuality": signal_quality,
                "blockedSignals": list(blocked_types),
                "signalCount": {
                    "direct": len(predictions),
                    "agdel": len(purchased_signals),
                    "afterFilter": len(all_signals),
                },
                "recommendation": recommendation,
            },
            citations=citations,
            reasoning=recommendation,
        )

    def _extract_direction(self, pred: dict, mark_price: float) -> str:
        """Extract direction from a prediction."""
        direction = pred.get("direction", "")
        if direction in ("LONG", "SHORT", "NEUTRAL"):
            return direction

        # Infer from target price
        target = pred.get("targetPrice") or pred.get("target_price")
        if target and mark_price:
            if target > mark_price * 1.001:
                return "LONG"
            elif target < mark_price * 0.999:
                return "SHORT"
        return "NEUTRAL"
