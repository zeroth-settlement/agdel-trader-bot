"""Market context aggregator — collects all available data for LLM reasoning."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class MarketContext:
    """All available market data for a single decision tick."""

    mark_price: float = 0.0
    asset: str = "ETH"
    timestamp: float = field(default_factory=time.time)

    # Position & portfolio
    position: dict = field(default_factory=dict)
    portfolio: dict = field(default_factory=dict)

    # All active signals keyed by horizon (e.g., "5m", "15m")
    # Each signal dict contains: score, confidence, calibration, direction,
    # target_price, entry_price, signal_type, maker, horizon, all_hashes, etc.
    signals: dict[str, dict | None] = field(default_factory=dict)

    # Purchase log entries (recent, with delivery metadata)
    active_predictions: list[dict] = field(default_factory=list)

    # Recent trade history (newest first)
    recent_trades: list[dict] = field(default_factory=list)

    # Recent price ticks for trend context
    recent_ticks: list[dict] = field(default_factory=list)

    # Risk levels (SL/TP if position open)
    risk_levels: dict = field(default_factory=dict)

    # AGDEL marketplace stats
    agdel_stats: dict = field(default_factory=dict)

    # Direct signal feed stats
    signal_feed_stats: dict = field(default_factory=dict)

    # Cluster tracker briefing (pre-computed trader's view)
    cluster_briefing: str = ""

    def to_prompt_context(self) -> str:
        """Format all data as structured text for the LLM decision prompt."""
        sections = []

        # Price
        sections.append(f"## Current Market\n- Asset: {self.asset}\n- Mark Price: ${self.mark_price:.2f}")

        # Price trend from recent ticks
        if self.recent_ticks:
            ticks = list(self.recent_ticks)[:60]  # last ~5 min at 5s intervals
            if len(ticks) >= 2:
                oldest_price = ticks[-1].get("markPrice", self.mark_price)
                newest_price = ticks[0].get("markPrice", self.mark_price)
                if oldest_price > 0:
                    change_pct = (newest_price - oldest_price) / oldest_price * 100
                    direction = "UP" if change_pct > 0 else "DOWN" if change_pct < 0 else "FLAT"
                    sections.append(
                        f"- Recent trend ({len(ticks)} ticks): {direction} {abs(change_pct):.3f}%"
                        f" (${oldest_price:.2f} -> ${newest_price:.2f})"
                    )

        # Position
        pos = self.position
        if pos and pos.get("size", 0) != 0:
            side = pos.get("side", "flat")
            size = pos.get("size", 0)
            entry = pos.get("entryPrice", 0)
            upnl = pos.get("unrealizedPnl", 0)
            leverage = pos.get("leverage", 1)
            pnl_pct = (upnl / (abs(size) * entry) * 100) if entry and size else 0
            sections.append(
                f"\n## Current Position\n"
                f"- Side: {side.upper()}\n"
                f"- Size: {abs(size):.4f} ETH\n"
                f"- Entry Price: ${entry:.2f}\n"
                f"- Current PnL: ${upnl:.2f} ({pnl_pct:+.2f}%)\n"
                f"- Leverage: {leverage}x"
            )
        else:
            sections.append("\n## Current Position\n- FLAT (no open position)")

        # Portfolio
        if self.portfolio:
            equity = self.portfolio.get("equity", 0)
            available = self.portfolio.get("availableBalance", 0)
            total_pnl = self.portfolio.get("pnl", 0)
            sections.append(
                f"\n## Portfolio\n"
                f"- Equity: ${equity:.2f}\n"
                f"- Available Balance: ${available:.2f}\n"
                f"- Session PnL: ${total_pnl:.2f}"
            )

        # Risk levels
        if self.risk_levels:
            rl = self.risk_levels
            parts = ["\n## Active Risk Levels"]
            if "slPrice" in rl:
                parts.append(f"- Stop Loss: ${rl['slPrice']:.2f} ({rl.get('slMode', 'unknown')})")
            if "tpPrice" in rl:
                parts.append(f"- Take Profit: ${rl['tpPrice']:.2f}")
            if rl.get("signalTarget"):
                parts.append(f"- Signal Target: ${rl['signalTarget']:.2f}")
            if rl.get("watermarkHigh"):
                parts.append(f"- Watermark High: ${rl['watermarkHigh']:.2f}")
            if rl.get("watermarkLow") and rl["watermarkLow"] < 1e10:
                parts.append(f"- Watermark Low: ${rl['watermarkLow']:.2f}")
            cd = rl.get("cooldownRemaining", 0)
            if cd > 0:
                parts.append(f"- Trade Cooldown: {cd}s remaining")
            sections.append("\n".join(parts))

        # Signals — all horizons with full detail
        if self.signals:
            parts = ["\n## Active Signals"]
            for hz in sorted(self.signals.keys()):
                sig = self.signals[hz]
                if not sig:
                    parts.append(f"\n### {hz} horizon: NO SIGNAL")
                    continue
                conf = float(sig.get("confidence", 0) or 0)
                calib = float(sig.get("calibration", 1.0) or 1.0)
                cc = round(conf * calib, 4)
                direction = sig.get("direction", "unknown")
                tp = sig.get("target_price")
                ep = sig.get("entry_price")
                sig_type = sig.get("signal_type", "unknown")
                score = float(sig.get("score", 0) or 0)
                agg = sig.get("aggregated_from", 1)

                parts.append(f"\n### {hz} horizon:")
                parts.append(f"  - Direction: {direction}")
                parts.append(f"  - Confidence: {conf:.3f} (calibration: {calib:.3f}, C*C: {cc:.4f})")
                parts.append(f"  - Score: {score:.4f}")
                parts.append(f"  - Signal Type: {sig_type}")
                if tp is not None:
                    tp_val = float(tp)
                    parts.append(f"  - Target Price: ${tp_val:.2f}")
                    if self.mark_price > 0:
                        pull_pct = (tp_val - self.mark_price) / self.mark_price * 100
                        parts.append(f"  - Gravity Pull: {pull_pct:+.3f}% from current")
                if ep is not None:
                    ep_val = float(ep)
                    parts.append(f"  - Entry Price (at signal): ${ep_val:.2f}")
                if agg > 1:
                    parts.append(f"  - Aggregated from: {agg} signals")

            sections.append("\n".join(parts))
        else:
            sections.append("\n## Active Signals\nNo signals currently available.")

        # Active predictions (all delivered signals — the FULL picture for the LLM)
        if self.active_predictions:
            active = [p for p in self.active_predictions if not p.get("expired")]
            expired_recent = [p for p in self.active_predictions if p.get("expired")]

            # Group active by signal type for pattern analysis
            by_type: dict[str, list] = {}
            for pred in active:
                sig_type = pred.get("signal_type", "unknown")
                by_type.setdefault(sig_type, []).append(pred)

            parts = [f"\n## Individual Signals ({len(active)} active, {len(expired_recent)} recently expired)"]

            if active:
                # Summary by signal type
                parts.append("\n### Signal Type Breakdown:")
                for sig_type, preds in sorted(by_type.items()):
                    long_count = sum(1 for p in preds if p.get("direction") == "long")
                    short_count = sum(1 for p in preds if p.get("direction") == "short")
                    avg_cc = sum(p.get("cc", 0) for p in preds) / len(preds) if preds else 0
                    targets = [p.get("target_price", 0) for p in preds if p.get("target_price")]
                    avg_target = sum(targets) / len(targets) if targets else 0
                    dir_label = f"{long_count}L/{short_count}S"
                    parts.append(
                        f"  {sig_type}: {dir_label} avg_cc={avg_cc:.3f} "
                        f"avg_target=${avg_target:.2f} ({len(preds)} signals)"
                    )

                # Detailed signal list
                parts.append("\n### All Active Signals:")
                for pred in sorted(active, key=lambda p: -p.get("cc", 0)):
                    hz = pred.get("hz", "?")
                    direction = pred.get("direction", "?")
                    conf = pred.get("confidence", 0)
                    calib = pred.get("calibration", 0)
                    cc = pred.get("cc", 0)
                    tp = pred.get("target_price", 0)
                    ep = pred.get("entry_price")
                    sig_type = pred.get("signal_type", "?")
                    maker = pred.get("maker", "?")

                    # Compute gravity if possible
                    gravity = ""
                    if tp and self.mark_price > 0:
                        pull_pct = (tp - self.mark_price) / self.mark_price * 100
                        gravity = f" gravity={pull_pct:+.3f}%"

                    strength = "STRONG" if cc > 0.4 else "moderate" if cc > 0.2 else "weak"
                    line = (
                        f"  [{hz}] {sig_type} → {direction.upper()} "
                        f"cc={cc:.3f} ({strength}) target=${tp:.2f}{gravity} "
                        f"conf={conf:.3f} calib={calib:.3f} maker={maker}"
                    )
                    if ep:
                        line += f" entry=${ep:.2f}"
                    # Append rich metadata from delivery if available
                    sm = pred.get("signal_metadata")
                    if isinstance(sm, dict):
                        meta_parts = []
                        if sm.get("regime"):
                            meta_parts.append(f"regime={sm['regime']}")
                        if sm.get("trend_direction"):
                            meta_parts.append(f"trend={sm['trend_direction']}")
                        if sm.get("exhaustion_score"):
                            meta_parts.append(f"exhaustion={sm['exhaustion_score']:.2f}")
                        if sm.get("vol_regime"):
                            meta_parts.append(f"vol={sm['vol_regime']}")
                        if sm.get("ema_alignment"):
                            meta_parts.append(f"ema={sm['ema_alignment']}")
                        if sm.get("reasoning"):
                            meta_parts.append(f'"{sm["reasoning"][:80]}"')
                        if meta_parts:
                            line += f"\n    context: {' | '.join(meta_parts)}"
                    parts.append(line)

            # Recently expired with outcomes (signal track record)
            resolved = [p for p in expired_recent if p.get("outcome")]
            if resolved:
                hits = sum(1 for p in resolved if p.get("outcome") == "HIT")
                misses = sum(1 for p in resolved if p.get("outcome") == "MISS")
                parts.append(f"\n### Recent Signal Outcomes: {hits} HIT / {misses} MISS")
                for pred in resolved[:8]:
                    sig_type = pred.get("signal_type", "?")
                    direction = pred.get("direction", "?")
                    outcome = pred.get("outcome", "?")
                    cc = pred.get("cc", 0)
                    parts.append(
                        f"  {sig_type} {direction} cc={cc:.3f} → {outcome}"
                    )

            sections.append("\n".join(parts))

        # Recent trades
        if self.recent_trades:
            parts = [f"\n## Recent Trades (last {len(self.recent_trades[:10])})"]
            for t in self.recent_trades[:10]:
                action = t.get("action", "?")
                price = t.get("price", 0)
                pnl = t.get("pnl", 0)
                fee = t.get("fee", 0)
                ts = t.get("timestamp", 0)
                age = int(time.time() - ts) if ts else 0
                rationale = t.get("rationale", {})
                reason = rationale.get("reason", "") if isinstance(rationale, dict) else str(rationale)

                parts.append(
                    f"  {action} @ ${price:.2f} pnl=${pnl:.4f} fee=${fee:.4f} "
                    f"({age}s ago) {reason[:80]}"
                )
            sections.append("\n".join(parts))

        # Signal purchase stats
        if self.agdel_stats:
            parts = ["\n## Signal Marketplace Stats"]
            stats = self.agdel_stats
            if "purchased" in stats:
                parts.append(f"  - Purchased: {stats['purchased']}")
            if "delivered" in stats:
                parts.append(f"  - Delivered: {stats['delivered']}")
            if "avgDeliveryTime" in stats:
                parts.append(f"  - Avg Delivery Time: {stats['avgDeliveryTime']:.1f}s")
            if "outcomes" in stats and isinstance(stats["outcomes"], dict):
                for k, v in stats["outcomes"].items():
                    parts.append(f"  - Outcome {k}: {v}")
            sections.append("\n".join(parts))

        return "\n".join(sections)

    def signal_consensus(self) -> dict:
        """Compute simple consensus across all active signals."""
        long_count = 0
        short_count = 0
        total_cc = 0.0
        long_cc = 0.0
        short_cc = 0.0

        for hz, sig in self.signals.items():
            if not sig:
                continue
            direction = sig.get("direction", "")
            conf = float(sig.get("confidence", 0) or 0)
            calib = float(sig.get("calibration", 1.0) or 1.0)
            cc = conf * calib

            if direction == "long":
                long_count += 1
                long_cc += cc
            elif direction == "short":
                short_count += 1
                short_cc += cc
            total_cc += cc

        total_signals = long_count + short_count
        return {
            "long_count": long_count,
            "short_count": short_count,
            "total_signals": total_signals,
            "long_cc": round(long_cc, 4),
            "short_cc": round(short_cc, 4),
            "net_direction": "long" if long_cc > short_cc else "short" if short_cc > long_cc else "flat",
            "agreement_ratio": max(long_count, short_count) / total_signals if total_signals else 0,
        }
