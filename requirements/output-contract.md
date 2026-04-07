# Output Contract

## Agent Output Types

### 1. RegimeClassification (regime-classifier agent)
```json
{
  "regime": "ranging | trending_up | trending_down | volatile",
  "confidence": 0.85,
  "reasoning": "Price trend at +0.05% (below ±0.2% threshold), Bollinger position cycling 25-75%, no sustained directional movement in last 30 minutes",
  "indicators": {
    "trendPct": 0.05,
    "bollingerPosition": 42,
    "volatilityExpansion": false,
    "sessionContext": "asia"
  },
  "citations": [
    { "cxu_id": "1220e5f6...", "alias": "regime-ranging" }
  ]
}
```

### 2. SignalAssessment (signal-assessor agent)
```json
{
  "summary": "12 direct signals analyzed, 3 AGDEL purchased. Net drift: LONG (weak). Consensus: 58% (below 75% threshold).",
  "consensus": {
    "direction": "LONG",
    "agreementPct": 58,
    "meetsThreshold": false,
    "threshold": 75
  },
  "signalQuality": [
    {
      "signalType": "onchain-flow",
      "horizon": "15m",
      "direction": "LONG",
      "confidence": 0.72,
      "historicalAccuracy": 0.93,
      "regimeRelevance": "high"
    }
  ],
  "blockedSignals": ["basis", "bb-reversal"],
  "recommendation": "hold — consensus below threshold for current regime",
  "citations": [
    { "cxu_id": "1220e1f2...", "alias": "learning-signal-accuracy-by-type" }
  ]
}
```

### 3. TradeDecision (trade-decider agent)
```json
{
  "action": "hold | open_long | open_short | close",
  "sizePct": 100,
  "confidence": 0.82,
  "reasoning": "Regime: RANGING. Playbook requires 75% consensus (current: 58%). Price at 42% of Bollinger range (not at entry zone <15%). HOLD per axiom-hold-default.",
  "riskLevels": {
    "stopLossPct": 3.0,
    "takeProfitPct": 8.0,
    "trailingStop": true
  },
  "feeCheck": {
    "estimatedEdge": 0,
    "minimumEdge": 13,
    "passesCheck": false
  },
  "citations": [
    { "cxu_id": "1220b2c3...", "alias": "axiom-hold-default" },
    { "cxu_id": "1220b8c9...", "alias": "playbook-ranging" },
    { "cxu_id": "1220a1b2...", "alias": "axiom-fee-kill" }
  ]
}
```

### 4. ReflectionOutput (reflector agent)
```json
{
  "cycle": 5,
  "tradesAnalyzed": 3,
  "signalsSettled": 42,
  "summary": "Last 3 trades: 2 wins, 1 loss. Net +$8.50. Onchain-flow confirmed as best signal in ranging (3/3 correct). Momentum-signal underperformed (1/3).",
  "cxusCreated": 1,
  "cxusUpdated": 1,
  "pendingHumanReview": 0,
  "changes": [
    {
      "action": "update",
      "cxuAlias": "learning-signal-accuracy-by-type",
      "field": "parameters.preferredSignalTypes",
      "before": "onchain-flow,vwap,technical,momentum",
      "after": "onchain-flow,vwap,technical",
      "reason": "momentum-signal dropped below 50% accuracy in ranging regime over last 24h"
    },
    {
      "action": "create",
      "cxuAlias": "learning-ranging-session-bias",
      "claim": "Ranging regime entries are most profitable during Asia session (00:00-08:00 UTC) when volatility is lowest",
      "tier": "learning",
      "evidence": "3/3 Asia session ranging trades profitable vs 1/4 US session"
    }
  ],
  "performanceDelta": {
    "before": { "winRate": 0.55, "avgPnl": 2.10 },
    "after": { "winRate": 0.67, "avgPnl": 2.83 }
  },
  "citations": [
    { "cxu_id": "1220e1f2...", "alias": "learning-signal-accuracy-by-type" }
  ]
}
```

## Dashboard Mapping

| Output Type | Tab | Components |
|-------------|-----|-----------|
| RegimeClassification | Trading | regime-badge, regime indicator in market strip |
| SignalAssessment | Signals | signal quality matrix, consensus meter |
| TradeDecision | Trading | decision card with CxU pills, gravity chart |
| ReflectionOutput | Reflection | timeline entries, CxU diff viewer, performance delta |
