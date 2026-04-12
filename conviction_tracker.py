"""Signal Conviction Tracker — logs conviction every minute and tracks resolution.

Every 60 seconds:
1. Compute overall signal conviction from range asymmetry
2. Record current price
3. Check how previous convictions resolved (was the direction right?)
4. Log everything to SQLite for analysis
"""
import asyncio
import os
import sys
import time
import json
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

CHECK_INTERVAL = 60  # 1 minute
RESOLUTION_WINDOWS = [60, 300, 900]  # Check resolution at 1m, 5m, 15m
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "conviction_tracker.db")
TRADING_SERVER = "http://localhost:9004"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conviction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            price REAL NOT NULL,
            conviction REAL NOT NULL,
            label TEXT NOT NULL,
            signal_count INTEGER,
            long_count INTEGER,
            short_count INTEGER,
            per_signal TEXT,
            regime TEXT,
            resolved_1m INTEGER DEFAULT NULL,
            resolved_5m INTEGER DEFAULT NULL,
            resolved_15m INTEGER DEFAULT NULL,
            price_1m REAL DEFAULT NULL,
            price_5m REAL DEFAULT NULL,
            price_15m REAL DEFAULT NULL
        )
    """)
    conn.commit()
    return conn


def compute_conviction(predictions, mark_price):
    """Compute directional conviction from signal range asymmetry."""
    by_type = {}
    for p in predictions:
        if p.get('expired'): continue
        agent = (p.get('signal_type') or p.get('agent') or '?').replace('-signal', '')
        target = p.get('target_price') or p.get('targetPrice') or 0
        entry = p.get('entry_price') or p.get('entryPrice') or mark_price
        conf = p.get('confidence') or p.get('cc') or 0
        if not target or conf < 0.01: continue

        skew = (target - entry) / entry if entry > 0 else 0

        if agent not in by_type:
            by_type[agent] = {'total_skew': 0, 'total_conf': 0, 'count': 0}
        by_type[agent]['total_skew'] += skew * conf
        by_type[agent]['total_conf'] += conf
        by_type[agent]['count'] += 1

    total_weighted = 0
    total_weight = 0
    per_signal = {}
    for agent, d in by_type.items():
        avg_skew = d['total_skew'] / d['total_conf'] if d['total_conf'] > 0 else 0
        avg_conf = d['total_conf'] / d['count'] if d['count'] > 0 else 0
        total_weighted += avg_skew * avg_conf
        total_weight += avg_conf
        bias = 'LONG' if avg_skew > 0.0001 else 'SHORT' if avg_skew < -0.0001 else 'FLAT'
        per_signal[agent] = {'skew': round(avg_skew * 100, 4), 'conf': round(avg_conf, 3), 'bias': bias}

    overall = total_weighted / total_weight if total_weight > 0 else 0
    label = 'BULLISH' if overall > 0.0002 else 'BEARISH' if overall < -0.0002 else 'NEUTRAL'

    longs = sum(1 for p in predictions if not p.get('expired') and str(p.get('direction', '')).lower() in ('long', '0'))
    shorts = sum(1 for p in predictions if not p.get('expired') and str(p.get('direction', '')).lower() in ('short', '1'))

    return {
        'conviction': overall,
        'label': label,
        'signal_count': len(predictions),
        'long_count': longs,
        'short_count': shorts,
        'per_signal': per_signal,
    }


def resolve_old_entries(conn, current_price, current_time):
    """Check old conviction entries and resolve them."""
    for window, col_resolved, col_price in [
        (60, 'resolved_1m', 'price_1m'),
        (300, 'resolved_5m', 'price_5m'),
        (900, 'resolved_15m', 'price_15m'),
    ]:
        rows = conn.execute(
            f"SELECT id, price, conviction FROM conviction_log WHERE {col_resolved} IS NULL AND timestamp < ?",
            (current_time - window,)
        ).fetchall()

        for row_id, entry_price, conviction in rows:
            price_change = (current_price - entry_price) / entry_price
            # Resolved correctly if conviction direction matches price direction
            correct = (conviction > 0 and price_change > 0) or (conviction < 0 and price_change < 0)
            # Neutral convictions are "correct" if price didn't move much
            if abs(conviction) < 0.0002:
                correct = abs(price_change) < 0.001

            conn.execute(
                f"UPDATE conviction_log SET {col_resolved} = ?, {col_price} = ? WHERE id = ?",
                (1 if correct else 0, current_price, row_id)
            )
        if rows:
            conn.commit()


async def run():
    import httpx

    conn = init_db()
    print(f"Conviction tracker started (interval={CHECK_INTERVAL}s, db={DB_PATH})", flush=True)

    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                # Get predictions and price
                resp = await client.get(f"{TRADING_SERVER}/api/predictions")
                preds = resp.json().get('predictions', [])

                resp = await client.get(f"{TRADING_SERVER}/api/state")
                state = resp.json()
                price = state.get('markPrice', 0)
                regime = state.get('regime', {}).get('regime', '?')

                if price and preds:
                    result = compute_conviction(preds, price)
                    now = time.time()

                    # Log to DB
                    conn.execute(
                        "INSERT INTO conviction_log (timestamp, price, conviction, label, signal_count, long_count, short_count, per_signal, regime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (now, price, result['conviction'], result['label'],
                         result['signal_count'], result['long_count'], result['short_count'],
                         json.dumps(result['per_signal']), regime)
                    )
                    conn.commit()

                    # Resolve old entries
                    resolve_old_entries(conn, price, now)

                    # Print status
                    total_1m = conn.execute("SELECT COUNT(*) FROM conviction_log WHERE resolved_1m IS NOT NULL").fetchone()[0]
                    correct_1m = conn.execute("SELECT COUNT(*) FROM conviction_log WHERE resolved_1m = 1").fetchone()[0]
                    acc_1m = f"{correct_1m/total_1m*100:.0f}%" if total_1m > 0 else "n/a"

                    total_5m = conn.execute("SELECT COUNT(*) FROM conviction_log WHERE resolved_5m IS NOT NULL").fetchone()[0]
                    correct_5m = conn.execute("SELECT COUNT(*) FROM conviction_log WHERE resolved_5m = 1").fetchone()[0]
                    acc_5m = f"{correct_5m/total_5m*100:.0f}%" if total_5m > 0 else "n/a"

                    print(f"[{time.strftime('%H:%M')}] ${price:,.2f} {result['label']:>8s} ({result['conviction']*100:+.3f}%) "
                          f"{result['long_count']}L/{result['short_count']}S "
                          f"| 1m acc: {acc_1m} ({total_1m}) 5m acc: {acc_5m} ({total_5m}) "
                          f"| regime: {regime}", flush=True)

            except Exception as e:
                print(f"[{time.strftime('%H:%M')}] Error: {e}", flush=True)

            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
