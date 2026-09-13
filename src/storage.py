"""Persistance SQLite. Les tables brutes (mentions_snapshot, price_snapshot)
ne sont jamais réécrites ni purgées par un changement de config : seuls les
calculs de signal (fait à la volée, non stocké de façon définitive) en tiennent
compte."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS mentions_snapshot (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    mentions INTEGER NOT NULL,
    mentions_24h_ago INTEGER,
    rank INTEGER,
    upvotes INTEGER,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (date, ticker)
);

CREATE TABLE IF NOT EXISTS price_snapshot (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    close REAL,
    volume INTEGER,
    is_weekend_carry INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, ticker)
);

CREATE TABLE IF NOT EXISTS collection_log (
    run_date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    tickers_collected INTEGER
);
"""


@contextmanager
def get_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_mentions(conn, date, rows):
    """rows: iterable de dicts avec ticker, mentions, mentions_24h_ago, rank, upvotes"""
    conn.executemany(
        """
        INSERT INTO mentions_snapshot
            (date, ticker, mentions, mentions_24h_ago, rank, upvotes, collected_at)
        VALUES (:date, :ticker, :mentions, :mentions_24h_ago, :rank, :upvotes, :collected_at)
        ON CONFLICT(date, ticker) DO UPDATE SET
            mentions=excluded.mentions,
            mentions_24h_ago=excluded.mentions_24h_ago,
            rank=excluded.rank,
            upvotes=excluded.upvotes,
            collected_at=excluded.collected_at
        """,
        [{**r, "date": date} for r in rows],
    )


def upsert_prices(conn, rows):
    """rows: iterable de dicts avec date, ticker, close, volume, is_weekend_carry"""
    conn.executemany(
        """
        INSERT INTO price_snapshot (date, ticker, close, volume, is_weekend_carry)
        VALUES (:date, :ticker, :close, :volume, :is_weekend_carry)
        ON CONFLICT(date, ticker) DO UPDATE SET
            close=excluded.close,
            volume=excluded.volume,
            is_weekend_carry=excluded.is_weekend_carry
        """,
        rows,
    )


def log_collection(conn, run_date, status, message, tickers_collected=0):
    from datetime import datetime, timezone

    conn.execute(
        """
        INSERT INTO collection_log (run_date, timestamp, status, message, tickers_collected)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_date, datetime.now(timezone.utc).isoformat(), status, message, tickers_collected),
    )


def get_last_collection(conn):
    row = conn.execute(
        "SELECT * FROM collection_log ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def get_distinct_dates(conn):
    rows = conn.execute("SELECT DISTINCT date FROM mentions_snapshot ORDER BY date").fetchall()
    return [r["date"] for r in rows]


def get_ticker_mentions_history(conn, ticker, limit_days=None):
    q = "SELECT date, mentions, rank, upvotes FROM mentions_snapshot WHERE ticker = ? ORDER BY date"
    rows = conn.execute(q, (ticker,)).fetchall()
    rows = [dict(r) for r in rows]
    if limit_days:
        rows = rows[-limit_days:]
    return rows


def get_ticker_price_history(conn, ticker, limit_days=None):
    q = "SELECT date, close, volume, is_weekend_carry FROM price_snapshot WHERE ticker = ? ORDER BY date"
    rows = conn.execute(q, (ticker,)).fetchall()
    rows = [dict(r) for r in rows]
    if limit_days:
        rows = rows[-limit_days:]
    return rows


def get_all_tickers(conn):
    rows = conn.execute("SELECT DISTINCT ticker FROM mentions_snapshot").fetchall()
    return [r["ticker"] for r in rows]


def get_latest_snapshot_tickers(conn, date):
    rows = conn.execute(
        "SELECT ticker, mentions, rank, upvotes FROM mentions_snapshot WHERE date = ? ORDER BY rank",
        (date,),
    ).fetchall()
    return [dict(r) for r in rows]
