"""Cluster tracker — tracks how signal clusters move over time.

Instead of just looking at where the cluster is NOW (snapshot),
this tracks the DRIFT of the cluster — where it was 5 min ago
vs where it is now. The drift projects where price is headed.

Aggregates by signal TYPE separately, then reports which types
agree on direction. The LLM sees a trader's view, not raw data.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class ClusterSnapshot:
    """A single snapshot of a signal type's cluster position."""
    timestamp: float
    signal_type: str
    horizon: str
    median_target: float
    spread: float  # IQR width
    long_count: int
    short_count: int
    total_count: int
    avg_cc: float
    mark_price: float

    @property
    def pull(self) -> float:
        """How far the cluster is from current price."""
        return self.median_target - self.mark_price

    @property
    def pull_pct(self) -> float:
        return self.pull / self.mark_price * 100 if self.mark_price else 0


# How many snapshots to keep per signal type (at ~10s intervals, 30 = 5 min)
MAX_HISTORY = 60  # ~10 minutes of history


class ClusterTracker:
    """Tracks cluster positions over time to detect drift."""

    def __init__(self):
        # History per (signal_type, horizon): deque of ClusterSnapshot
        self._history: dict[str, deque[ClusterSnapshot]] = defaultdict(
            lambda: deque(maxlen=MAX_HISTORY)
        )

    def update(self, predictions: list[dict], mark_price: float):
        """Update cluster positions from the latest predictions."""
        now = time.time()

        # Group by (signal_type, horizon)
        groups: dict[str, list[dict]] = defaultdict(list)
        for p in predictions:
            if p.get("expired") or p.get("cc", 0) < 0.05:
                continue
            sig_type = p.get("signal_type", "unknown").replace("-signal", "")
            hz = p.get("hz", "unknown")
            key = f"{sig_type}:{hz}"
            groups[key].append(p)

        for key, preds in groups.items():
            parts = key.split(":", 1)
            sig_type = parts[0]
            hz = parts[1] if len(parts) > 1 else "?"

            targets = [p["target_price"] for p in preds if p.get("target_price")]
            if not targets:
                continue

            sorted_t = sorted(targets)
            q1 = sorted_t[len(sorted_t) // 4] if len(sorted_t) > 3 else sorted_t[0]
            q3 = sorted_t[3 * len(sorted_t) // 4] if len(sorted_t) > 3 else sorted_t[-1]
            median = sorted_t[len(sorted_t) // 2]

            longs = sum(1 for p in preds if p.get("direction") == "long")
            shorts = sum(1 for p in preds if p.get("direction") == "short")
            avg_cc = sum(p.get("cc", 0) for p in preds) / len(preds) if preds else 0

            snap = ClusterSnapshot(
                timestamp=now,
                signal_type=sig_type,
                horizon=hz,
                median_target=median,
                spread=q3 - q1,
                long_count=longs,
                short_count=shorts,
                total_count=len(preds),
                avg_cc=avg_cc,
                mark_price=mark_price,
            )
            self._history[key].append(snap)

    def get_drift(self, signal_type: str, horizon: str, lookback_seconds: int = 300) -> dict | None:
        """Calculate how a cluster has drifted over the lookback period.

        Returns dict with drift direction, magnitude, and confidence.
        """
        key = f"{signal_type}:{horizon}"
        history = self._history.get(key)
        if not history or len(history) < 3:
            return None

        now = time.time()
        cutoff = now - lookback_seconds

        # Find the oldest snapshot within lookback
        old_snap = None
        for snap in history:
            if snap.timestamp >= cutoff:
                old_snap = snap
                break
        if not old_snap:
            old_snap = history[0]

        new_snap = history[-1]
        if old_snap is new_snap:
            return None

        # Drift = how the median target moved relative to price movement
        target_drift = new_snap.median_target - old_snap.median_target
        price_drift = new_snap.mark_price - old_snap.mark_price
        # Net drift = cluster movement beyond price movement (the signal's added value)
        net_drift = target_drift - price_drift

        elapsed = new_snap.timestamp - old_snap.timestamp
        if elapsed < 10:
            return None

        # Project to 15 minutes
        drift_per_sec = net_drift / elapsed
        projected_15m = drift_per_sec * 900  # 15 minutes

        return {
            "signal_type": signal_type,
            "horizon": horizon,
            "target_drift": round(target_drift, 2),
            "price_drift": round(price_drift, 2),
            "net_drift": round(net_drift, 2),
            "projected_15m": round(projected_15m, 2),
            "elapsed_seconds": round(elapsed),
            "current_pull": round(new_snap.pull, 2),
            "current_pull_pct": round(new_snap.pull_pct, 3),
            "spread": round(new_snap.spread, 2),
            "avg_cc": round(new_snap.avg_cc, 3),
            "direction": "LONG" if projected_15m > 0 else "SHORT" if projected_15m < 0 else "FLAT",
        }

    def get_trader_briefing(self, mark_price: float) -> str:
        """Generate a trader's briefing from cluster drift data.

        This is what the LLM should see — concise, actionable.
        """
        sections = []
        sections.append(f"## Signal Cluster Analysis (price: ${mark_price:.2f})")

        # Compute drift for the key signal types on 5m horizon
        drifts_5m = {}
        drifts_15m = {}
        for sig_type in ["technical", "vwap", "mesa", "momentum", "basis",
                          "bb-reversal", "onchain-flow", "cross-asset",
                          "crypto-breadth", "funding", "regime"]:
            d5 = self.get_drift(sig_type, "5m", lookback_seconds=300)
            if d5:
                drifts_5m[sig_type] = d5
            d15 = self.get_drift(sig_type, "15m", lookback_seconds=600)
            if d15:
                drifts_15m[sig_type] = d15

        if not drifts_5m and not drifts_15m:
            sections.append("  Insufficient history — need a few minutes to track drift")
            return "\n".join(sections)

        # Summarize 5m cluster movements
        if drifts_5m:
            sections.append(f"\n### 5-min cluster drift (projected to 15m):")
            long_types = []
            short_types = []
            flat_types = []
            for sig_type, d in sorted(drifts_5m.items(), key=lambda x: -abs(x[1]["projected_15m"])):
                proj = d["projected_15m"]
                pull = d["current_pull"]
                cc = d["avg_cc"]
                label = f"{sig_type} (proj {proj:+.2f}, pull {pull:+.2f}, cc={cc:.2f})"
                if d["direction"] == "LONG":
                    long_types.append(label)
                elif d["direction"] == "SHORT":
                    short_types.append(label)
                else:
                    flat_types.append(label)

            if long_types:
                sections.append(f"  Drifting LONG: {', '.join(long_types)}")
            if short_types:
                sections.append(f"  Drifting SHORT: {', '.join(short_types)}")
            if flat_types:
                sections.append(f"  Flat: {', '.join(flat_types)}")

            # Net direction
            long_weight = sum(abs(d["projected_15m"]) * d["avg_cc"]
                              for d in drifts_5m.values() if d["direction"] == "LONG")
            short_weight = sum(abs(d["projected_15m"]) * d["avg_cc"]
                               for d in drifts_5m.values() if d["direction"] == "SHORT")
            if long_weight > short_weight * 1.3:
                net_5m = "LONG"
            elif short_weight > long_weight * 1.3:
                net_5m = "SHORT"
            else:
                net_5m = "MIXED"
            sections.append(f"  → 5m net drift: {net_5m} (long_wt={long_weight:.2f}, short_wt={short_weight:.2f})")

        # Summarize 15m cluster movements
        if drifts_15m:
            long_weight_15 = sum(abs(d["projected_15m"]) * d["avg_cc"]
                                  for d in drifts_15m.values() if d["direction"] == "LONG")
            short_weight_15 = sum(abs(d["projected_15m"]) * d["avg_cc"]
                                   for d in drifts_15m.values() if d["direction"] == "SHORT")
            if long_weight_15 > short_weight_15 * 1.3:
                net_15m = "LONG"
            elif short_weight_15 > long_weight_15 * 1.3:
                net_15m = "SHORT"
            else:
                net_15m = "MIXED"
            sections.append(f"\n### 15-min cluster drift: {net_15m}")

        # Overall picture — what a trader needs to know
        sections.append(f"\n### Price action context:")
        # Recent price movement from latest snapshots
        any_history = next(iter(self._history.values()), None)
        if any_history and len(any_history) >= 2:
            oldest = any_history[0]
            newest = any_history[-1]
            price_chg = newest.mark_price - oldest.mark_price
            elapsed = newest.timestamp - oldest.timestamp
            if elapsed > 0:
                rate_per_min = price_chg / (elapsed / 60)
                sections.append(f"  Price moved {price_chg:+.2f} over {elapsed/60:.0f}min ({rate_per_min:+.2f}/min)")

        return "\n".join(sections)
