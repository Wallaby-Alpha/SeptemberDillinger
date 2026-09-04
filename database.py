"""
Database module for MEXC Quiet Accumulation Scanner.
Provides SQLite storage for alerts, candidate evaluation logs, cooldown tracking,
and subsequent price performance records.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


class Database:
    def __init__(self, db_path: str = "scanner_data.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create necessary tables and indices if they do not exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Alerts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    timestamp_unix INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    price REAL NOT NULL,
                    final_score REAL NOT NULL,
                    stage TEXT NOT NULL,
                    rs_score REAL NOT NULL,
                    vol_score REAL NOT NULL,
                    trend_score REAL NOT NULL,
                    liq_score REAL NOT NULL,
                    ema20_1h REAL NOT NULL,
                    ema50_1h REAL NOT NULL,
                    daily_ema20 REAL NOT NULL,
                    vol_ratio REAL NOT NULL,
                    rs_diff_pct REAL NOT NULL,
                    spread_bps REAL NOT NULL,
                    quote_volume_24h REAL NOT NULL,
                    suggested_entry_low REAL NOT NULL,
                    suggested_entry_high REAL NOT NULL,
                    suggested_stop REAL NOT NULL,
                    telegram_sent INTEGER NOT NULL DEFAULT 0,
                    metrics_json TEXT
                )
            """)

            # Candidates evaluation table (all scanned coins above min_log_score)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    price REAL NOT NULL,
                    final_score REAL NOT NULL,
                    stage TEXT NOT NULL,
                    passed_gates INTEGER NOT NULL,
                    rs_score REAL NOT NULL,
                    vol_score REAL NOT NULL,
                    trend_score REAL NOT NULL,
                    liq_score REAL NOT NULL,
                    spread_bps REAL NOT NULL,
                    quote_volume_24h REAL NOT NULL
                )
            """)

            # Cooldown tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    symbol TEXT PRIMARY KEY,
                    last_alert_time TEXT NOT NULL,
                    last_alert_unix INTEGER NOT NULL
                )
            """)

            # Performance tracking table (5m, 15m, 1h, 4h, 24h price action)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performance_tracking (
                    alert_id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    alert_timestamp TEXT NOT NULL,
                    alert_timestamp_unix INTEGER NOT NULL,
                    alert_price REAL NOT NULL,
                    price_5m REAL,
                    return_5m_pct REAL,
                    price_15m REAL,
                    return_15m_pct REAL,
                    price_1h REAL,
                    return_1h_pct REAL,
                    price_4h REAL,
                    return_4h_pct REAL,
                    price_24h REAL,
                    return_24h_pct REAL,
                    max_favorable_excursion_pct REAL,
                    max_adverse_excursion_pct REAL,
                    evaluated_at TEXT,
                    is_complete INTEGER DEFAULT 0,
                    FOREIGN KEY (alert_id) REFERENCES alerts(id)
                )
            """)

            # Indices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_time ON alerts(timestamp_unix)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_symbol ON candidates(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_complete ON performance_tracking(is_complete)")

            conn.commit()

    def log_candidate(
        self,
        symbol: str,
        price: float,
        final_score: float,
        stage: str,
        passed_gates: bool,
        rs_score: float,
        vol_score: float,
        trend_score: float,
        liq_score: float,
        spread_bps: float,
        quote_volume_24h: float,
    ) -> None:
        """Log candidate evaluation into candidates table."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO candidates (
                    timestamp, symbol, price, final_score, stage, passed_gates,
                    rs_score, vol_score, trend_score, liq_score, spread_bps, quote_volume_24h
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now_utc, symbol, price, final_score, stage, 1 if passed_gates else 0,
                rs_score, vol_score, trend_score, liq_score, spread_bps, quote_volume_24h
            ))
            conn.commit()

    def save_alert(
        self,
        symbol: str,
        price: float,
        final_score: float,
        stage: str,
        rs_score: float,
        vol_score: float,
        trend_score: float,
        liq_score: float,
        ema20_1h: float,
        ema50_1h: float,
        daily_ema20: float,
        vol_ratio: float,
        rs_diff_pct: float,
        spread_bps: float,
        quote_volume_24h: float,
        suggested_entry_low: float,
        suggested_entry_high: float,
        suggested_stop: float,
        telegram_sent: bool,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Save a new alert to the database and initialize performance record."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        now_unix = int(now.timestamp())
        metrics_json = json.dumps(metrics or {})

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alerts (
                    timestamp, timestamp_unix, symbol, price, final_score, stage,
                    rs_score, vol_score, trend_score, liq_score,
                    ema20_1h, ema50_1h, daily_ema20, vol_ratio, rs_diff_pct,
                    spread_bps, quote_volume_24h,
                    suggested_entry_low, suggested_entry_high, suggested_stop,
                    telegram_sent, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now_iso, now_unix, symbol, price, final_score, stage,
                rs_score, vol_score, trend_score, liq_score,
                ema20_1h, ema50_1h, daily_ema20, vol_ratio, rs_diff_pct,
                spread_bps, quote_volume_24h,
                suggested_entry_low, suggested_entry_high, suggested_stop,
                1 if telegram_sent else 0, metrics_json
            ))
            alert_id = cursor.lastrowid

            # Initialize entry in performance tracking
            cursor.execute("""
                INSERT INTO performance_tracking (
                    alert_id, symbol, alert_timestamp, alert_timestamp_unix, alert_price
                ) VALUES (?, ?, ?, ?, ?)
            """, (alert_id, symbol, now_iso, now_unix, price))

            # Update cooldown
            cursor.execute("""
                INSERT INTO cooldowns (symbol, last_alert_time, last_alert_unix)
                VALUES (?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    last_alert_time=excluded.last_alert_time,
                    last_alert_unix=excluded.last_alert_unix
            """, (symbol, now_iso, now_unix))

            conn.commit()
            return alert_id

    def is_on_cooldown(self, symbol: str, cooldown_minutes: int) -> bool:
        """Check if symbol is currently in cooldown period."""
        if cooldown_minutes <= 0:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_alert_unix FROM cooldowns WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            if not row:
                return False
            last_alert_unix = row["last_alert_unix"]
            current_unix = int(datetime.now(timezone.utc).timestamp())
            cooldown_seconds = cooldown_minutes * 60
            return (current_unix - last_alert_unix) < cooldown_seconds

    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve the most recent alerts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_pending_performance_alerts(self) -> List[Dict[str, Any]]:
        """Retrieve alerts that have incomplete performance tracking."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.*, a.final_score, a.stage, a.rs_score, a.vol_score, a.trend_score
                FROM performance_tracking p
                JOIN alerts a ON p.alert_id = a.id
                WHERE p.is_complete = 0
                ORDER BY p.alert_id ASC
            """)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def update_performance_record(
        self,
        alert_id: int,
        price_5m: Optional[float],
        return_5m_pct: Optional[float],
        price_15m: Optional[float],
        return_15m_pct: Optional[float],
        price_1h: Optional[float],
        return_1h_pct: Optional[float],
        price_4h: Optional[float],
        return_4h_pct: Optional[float],
        price_24h: Optional[float],
        return_24h_pct: Optional[float],
        max_favorable_excursion_pct: Optional[float],
        max_adverse_excursion_pct: Optional[float],
        is_complete: bool,
    ) -> None:
        """Update performance tracking fields for a specific alert."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE performance_tracking SET
                    price_5m = coalesce(?, price_5m),
                    return_5m_pct = coalesce(?, return_5m_pct),
                    price_15m = coalesce(?, price_15m),
                    return_15m_pct = coalesce(?, return_15m_pct),
                    price_1h = coalesce(?, price_1h),
                    return_1h_pct = coalesce(?, return_1h_pct),
                    price_4h = coalesce(?, price_4h),
                    return_4h_pct = coalesce(?, return_4h_pct),
                    price_24h = coalesce(?, price_24h),
                    return_24h_pct = coalesce(?, return_24h_pct),
                    max_favorable_excursion_pct = coalesce(?, max_favorable_excursion_pct),
                    max_adverse_excursion_pct = coalesce(?, max_adverse_excursion_pct),
                    evaluated_at = ?,
                    is_complete = ?
                WHERE alert_id = ?
            """, (
                price_5m, return_5m_pct,
                price_15m, return_15m_pct,
                price_1h, return_1h_pct,
                price_4h, return_4h_pct,
                price_24h, return_24h_pct,
                max_favorable_excursion_pct, max_adverse_excursion_pct,
                now_iso, 1 if is_complete else 0, alert_id
            ))
            conn.commit()

    def get_all_performance_records(self) -> List[Dict[str, Any]]:
        """Retrieve all performance records joined with alert info."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.*, a.final_score, a.stage, a.rs_score, a.vol_score, a.trend_score, a.spread_bps
                FROM performance_tracking p
                JOIN alerts a ON p.alert_id = a.id
                ORDER BY p.alert_id DESC
            """)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
