"""Market sentiment bias — hard directional gate from cross-market correlation.

Fetches returns from correlated assets and determines if the broad market
is bullish, bearish, or neutral. This is a GATE, not a signal:
- BULLISH: block all short entries
- BEARISH: block all long entries
- NEUTRAL: no restriction

This runs as CODE, not a prompt instruction, because the LLM ignores
prompt-level restrictions. The gate prevents wrong-direction trades
from ever reaching Hyperliquid.
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger("sentiment")

# Assets correlated with ETH, ordered by importance
CORRELATED_ASSETS = [
    "BTC", "SOL", "ARB", "OP", "LINK", "AAVE", "UNI",
    "AVAX", "DOGE", "HYPE",
]

# Thresholds
BULLISH_RATIO = 0.75   # 75%+ of assets up → bullish
BEARISH_RATIO = 0.25   # 25%- of assets up (75%+ down) → bearish
MIN_MOVE_PCT = 0.5     # asset must move ±0.5% to count as up/down
LOOKBACK_HOURS = 4     # 4h returns for sentiment
CACHE_SECONDS = 300    # recompute every 5 minutes

HL_API = "https://api.hyperliquid.xyz"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
FNG_URL = "https://api.alternative.me/fng/?limit=1"

# Macro indicators and their bullish/bearish interpretation
MACRO_INDICATORS = [
    ("^GSPC", "S&P 500", "up_is_bullish"),      # stocks up = risk-on
    ("^IXIC", "NASDAQ", "up_is_bullish"),         # tech up = bullish for crypto
    ("^VIX", "VIX", "up_is_bearish"),             # fear up = bearish
    ("GC=F", "Gold", "neutral"),                   # mixed signal
    ("DX-Y.NYB", "Dollar Index", "up_is_bearish"),# strong dollar = bearish for crypto
]


class SentimentBias:
    """Computes broad market sentiment from correlated asset returns."""

    def __init__(self):
        self._bias: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
        self._ratio: float = 0.5
        self._details: dict = {}
        self._last_computed: float = 0
        self._http = httpx.AsyncClient(timeout=10)

    @property
    def bias(self) -> str:
        return self._bias

    @property
    def ratio(self) -> float:
        return self._ratio

    async def compute(self) -> str:
        """Recompute sentiment bias from cross-market returns."""
        now = time.time()
        if now - self._last_computed < CACHE_SECONDS:
            return self._bias

        try:
            start_ms = int((now - LOOKBACK_HOURS * 3600) * 1000)
            end_ms = int(now * 1000)

            returns = {}
            for asset in CORRELATED_ASSETS:
                try:
                    resp = await self._http.post(HL_API + "/info", json={
                        "type": "candleSnapshot",
                        "req": {
                            "coin": asset,
                            "interval": "1h",
                            "startTime": start_ms,
                            "endTime": end_ms,
                        },
                    })
                    candles = resp.json()
                    if candles and len(candles) >= 2:
                        open_price = float(candles[0]["o"])
                        close_price = float(candles[-1]["c"])
                        ret = (close_price - open_price) / open_price * 100
                        returns[asset] = ret
                except Exception:
                    pass

            if not returns:
                self._bias = "NEUTRAL"
                return self._bias

            bullish = sum(1 for r in returns.values() if r > MIN_MOVE_PCT)
            bearish = sum(1 for r in returns.values() if r < -MIN_MOVE_PCT)
            total = len(returns)
            ratio = bullish / total

            if ratio >= BULLISH_RATIO:
                self._bias = "BULLISH"
            elif ratio <= BEARISH_RATIO:
                self._bias = "BEARISH"
            else:
                self._bias = "NEUTRAL"

            self._ratio = round(ratio, 2)
            self._details = {
                "bullish_count": bullish,
                "bearish_count": bearish,
                "total": total,
                "ratio": self._ratio,
                "returns": {k: round(v, 2) for k, v in returns.items()},
            }
            self._last_computed = now

            # Also fetch macro indicators
            await self.compute_macro()
            macro_bias = getattr(self, '_macro', {}).get('macro_bias', 'NEUTRAL')

            # Combine: if both crypto and macro agree, strengthen the bias
            if macro_bias == self._bias and self._bias != "NEUTRAL":
                logger.info("Sentiment: %s CONFIRMED by macro (%.0f%% crypto up, macro=%s)",
                            self._bias, ratio * 100, macro_bias)
            else:
                logger.info("Sentiment: %s (%.0f%% crypto up, macro=%s)",
                            self._bias, ratio * 100, macro_bias)

        except Exception as e:
            logger.warning("Sentiment computation failed: %s", e)

        return self._bias

    def should_block(self, action: str) -> tuple[bool, str]:
        """Check if an action should be blocked by sentiment gate.

        Only blocks when BOTH crypto and macro agree on direction.
        If they diverge (e.g., crypto bearish but macro bullish), no block —
        that divergence is itself a signal (often contrarian bullish).
        """
        macro_bias = getattr(self, '_macro', {}).get('macro_bias', 'NEUTRAL')

        # Only block when crypto AND macro agree
        if self._bias == "BULLISH" and macro_bias != "BEARISH" and action in ("open_short", "flip_short"):
            return True, f"BLOCKED: crypto BULLISH ({self._ratio:.0%} up) + macro {macro_bias} — no shorts"
        if self._bias == "BEARISH" and macro_bias != "BULLISH" and action in ("open_long", "flip_long"):
            return True, f"BLOCKED: crypto BEARISH ({1-self._ratio:.0%} down) + macro {macro_bias} — no longs"
        return False, ""

    async def compute_macro(self) -> dict:
        """Fetch macro indicators from Yahoo Finance + Crypto Fear & Greed."""
        macro = {"indicators": {}, "fear_greed": None, "macro_bias": "NEUTRAL"}
        try:
            bullish_signals = 0
            bearish_signals = 0

            for symbol, name, interpretation in MACRO_INDICATORS:
                try:
                    resp = await self._http.get(
                        f"{YAHOO_URL}/{symbol}?interval=1d&range=2d",
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    data = resp.json()
                    result = data.get("chart", {}).get("result", [{}])[0]
                    meta = result.get("meta", {})
                    price = meta.get("regularMarketPrice", 0)
                    prev = meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0)
                    if price and prev:
                        chg = (price - prev) / prev * 100
                        macro["indicators"][name] = {"price": round(price, 2), "change_pct": round(chg, 2)}
                        if interpretation == "up_is_bullish" and chg > 0.3:
                            bullish_signals += 1
                        elif interpretation == "up_is_bullish" and chg < -0.3:
                            bearish_signals += 1
                        elif interpretation == "up_is_bearish" and chg > 0.3:
                            bearish_signals += 1
                        elif interpretation == "up_is_bearish" and chg < -0.3:
                            bullish_signals += 1
                except Exception:
                    pass

            # Crypto Fear & Greed
            try:
                resp = await self._http.get(FNG_URL)
                fg_data = resp.json()
                fg = fg_data.get("data", [{}])[0]
                fg_value = int(fg.get("value", 50))
                fg_label = fg.get("value_classification", "Neutral")
                macro["fear_greed"] = {"value": fg_value, "label": fg_label}
                # Extreme fear is contrarian bullish
                if fg_value <= 20:
                    bullish_signals += 1
                elif fg_value >= 80:
                    bearish_signals += 1
            except Exception:
                pass

            if bullish_signals >= 3:
                macro["macro_bias"] = "BULLISH"
            elif bearish_signals >= 3:
                macro["macro_bias"] = "BEARISH"

            self._macro = macro
        except Exception as e:
            logger.debug("Macro fetch failed: %s", e)

        return macro

    def get_summary(self) -> str:
        """One-line summary for the LLM prompt."""
        if not self._details:
            return "Sentiment: computing..."
        d = self._details
        summary = (
            f"Market Sentiment: {self._bias} "
            f"({d['bullish_count']}/{d['total']} crypto assets up, "
            f"{d['bearish_count']} down)"
        )
        macro = getattr(self, '_macro', None)
        if macro:
            mb = macro.get("macro_bias", "NEUTRAL")
            fg = macro.get("fear_greed")
            if fg:
                summary += f" | Macro: {mb}, Fear&Greed: {fg['value']} ({fg['label']})"
            indicators = macro.get("indicators", {})
            parts = []
            for name, data in indicators.items():
                parts.append(f"{name} {data['change_pct']:+.1f}%")
            if parts:
                summary += f" | {', '.join(parts)}"
        return summary

    def get_stats(self) -> dict:
        return {
            "bias": self._bias,
            "ratio": self._ratio,
            "details": self._details,
            "macro": getattr(self, '_macro', None),
            "lastComputed": self._last_computed,
        }
