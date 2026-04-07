"""Market analyzer — pre-digests raw signals into a structured analysis for the LLM.

Instead of dumping 500 raw signals into the prompt, this module:
1. Classifies the market regime from signal metadata
2. Aggregates consensus by signal category (technical, microstructure, sentiment, etc.)
3. Identifies cross-validation and conflicts between categories
4. Tracks recent signal accuracy to learn which types to trust
5. Produces a concise market briefing the LLM can reason about
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


# Map signal types to categories for cross-validation
SIGNAL_CATEGORIES = {
    # Technical / price action
    "technical-signal": "technical",
    "momentum-signal": "technical",
    "mesa-signal": "technical",
    "bb-reversal-signal": "technical",
    "vwap-signal": "technical",
    # Microstructure
    "funding-signal": "microstructure",
    "oi-signal": "microstructure",
    "basis-signal": "microstructure",
    "market-fragility-signal": "microstructure",
    "liquidation-signal": "microstructure",
    # Sentiment
    "fear-greed-signal": "sentiment",
    "social-feed-signal": "sentiment",
    # Cross-asset / macro
    "cross-asset-signal": "macro",
    "crypto-breadth-signal": "macro",
    # Derivatives
    "options-skew-signal": "derivatives",
    "onchain-flow-signal": "onchain",
    # Regime / meta
    "regime-signal": "regime",
    "trend-exhaustion-signal": "regime",
}

HORIZON_WEIGHTS = {"1m": 0.3, "5m": 0.7, "15m": 1.0, "1h": 0.8, "60m": 0.8}


@dataclass
class CategoryConsensus:
    """Consensus for a single signal category."""
    category: str
    long_count: int = 0
    short_count: int = 0
    flat_count: int = 0
    total_cc: float = 0.0
    long_cc: float = 0.0
    short_cc: float = 0.0
    avg_target: float = 0.0
    targets: list[float] = field(default_factory=list)
    signal_types: set[str] = field(default_factory=set)

    @property
    def total(self) -> int:
        return self.long_count + self.short_count + self.flat_count

    @property
    def direction(self) -> str:
        if self.long_cc > self.short_cc * 1.2:
            return "LONG"
        elif self.short_cc > self.long_cc * 1.2:
            return "SHORT"
        return "MIXED"

    @property
    def strength(self) -> str:
        avg_cc = self.total_cc / self.total if self.total else 0
        if avg_cc > 0.4:
            return "STRONG"
        elif avg_cc > 0.2:
            return "moderate"
        return "weak"

    def summary(self) -> str:
        if not self.total:
            return "no signals"
        avg_cc = self.total_cc / self.total
        types = ", ".join(sorted(self.signal_types))
        dir_str = f"{self.long_count}L/{self.short_count}S"
        if self.flat_count:
            dir_str += f"/{self.flat_count}F"
        target_str = ""
        if self.targets:
            target_str = f", target cluster ${min(self.targets):.0f}-${max(self.targets):.0f}"
        return f"{self.direction} ({self.strength}) {dir_str} avg_cc={avg_cc:.3f}{target_str} [{types}]"


@dataclass
class MarketAnalysis:
    """Pre-digested market analysis for the LLM."""
    timestamp: float = 0.0
    mark_price: float = 0.0

    # Regime
    regime: str = "unknown"  # trending_up, trending_down, ranging, volatile, unknown
    regime_confidence: float = 0.0
    regime_details: str = ""

    # Category consensus
    categories: dict[str, CategoryConsensus] = field(default_factory=dict)

    # Overall
    total_signals: int = 0
    overall_direction: str = "MIXED"
    overall_confidence: float = 0.0
    agreement_pct: float = 0.0

    # Cross-validation
    cross_validation: str = ""  # e.g., "technical + microstructure confirm SHORT"
    conflicts: str = ""  # e.g., "sentiment contradicts technical"

    # Key thesis points
    thesis_points: list[str] = field(default_factory=list)

    # Signal performance (recent accuracy by type)
    signal_performance: dict[str, dict] = field(default_factory=dict)

    # Target price cluster
    target_cluster: str = ""

    # Horizon-specific analysis
    by_horizon: dict[str, dict] = field(default_factory=dict)

    # Trusted signals (proven >50% directional accuracy)
    _trusted_signals: list[dict] = field(default_factory=list)

    def to_prompt(self) -> str:
        """Format as a structured market briefing for the LLM."""
        sections = []

        # Regime
        sections.append(f"## Market Regime: {self.regime.upper()}")
        if self.regime_details:
            sections.append(f"  {self.regime_details}")
        sections.append(f"  Regime confidence: {self.regime_confidence:.0%}")

        # Trusted signal summary (data-driven from settled predictions)
        sections.append(f"\n## Trusted Signal Direction (proven >50% accurate)")
        trusted_long = 0
        trusted_short = 0
        trusted_details = []
        for p in self._trusted_signals:
            sig = p.get("signal_type", "")
            hz = p.get("hz", "")
            direction = p.get("direction", "flat")
            cc = p.get("cc", 0)
            if direction == "long":
                trusted_long += 1
            elif direction == "short":
                trusted_short += 1
            if cc > 0.2:
                trusted_details.append(f"{sig.replace('-signal','')}:{hz}→{direction}")
        if trusted_long or trusted_short:
            total_t = trusted_long + trusted_short
            t_dir = "LONG" if trusted_long > trusted_short else "SHORT" if trusted_short > trusted_long else "SPLIT"
            t_agree = max(trusted_long, trusted_short) / total_t * 100 if total_t else 0
            sections.append(f"  Trusted consensus: {t_dir} ({t_agree:.0f}% — {trusted_long}L/{trusted_short}S)")
            if trusted_details:
                sections.append(f"  Details: {', '.join(trusted_details[:10])}")
        else:
            sections.append(f"  No trusted signals active")

        # Full consensus by category
        sections.append(f"\n## All Signals by Category ({self.total_signals} total)")
        for cat_name in ["technical", "microstructure", "sentiment", "macro",
                         "derivatives", "onchain", "regime"]:
            cat = self.categories.get(cat_name)
            if cat and cat.total > 0:
                sections.append(f"  {cat_name.capitalize()}: {cat.summary()}")

        # Horizon-specific analysis with edge detection
        if self.by_horizon:
            sections.append(f"\n## Signal View — By Horizon")
            for hz in ["1m", "5m", "15m", "1h"]:
                hd = self.by_horizon.get(hz)
                if not hd or not hd.get("total"):
                    continue
                direction = hd.get("direction", "MIXED")
                agreement = hd.get("agreement_pct", 0)
                targets = hd.get("targets", [])
                if targets and self.mark_price > 0:
                    sorted_t = sorted(targets)
                    q1 = sorted_t[len(sorted_t) // 4] if len(sorted_t) > 3 else sorted_t[0]
                    q3 = sorted_t[3 * len(sorted_t) // 4] if len(sorted_t) > 3 else sorted_t[-1]
                    median = sorted_t[len(sorted_t) // 2]
                    spread = q3 - q1
                    pull = median - self.mark_price
                    pull_pct = abs(pull) / self.mark_price * 100

                    # Edge classification — calibrated to actual fee math:
                    # $1125 partial position → $0.79 flip fee → need $2.90+ move (0.14%)
                    if pull_pct < 0.07:
                        edge = f"NO EDGE ({pull:+.2f}) — below fee threshold, hold"
                    elif pull_pct < 0.15:
                        edge = f"MARGINAL ({pull:+.2f}, {pull_pct:.2f}%) — barely covers fees"
                    elif pull_pct < 0.30:
                        edge = f"TRADEABLE ({pull:+.2f}, {pull_pct:.2f}%) — expected profit after fees"
                    else:
                        edge = f"STRONG ({pull:+.2f}, {pull_pct:.2f}%) — clear directional move"

                    sections.append(
                        f"  {hz}: {direction} {agreement:.0%} ({hd['long']}L/{hd['short']}S) "
                        f"median=${median:.2f} spread=${spread:.2f} → {edge}"
                    )
                else:
                    sections.append(
                        f"  {hz}: {direction} {agreement:.0%} ({hd['long']}L/{hd['short']}S) "
                        f"avg_cc={hd.get('avg_cc',0):.3f}"
                    )

        # Breakout detection — single signal type spiking while others are flat
        if self.categories and self.mark_price > 0:
            breakout_signals = []
            for cat_name, cat in self.categories.items():
                if not cat.total or cat_name in ("regime",):
                    continue
                # Check if this category has strong pull while overall is weak
                if cat.targets:
                    cat_median = sorted(cat.targets)[len(cat.targets) // 2]
                    cat_pull_pct = abs(cat_median - self.mark_price) / self.mark_price * 100
                    # Category has strong pull (>0.15%) while we detected no tradeable edge on horizons
                    if cat_pull_pct > 0.15 and cat.direction != "MIXED":
                        breakout_signals.append(
                            f"{cat_name}: {cat.direction} pull={cat_median - self.mark_price:+.2f} "
                            f"({cat_pull_pct:.2f}%) [{', '.join(cat.signal_types)}]"
                        )
            if breakout_signals:
                sections.append(f"\n## BREAKOUT ALERT — individual signal types spiking:")
                for b in breakout_signals:
                    sections.append(f"  {b}")

        # Cross-validation
        if self.cross_validation:
            sections.append(f"\n## Cross-Validation")
            sections.append(f"  {self.cross_validation}")
        if self.conflicts:
            sections.append(f"  CONFLICTS: {self.conflicts}")

        # Overall thesis
        sections.append(f"\n## Overall Thesis: {self.overall_direction} ({self.agreement_pct:.0%} agreement)")
        if self.target_cluster:
            sections.append(f"  Target cluster: {self.target_cluster}")
        for point in self.thesis_points:
            sections.append(f"  - {point}")

        # Signal performance
        if self.signal_performance:
            sections.append(f"\n## Recent Signal Performance (which types to trust)")
            for sig_type, perf in sorted(self.signal_performance.items(),
                                          key=lambda x: -x[1].get("accuracy", 0)):
                acc = perf.get("accuracy", 0)
                total = perf.get("total", 0)
                if total >= 3:
                    label = "reliable" if acc > 0.6 else "mixed" if acc > 0.4 else "unreliable"
                    sections.append(
                        f"  {sig_type}: {acc:.0%} accuracy ({perf.get('hits',0)}/{total}) — {label}"
                    )

        return "\n".join(sections)


def analyze_signals(
    predictions: list[dict],
    settled_predictions: list[dict] | None = None,
    mark_price: float = 0.0,
) -> MarketAnalysis:
    """Analyze raw signals into a structured market briefing.

    Args:
        predictions: Active predictions from signal feed + AGDEL
        settled_predictions: Recently settled predictions for performance tracking
        mark_price: Current ETH price
    """
    analysis = MarketAnalysis(
        timestamp=time.time(),
        mark_price=mark_price,
    )

    if not predictions:
        analysis.regime = "unknown"
        analysis.overall_direction = "NO DATA"
        return analysis

    # Filter to active, non-expired predictions with meaningful confidence
    active = [p for p in predictions if not p.get("expired") and p.get("cc", 0) > 0.05]

    # ── Extract signals with strong directional conviction ──
    # Use direction_score (continuous) instead of stale accuracy combos.
    # Only trust signals where the script's own directional model is confident.
    analysis._trusted_signals = [
        p for p in active
        if abs(p.get("direction_score", 0)) > 0.2  # script has meaningful conviction
        and p.get("direction") in ("long", "short")
    ]

    # ── 1. Regime detection from regime signals ──
    regime_signals = [p for p in active if p.get("signal_type", "").startswith("regime")]
    if regime_signals:
        # Use the highest-confidence regime signal
        best_regime = max(regime_signals, key=lambda p: p.get("cc", 0))
        meta = best_regime.get("signal_metadata", {})
        analysis.regime = meta.get("regime", "unknown")
        analysis.regime_confidence = best_regime.get("cc", 0)
        details = []
        if meta.get("vol_regime"):
            details.append(f"volatility: {meta['vol_regime']}")
        if meta.get("ema_alignment"):
            details.append(f"EMA: {meta['ema_alignment']}")
        if meta.get("trend_direction"):
            details.append(f"trend: {meta['trend_direction']}")
        analysis.regime_details = ", ".join(details)

    # Check for trend exhaustion
    exhaustion_signals = [p for p in active if "exhaustion" in p.get("signal_type", "")]
    if exhaustion_signals:
        best_ex = max(exhaustion_signals, key=lambda p: p.get("cc", 0))
        ex_meta = best_ex.get("signal_metadata", {})
        ex_score = ex_meta.get("exhaustion_score", 0)
        if ex_score > 0.5:
            analysis.thesis_points.append(
                f"Trend exhaustion detected (score={ex_score:.2f}) — reversal likely"
            )

    # ── 2. Category consensus ──
    categories: dict[str, CategoryConsensus] = {}
    all_targets = []

    for p in active:
        sig_type = p.get("signal_type", "unknown")
        cat_name = SIGNAL_CATEGORIES.get(sig_type, "other")
        if cat_name not in categories:
            categories[cat_name] = CategoryConsensus(category=cat_name)
        cat = categories[cat_name]

        direction = p.get("direction", "flat")
        cc = p.get("cc", 0)
        target = p.get("target_price", 0)
        hz = p.get("hz", "5m")
        hz_weight = HORIZON_WEIGHTS.get(hz, 0.5)
        weighted_cc = cc * hz_weight

        cat.signal_types.add(sig_type.replace("-signal", ""))
        cat.total_cc += weighted_cc

        if direction == "long":
            cat.long_count += 1
            cat.long_cc += weighted_cc
        elif direction == "short":
            cat.short_count += 1
            cat.short_cc += weighted_cc
        else:
            cat.flat_count += 1

        if target and mark_price > 0:
            cat.targets.append(target)
            all_targets.append(target)

    analysis.categories = categories
    analysis.total_signals = len(active)

    # ── 3. Overall direction ──
    total_long_cc = sum(c.long_cc for c in categories.values())
    total_short_cc = sum(c.short_cc for c in categories.values())
    total_long = sum(c.long_count for c in categories.values())
    total_short = sum(c.short_count for c in categories.values())
    total_dir = total_long + total_short

    if total_long_cc > total_short_cc * 1.3:
        analysis.overall_direction = "LONG"
    elif total_short_cc > total_long_cc * 1.3:
        analysis.overall_direction = "SHORT"
    else:
        analysis.overall_direction = "MIXED"

    analysis.agreement_pct = max(total_long, total_short) / total_dir if total_dir else 0
    analysis.overall_confidence = (total_long_cc + total_short_cc) / len(active) if active else 0

    # Target cluster
    if all_targets:
        sorted_targets = sorted(all_targets)
        # Interquartile range for the cluster
        q1 = sorted_targets[len(sorted_targets) // 4]
        q3 = sorted_targets[3 * len(sorted_targets) // 4]
        median = sorted_targets[len(sorted_targets) // 2]
        analysis.target_cluster = f"${q1:.0f}-${q3:.0f} (median ${median:.0f})"

    # ── 3b. Horizon-specific analysis (critical for scalping) ──
    by_horizon: dict[str, dict] = {}
    for p in active:
        hz = p.get("hz", "unknown")
        if hz not in by_horizon:
            by_horizon[hz] = {"long": 0, "short": 0, "flat": 0, "total": 0,
                              "long_cc": 0, "short_cc": 0, "targets": [], "total_cc": 0}
        hd = by_horizon[hz]
        direction = p.get("direction", "flat")
        cc = p.get("cc", 0)
        target = p.get("target_price", 0)
        hd["total"] += 1
        hd["total_cc"] += cc
        if direction == "long":
            hd["long"] += 1
            hd["long_cc"] += cc
        elif direction == "short":
            hd["short"] += 1
            hd["short_cc"] += cc
        else:
            hd["flat"] += 1
        if target and mark_price > 0:
            hd["targets"].append(target)

    for hz, hd in by_horizon.items():
        if hd["long_cc"] > hd["short_cc"] * 1.2:
            hd["direction"] = "LONG"
        elif hd["short_cc"] > hd["long_cc"] * 1.2:
            hd["direction"] = "SHORT"
        else:
            hd["direction"] = "MIXED"
        dir_total = hd["long"] + hd["short"]
        hd["agreement_pct"] = max(hd["long"], hd["short"]) / dir_total if dir_total else 0
        hd["avg_cc"] = hd["total_cc"] / hd["total"] if hd["total"] else 0

    analysis.by_horizon = by_horizon

    # ── 4. Cross-validation ──
    confirming = []
    conflicting = []
    tech = categories.get("technical")
    micro = categories.get("microstructure")
    sent = categories.get("sentiment")
    macro = categories.get("macro")

    if tech and micro and tech.total and micro.total:
        if tech.direction == micro.direction and tech.direction != "MIXED":
            confirming.append(f"technical + microstructure both {tech.direction}")
        elif tech.direction != "MIXED" and micro.direction != "MIXED" and tech.direction != micro.direction:
            conflicting.append(f"technical says {tech.direction} but microstructure says {micro.direction}")

    if sent and sent.total and sent.direction != "MIXED":
        main_dir = tech.direction if tech and tech.total else analysis.overall_direction
        if sent.direction != main_dir and main_dir != "MIXED":
            conflicting.append(f"sentiment ({sent.direction}) contradicts main thesis ({main_dir})")
        elif sent.direction == main_dir:
            confirming.append(f"sentiment confirms {main_dir}")

    if macro and macro.total and macro.direction != "MIXED":
        main_dir = analysis.overall_direction
        if macro.direction != main_dir and main_dir != "MIXED":
            conflicting.append(f"macro/breadth ({macro.direction}) diverges from thesis ({main_dir})")

    analysis.cross_validation = "; ".join(confirming) if confirming else "no strong cross-validation"
    analysis.conflicts = "; ".join(conflicting) if conflicting else ""

    # ── 5. Thesis points ──
    if analysis.agreement_pct > 0.75:
        analysis.thesis_points.append(f"Strong consensus: {analysis.agreement_pct:.0%} of signals agree")
    elif analysis.agreement_pct < 0.55:
        analysis.thesis_points.append(f"Weak consensus: signals are split ({total_long}L vs {total_short}S)")

    if confirming:
        analysis.thesis_points.append(f"Cross-validated: {confirming[0]}")
    if conflicting:
        analysis.thesis_points.append(f"Warning: {conflicting[0]}")

    # Regime-specific advice
    if analysis.regime == "trending_up":
        analysis.thesis_points.append("Regime: trending up — favor longs, follow momentum")
    elif analysis.regime == "trending_down":
        analysis.thesis_points.append("Regime: trending down — favor shorts, follow momentum")
    elif analysis.regime == "ranging":
        analysis.thesis_points.append("Regime: ranging — quick profits, fade extremes")
    elif analysis.regime == "volatile":
        analysis.thesis_points.append("Regime: volatile — smaller positions, wider stops")

    # ── 6. Signal performance (from settled predictions) ──
    if settled_predictions:
        perf_by_type: dict[str, dict] = defaultdict(lambda: {"hits": 0, "misses": 0, "total": 0})
        for sp in settled_predictions:
            agent = sp.get("agent", sp.get("signal_type", "unknown"))
            outcome = sp.get("outcome", "")
            perf_by_type[agent]["total"] += 1
            if outcome == "HIT" or outcome is True:
                perf_by_type[agent]["hits"] += 1
            elif outcome == "MISS" or outcome is False:
                perf_by_type[agent]["misses"] += 1

        for agent, perf in perf_by_type.items():
            if perf["total"] > 0:
                perf["accuracy"] = perf["hits"] / perf["total"]
        analysis.signal_performance = dict(perf_by_type)

    return analysis
