"""Market sentiment bias — hard directional gate from cross-market correlation.

Fetches returns from correlated assets and determines if the broad market
is bullish, bearish, or neutral. This is a GATE, not a signal:
- BULLISH: block all short entries
- BEARISH: block all long entries
- NEUTRAL: no restriction

This runs as CODE, not a prompt instruction, because the LLM ignores
prompt-level restrictions. The gate prevents wrong-direction trades
from ever reaching Hyperliquid.

LLM analysis layer: periodically feeds quantitative data + news headlines
to Claude for a synthesized macro narrative with score, risks, and holding rec.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from xml.etree import ElementTree

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

# RSS feeds for news headlines
NEWS_FEEDS = [
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk"),
    ("https://cointelegraph.com/rss", "CoinTelegraph"),
    ("https://feeds.feedburner.com/zerohedge/feed", "ZeroHedge"),
    ("https://www.rss.app/feeds/v1.1/tsBYgEnFqxDgHZG3.json", "CryptoNews"),
]
LLM_CACHE_SECONDS = 900  # 15 minutes between LLM calls
LLM_MODEL = "claude-sonnet-4-6"

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
            "llmAnalysis": getattr(self, '_llm_analysis', None),
        }

    # ─── LLM-powered macro analysis ─────────────────────────────────

    async def analyze_with_llm(self) -> dict | None:
        """Use Claude to synthesize a macro sentiment narrative from
        quantitative indicators + recent news headlines."""
        now = time.time()
        cached = getattr(self, '_llm_analysis', None)
        if cached and now - cached.get("timestamp", 0) < LLM_CACHE_SECONDS:
            return cached

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("No ANTHROPIC_API_KEY — skipping LLM macro analysis")
            return None

        # 1. Ensure quantitative data is fresh
        await self.compute()

        # 2. Fetch news headlines
        headlines = await self._fetch_headlines()

        # 3. Build the prompt
        quant_summary = self._build_quant_summary()
        headline_text = "\n".join(f"- [{h['source']}] {h['title']}" for h in headlines[:25])
        if not headline_text:
            headline_text = "(No recent headlines available)"

        system = """You are a macro analyst for a crypto trading desk that trades ETH perpetuals on Hyperliquid. Your job is to synthesize quantitative market data and recent news into an actionable macro sentiment assessment.

You are advising a trader who holds positions for minutes to hours — not days. They need to know:
1. Is the macro environment supportive of holding risk (crypto longs) or defensive?
2. Are there imminent catalysts or risks that could cause sharp moves?
3. Should they be more aggressive (wider stops, let winners run) or defensive (tight stops, quick exits)?

Be specific and direct. No hedging or "it depends" — give a clear read."""

        user = f"""## Current Quantitative Indicators
{quant_summary}

## Recent Headlines
{headline_text}

## Current Date/Time
{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}

Respond with JSON:
{{
  "score": <integer -100 to +100, where -100 = max bearish, +100 = max bullish>,
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": <0.0-1.0 how confident you are in this read>,
  "narrative": "<2-3 sentence summary of the macro picture>",
  "keyFactors": ["<factor 1>", "<factor 2>", "<factor 3>"],
  "risks": ["<risk 1>", "<risk 2>"],
  "holdingRec": "<1 sentence: how this should affect holding ETH positions right now>",
  "divergences": "<any notable divergences between indicators, or null>"
}}"""

        try:
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": LLM_MODEL,
                        "max_tokens": 600,
                        "temperature": 0.1,
                        "system": system,
                        "messages": [{"role": "user", "content": user}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data.get("content", [{}])[0].get("text", "")

                # Parse JSON from response
                parsed = self._parse_json(text)
                if parsed:
                    parsed["timestamp"] = now
                    parsed["headlineCount"] = len(headlines)
                    self._llm_analysis = parsed
                    logger.info("LLM macro analysis: score=%s bias=%s confidence=%.0f%%",
                                parsed.get("score"), parsed.get("bias"), (parsed.get("confidence", 0)) * 100)
                    return parsed

        except Exception as e:
            logger.warning("LLM macro analysis failed: %s", e)

        return None

    async def _fetch_headlines(self) -> list[dict]:
        """Fetch recent headlines from RSS feeds."""
        headlines = []
        for url, source in NEWS_FEEDS:
            try:
                resp = await self._http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                if not resp.is_success:
                    continue
                content_type = resp.headers.get("content-type", "")

                if "json" in content_type or url.endswith(".json"):
                    # JSON feed
                    data = resp.json()
                    for item in (data.get("items") or data.get("entries") or [])[:8]:
                        title = item.get("title", "")
                        if title:
                            headlines.append({"source": source, "title": title[:150]})
                else:
                    # XML/RSS feed
                    root = ElementTree.fromstring(resp.text)
                    # Handle both RSS and Atom
                    ns = {"atom": "http://www.w3.org/2005/Atom"}
                    items = root.findall(".//item") or root.findall(".//atom:entry", ns)
                    for item in items[:8]:
                        title_el = item.find("title") or item.find("atom:title", ns)
                        if title_el is not None and title_el.text:
                            headlines.append({"source": source, "title": title_el.text.strip()[:150]})
            except Exception as e:
                logger.debug("RSS fetch failed for %s: %s", source, e)
        return headlines

    def _build_quant_summary(self) -> str:
        """Build a text summary of all quantitative indicators for the LLM."""
        lines = []

        # Crypto breadth
        d = self._details
        if d:
            lines.append(f"Crypto breadth: {d.get('bullish_count', '?')}/{d.get('total', '?')} assets up over 4h (ratio: {self._ratio:.0%})")
            lines.append(f"Crypto bias: {self._bias}")
            returns = d.get("returns", {})
            if returns:
                top_movers = sorted(returns.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
                lines.append("Top movers: " + ", ".join(f"{k} {v:+.2f}%" for k, v in top_movers))

        # Macro indicators
        macro = getattr(self, '_macro', {}) or {}
        indicators = macro.get("indicators", {})
        for name, data in indicators.items():
            lines.append(f"{name}: ${data.get('price', '?'):,} ({data.get('change_pct', 0):+.1f}% today)")

        # Fear & Greed
        fg = macro.get("fear_greed")
        if fg:
            lines.append(f"Crypto Fear & Greed Index: {fg['value']} ({fg['label']})")

        lines.append(f"Macro bias (algorithmic): {macro.get('macro_bias', 'UNKNOWN')}")

        return "\n".join(lines) if lines else "No quantitative data available yet."

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try markdown code block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Try finding first JSON object
        start = text.find("{")
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{": depth += 1
                elif text[i] == "}": depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i+1])
                    except json.JSONDecodeError:
                        break
        return None
