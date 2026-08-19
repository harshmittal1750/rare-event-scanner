from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb
import polars as pl
from loguru import logger

from .config import settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ohlcv (
    asset       TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    ts          TIMESTAMP NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      DOUBLE,
    source      TEXT,
    PRIMARY KEY (asset, timeframe, ts)
);

CREATE TABLE IF NOT EXISTS funding_rates (
    asset       TEXT NOT NULL,
    venue       TEXT NOT NULL,
    ts          TIMESTAMP NOT NULL,
    rate        DOUBLE,          -- per-interval rate as decimal (e.g. 0.0001 = 1bp/hr)
    interval_h  DOUBLE,          -- hours per funding interval (hyperliquid = 1)
    premium     DOUBLE,
    PRIMARY KEY (asset, venue, ts)
);

CREATE TABLE IF NOT EXISTS published_events (
    dedup_key       TEXT PRIMARY KEY,
    event_type      TEXT,
    asset           TEXT,
    timeframe       TEXT,
    detected_at     TIMESTAMP,
    rarity_percentile DOUBLE,
    headline        TEXT,
    published_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_data_dir() -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir


@contextmanager
def connection():
    _ensure_data_dir()
    conn = duckdb.connect(str(settings.db_path))
    try:
        conn.execute(SCHEMA_SQL)
        yield conn
    finally:
        conn.close()


def upsert_ohlcv(df: pl.DataFrame) -> int:
    """Insert/replace OHLCV rows. Expects columns: asset, timeframe, ts, o, h, l, c, v, source."""
    if df.is_empty():
        return 0
    required = {"asset", "timeframe", "ts", "open", "high", "low", "close", "volume", "source"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")

    with connection() as conn:
        conn.register("incoming", df.to_arrow())
        conn.execute("""
            INSERT INTO ohlcv (asset, timeframe, ts, open, high, low, close, volume, source)
            SELECT asset, timeframe, ts, open, high, low, close, volume, source FROM incoming
            ON CONFLICT (asset, timeframe, ts) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume, source=excluded.source;
        """)
        conn.unregister("incoming")
    return df.height


def load_ohlcv(asset: str, timeframe: str = "1d") -> pl.DataFrame:
    with connection() as conn:
        arrow_tbl = conn.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE asset = ? AND timeframe = ? ORDER BY ts",
            [asset, timeframe],
        ).fetch_arrow_table()
    return pl.from_arrow(arrow_tbl)


def latest_ts(asset: str, timeframe: str = "1d") -> datetime | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT MAX(ts) FROM ohlcv WHERE asset = ? AND timeframe = ?",
            [asset, timeframe],
        ).fetchone()
    return row[0] if row and row[0] else None


def upsert_funding(df: pl.DataFrame) -> int:
    """Insert/replace funding rows. Expects: asset, venue, ts, rate, interval_h, premium."""
    if df.is_empty():
        return 0
    required = {"asset", "venue", "ts", "rate", "interval_h", "premium"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"funding frame missing columns: {missing}")
    with connection() as conn:
        conn.register("incoming", df.to_arrow())
        conn.execute("""
            INSERT INTO funding_rates (asset, venue, ts, rate, interval_h, premium)
            SELECT asset, venue, ts, rate, interval_h, premium FROM incoming
            ON CONFLICT (asset, venue, ts) DO UPDATE SET
                rate=excluded.rate, interval_h=excluded.interval_h, premium=excluded.premium;
        """)
        conn.unregister("incoming")
    return df.height


def load_funding(asset: str, venue: str) -> pl.DataFrame:
    with connection() as conn:
        arrow_tbl = conn.execute(
            "SELECT ts, rate, interval_h, premium FROM funding_rates "
            "WHERE asset = ? AND venue = ? ORDER BY ts",
            [asset, venue],
        ).fetch_arrow_table()
    return pl.from_arrow(arrow_tbl)


def latest_funding_ts(asset: str, venue: str) -> datetime | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT MAX(ts) FROM funding_rates WHERE asset = ? AND venue = ?",
            [asset, venue],
        ).fetchone()
    return row[0] if row and row[0] else None


def record_published(event_dedup_key: str, payload: dict) -> bool:
    """Returns True if this was a new record; False if already published."""
    with connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM published_events WHERE dedup_key = ?",
            [event_dedup_key],
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """INSERT INTO published_events
               (dedup_key, event_type, asset, timeframe, detected_at,
                rarity_percentile, headline)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                event_dedup_key,
                payload["event_type"],
                payload["asset"],
                payload["timeframe"],
                payload["detected_at"],
                payload["rarity_percentile"],
                payload["headline"],
            ],
        )
    return True


def stats() -> dict:
    with connection() as conn:
        rows = conn.execute(
            "SELECT asset, timeframe, COUNT(*), MIN(ts), MAX(ts) "
            "FROM ohlcv GROUP BY asset, timeframe ORDER BY asset"
        ).fetchall()
        funding_rows = conn.execute(
            "SELECT asset, venue, COUNT(*), MIN(ts), MAX(ts) "
            "FROM funding_rates GROUP BY asset, venue ORDER BY asset"
        ).fetchall()
        published = conn.execute("SELECT COUNT(*) FROM published_events").fetchone()[0]
    logger.info(f"Published events: {published}")
    logger.info("OHLCV:")
    for asset, tf, n, mn, mx in rows:
        logger.info(f"  {asset:<10} {tf}: {n:>6} rows  {mn} → {mx}")
    if funding_rows:
        logger.info("Funding rates:")
        for asset, venue, n, mn, mx in funding_rows:
            logger.info(f"  {asset:<10} @{venue:<12} {n:>6} rows  {mn} → {mx}")
    return {"assets": len(rows), "funding_series": len(funding_rows), "published": published}
