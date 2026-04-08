"""SQLite persistence layer for candles, trades, signals, and alerts.

Single file database at data/trader.db. Survives restarts.
All writes are async-safe via aiosqlite.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import sqlite3

logger = logging.getLogger("db")

DB_PATH = Path(__file__).parent / "data" / "trader.db"


class TraderDB:
    """SQLite database for persistent trading data."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """Open connection and create tables."""
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()
        logger.info("SQLite DB connected: %s", self.db_path)

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _create_tables(self):
        c = self._conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS candles (
                timeframe TEXT NOT NULL,
                timestamp REAL NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                ticks INTEGER DEFAULT 0,
                PRIMARY KEY (timeframe, timestamp)
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                side TEXT,
                size REAL,
                price REAL,
                pnl REAL DEFAULT 0,
                fee REAL DEFAULT 0,
                regime TEXT,
                rationale TEXT,
                citations TEXT,  -- JSON array
                mode TEXT DEFAULT 'paper',
                created_at REAL DEFAULT (unixepoch())
            );

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,  -- 'agdel' or 'direct'
                signal_type TEXT,
                horizon TEXT,
                direction TEXT,
                confidence REAL,
                target_price REAL,
                entry_price REAL,
                quality_score REAL,
                maker TEXT,
                commitment_hash TEXT,
                outcome TEXT,
                created_at REAL DEFAULT (unixepoch())
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL,
                regime TEXT,
                indicators TEXT,  -- JSON
                triggered_at REAL DEFAULT (unixepoch())
            );

            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reasoning TEXT NOT NULL,
                action TEXT,  -- 'update', 'create', 'note'
                cxu_alias TEXT,
                change_description TEXT,
                price REAL,
                regime TEXT,
                position_side TEXT,
                created_at REAL DEFAULT (unixepoch())
            );

            CREATE INDEX IF NOT EXISTS idx_candles_tf_ts ON candles(timeframe, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(created_at DESC);
        """)
        c.commit()

    # ─── Candles ─────────────────────────────────────────────────
    def save_candle(self, timeframe: str, candle: dict):
        """Save a closed candle."""
        self._conn.execute(
            "INSERT OR REPLACE INTO candles (timeframe, timestamp, open, high, low, close, ticks) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timeframe, candle["timestamp"], candle["open"], candle["high"], candle["low"], candle["close"], candle.get("ticks", 0)),
        )
        self._conn.commit()

    def save_candles_batch(self, timeframe: str, candles: List[dict]):
        """Save multiple candles at once."""
        self._conn.executemany(
            "INSERT OR REPLACE INTO candles (timeframe, timestamp, open, high, low, close, ticks) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(timeframe, c["timestamp"], c["open"], c["high"], c["low"], c["close"], c.get("ticks", 0)) for c in candles],
        )
        self._conn.commit()

    def get_candles(self, timeframe: str, limit: int = 500, since: float = 0) -> List[dict]:
        """Get candles for a timeframe, most recent last."""
        rows = self._conn.execute(
            "SELECT timestamp, open, high, low, close, ticks FROM candles WHERE timeframe = ? AND timestamp >= ? ORDER BY timestamp ASC LIMIT ?",
            (timeframe, since, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_candle_count(self, timeframe: str) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM candles WHERE timeframe = ?", (timeframe,)).fetchone()
        return row[0] if row else 0

    # ─── Trades ──────────────────────────────────────────────────
    def save_trade(self, trade: dict):
        """Save a trade record."""
        self._conn.execute(
            "INSERT INTO trades (timestamp, action, side, size, price, pnl, fee, regime, rationale, citations, mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trade.get("timestamp", ""),
                trade.get("action", ""),
                trade.get("side", ""),
                trade.get("size", 0),
                trade.get("price", 0),
                trade.get("pnl", 0),
                trade.get("fee", 0),
                trade.get("regime", ""),
                trade.get("rationale", ""),
                json.dumps(trade.get("citations", [])),
                trade.get("mode", "paper"),
            ),
        )
        self._conn.commit()

    def get_trades(self, limit: int = 100, mode: Optional[str] = None) -> List[dict]:
        if mode:
            rows = self._conn.execute(
                "SELECT * FROM trades WHERE mode = ? ORDER BY created_at DESC LIMIT ?", (mode, limit)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["citations"] = json.loads(d.get("citations") or "[]")
            result.append(d)
        return result

    # ─── Signals ─────────────────────────────────────────────────
    def save_signal(self, signal: dict):
        self._conn.execute(
            "INSERT INTO signals (source, signal_type, horizon, direction, confidence, target_price, entry_price, quality_score, maker, commitment_hash, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                signal.get("source", ""),
                signal.get("signal_type", signal.get("signalType", "")),
                signal.get("horizon", ""),
                signal.get("direction", ""),
                signal.get("confidence", 0),
                signal.get("target_price", signal.get("targetPrice")),
                signal.get("entry_price", signal.get("entryPrice")),
                signal.get("quality_score", signal.get("quality", signal.get("qualityScore"))),
                signal.get("maker", ""),
                signal.get("commitment_hash", signal.get("commitmentHash", "")),
                signal.get("outcome"),
            ),
        )
        self._conn.commit()

    # ─── Alerts ──────────────────────────────────────────────────
    def save_alert(self, alert: dict):
        self._conn.execute(
            "INSERT INTO alerts (name, description, price, regime, indicators) VALUES (?, ?, ?, ?, ?)",
            (
                alert.get("name", ""),
                alert.get("description", ""),
                alert.get("price", 0),
                alert.get("regime", ""),
                json.dumps(alert.get("indicators", {})),
            ),
        )
        self._conn.commit()

    def get_alerts(self, limit: int = 50) -> List[dict]:
        rows = self._conn.execute(
            "SELECT * FROM alerts ORDER BY triggered_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── Observations ────────────────────────────────────────────
    def save_observation(self, obs: dict):
        self._conn.execute(
            "INSERT INTO observations (reasoning, action, cxu_alias, change_description, price, regime, position_side) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                obs.get("reasoning", ""),
                obs.get("action", ""),
                obs.get("cxu_alias", ""),
                obs.get("change_description", ""),
                obs.get("price", 0),
                obs.get("regime", ""),
                obs.get("position_side", ""),
            ),
        )
        self._conn.commit()

    # ─── Stats ───────────────────────────────────────────────────
    def get_stats(self) -> dict:
        c = self._conn
        candle_counts = {}
        for tf in ["1m", "3m", "5m", "15m", "1h"]:
            candle_counts[tf] = self.get_candle_count(tf)
        trade_count = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        signal_count = c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        alert_count = c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        return {
            "candles": candle_counts,
            "trades": trade_count,
            "signals": signal_count,
            "alerts": alert_count,
        }
