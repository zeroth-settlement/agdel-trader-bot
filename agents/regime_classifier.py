"""Regime Classifier — identifies current market regime using CxU-defined criteria.

Uses a deterministic fast path when indicators are clear, falls back to LLM
only when the regime is ambiguous. This saves latency and cost.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any, Dict, List, Optional

from agents.base import AgentOutput, BaseAgent
from cxu_store import CxU, CxUStore

logger = logging.getLogger("agents.regime")


class RegimeClassifier(BaseAgent):
    AGENT_ID = "regime-classifier"
    AGENT_NAME = "Regime Classifier"

    def __init__(self, config: dict, cxu_store: CxUStore):
        super().__init__(config)
        self.cxu_store = cxu_store

    async def classify(
        self,
        mark_price: float,
        recent_prices: List[float],
        tick_interval_s: float = 5.0,
    ) -> AgentOutput:
        """Classify current market regime.

        Args:
            mark_price: Current ETH mark price
            recent_prices: Last 360+ prices (30 min at 5s intervals)
            tick_interval_s: Seconds between ticks
        """
        regime_cxus = self.cxu_store.regime_models
        if not regime_cxus:
            return self._make_error("No regime model CxUs found")

        # Compute indicators
        indicators = self._compute_indicators(mark_price, recent_prices)

        # Deterministic fast path: clear regime match
        regime, confidence, matched_cxu = self._fast_classify(indicators, regime_cxus)

        if confidence >= 0.8:
            # Clear match — skip LLM
            return self._make_output(
                data={
                    "regime": regime,
                    "confidence": confidence,
                    "indicators": indicators,
                    "method": "deterministic",
                },
                citations=[matched_cxu.to_citation()],
                reasoning=f"Deterministic: {regime} (trend={indicators['trendPct']:.3f}%, "
                          f"bb_pos={indicators['bollingerPosition']:.0f}%)",
            )

        # Ambiguous — use LLM
        return await self._llm_classify(indicators, regime_cxus)

    def _compute_indicators(self, mark_price: float, prices: List[float]) -> Dict[str, Any]:
        """Compute regime classification indicators from price history."""
        if len(prices) < 10:
            return {
                "trendPct": 0.0,
                "bollingerPosition": 50,
                "volatilityExpansion": False,
                "sessionContext": self._session_context(),
                "priceCount": len(prices),
            }

        # Trend: % change over window
        window = min(len(prices), 360)  # ~30 min
        old_price = prices[-window]
        trend_pct = ((mark_price - old_price) / old_price) * 100 if old_price else 0

        # Bollinger position (where price sits in recent range)
        recent = prices[-60:]  # ~5 min
        p_min, p_max = min(recent), max(recent)
        bb_range = p_max - p_min
        bb_pos = ((mark_price - p_min) / bb_range * 100) if bb_range > 0 else 50

        # Volatility expansion (are bands widening?)
        if len(prices) >= 120:
            old_std = statistics.stdev(prices[-120:-60])
            new_std = statistics.stdev(prices[-60:])
            vol_expansion = new_std > old_std * 1.3
        else:
            vol_expansion = False

        # Higher highs / lower lows (trend quality)
        chunks = [prices[i:i+12] for i in range(max(0, len(prices)-60), len(prices), 12)]
        if len(chunks) >= 3:
            highs = [max(c) for c in chunks if c]
            lows = [min(c) for c in chunks if c]
            hh = all(highs[i] >= highs[i-1] for i in range(1, len(highs)))
            ll = all(lows[i] <= lows[i-1] for i in range(1, len(lows)))
        else:
            hh, ll = False, False

        return {
            "trendPct": round(trend_pct, 4),
            "bollingerPosition": round(bb_pos, 1),
            "volatilityExpansion": vol_expansion,
            "higherHighs": hh,
            "lowerLows": ll,
            "sessionContext": self._session_context(),
            "priceCount": len(prices),
        }

    def _fast_classify(
        self, indicators: Dict[str, Any], regime_cxus: List[CxU]
    ) -> tuple:
        """Deterministic regime classification when indicators are clear."""
        trend = abs(indicators["trendPct"])
        vol_exp = indicators["volatilityExpansion"]
        hh = indicators.get("higherHighs", False)
        ll = indicators.get("lowerLows", False)

        # Load thresholds from CxUs
        ranging_cxu = self.cxu_store.by_alias("regime-ranging")
        trending_cxu = self.cxu_store.by_alias("regime-trending")
        volatile_cxu = self.cxu_store.by_alias("regime-volatile")

        ranging_threshold = ranging_cxu.param_value("trendThresholdPct", 0.2) if ranging_cxu else 0.2
        trending_threshold = trending_cxu.param_value("trendThresholdPct", 0.2) if trending_cxu else 0.2

        # Volatile: high volatility expansion with no clear trend
        if vol_exp and trend < trending_threshold * 2:
            return ("volatile", 0.85, volatile_cxu or ranging_cxu)

        # Trending: clear directional movement
        if trend >= trending_threshold and (hh or ll):
            direction = "up" if indicators["trendPct"] > 0 else "down"
            return (f"trending_{direction}", 0.9, trending_cxu or ranging_cxu)

        if trend >= trending_threshold:
            direction = "up" if indicators["trendPct"] > 0 else "down"
            return (f"trending_{direction}", 0.75, trending_cxu or ranging_cxu)

        # Ranging: bounded price action
        if trend < ranging_threshold:
            return ("ranging", 0.85, ranging_cxu or regime_cxus[0])

        # Ambiguous
        return ("unknown", 0.5, regime_cxus[0])

    async def _llm_classify(
        self, indicators: Dict[str, Any], regime_cxus: List[CxU]
    ) -> AgentOutput:
        """LLM-based classification for ambiguous regimes."""
        cxu_context = "\n\n".join(c.to_prompt_context() for c in regime_cxus)

        system = f"""You are a market regime classifier for ETH-USD perpetuals.
Classify the current market regime using ONLY these CxU-defined regime models:

{cxu_context}

Respond with JSON:
{{
  "regime": "ranging | trending_up | trending_down | volatile",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation citing CxU aliases"
}}"""

        user = f"""Current market indicators:
- Trend: {indicators['trendPct']:.4f}%
- Bollinger position: {indicators['bollingerPosition']:.1f}%
- Volatility expansion: {indicators['volatilityExpansion']}
- Higher highs: {indicators.get('higherHighs', False)}
- Lower lows: {indicators.get('lowerLows', False)}
- Session: {indicators['sessionContext']}
- Price history points: {indicators['priceCount']}"""

        result = await self.call_llm(system, user)
        if not result:
            # Fallback to deterministic
            regime, conf, cxu = self._fast_classify(indicators, regime_cxus)
            return self._make_output(
                data={"regime": regime, "confidence": conf * 0.7, "indicators": indicators, "method": "fallback"},
                citations=[cxu.to_citation()],
                reasoning="LLM failed, using deterministic fallback",
            )

        metrics = result.pop("_metrics", {})
        regime = result.get("regime", "unknown")
        matched = self.cxu_store.by_alias(f"regime-{regime.split('_')[0]}")
        citations = [matched.to_citation()] if matched else []

        return self._make_output(
            data={**result, "indicators": indicators, "method": "llm"},
            citations=citations,
            reasoning=result.get("reasoning", ""),
            metrics=metrics,
        )

    def _session_context(self) -> str:
        """Determine current trading session."""
        from datetime import datetime, timezone
        hour = datetime.now(timezone.utc).hour
        if 0 <= hour < 8:
            return "asia"
        elif 8 <= hour < 14:
            return "europe"
        else:
            return "us"
