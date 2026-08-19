import time
from datetime import UTC, datetime, timedelta

import httpx
import polars as pl
from loguru import logger

from ..config import AssetSpec
from ..db import (
    latest_funding_ts,
    latest_ts,
    upsert_funding,
    upsert_ohlcv,
)

HL_API = "https://api.hyperliquid.xyz/info"
HL_VENUE = "hyperliquid"
REQUEST_SLEEP_SECONDS = 0.3


def _post(payload: dict, max_retries: int = 3) -> list | dict:
    for attempt in range(max_retries):
        try:
            resp = httpx.post(HL_API, json=payload, timeout=30.0)
            if resp.status_code == 429:
                wait = 2**attempt
                logger.warning(f"[hl] 429 rate limited, sleeping {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            time.sleep(REQUEST_SLEEP_SECONDS)
            return resp.json()
        except httpx.HTTPError:
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt)
    return []


def fetch_hyperliquid_daily(spec: AssetSpec, backfill_days: int = 3650) -> int:
    """Fetch daily OHLCV candles for a Hyperliquid perp and upsert into `ohlcv`."""
    last_ts = latest_ts(spec.symbol, "1d")
    if last_ts is None:
        start_dt = datetime.now(UTC) - timedelta(days=backfill_days)
        logger.info(f"[hl] {spec.symbol}: cold backfill from {start_dt.date()}")
    else:
        start_dt = last_ts - timedelta(days=3)
        logger.info(f"[hl] {spec.symbol}: incremental from {start_dt.date()}")

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(datetime.now(UTC).timestamp() * 1000)

    all_rows: list[dict] = []
    cursor = start_ms
    # HL returns up to 5000 candles per call.
    while cursor < end_ms:
        window_end = min(cursor + 5000 * 86_400_000, end_ms)
        batch = _post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": spec.source_symbol,
                    "interval": "1d",
                    "startTime": cursor,
                    "endTime": window_end,
                },
            }
        )
        if not isinstance(batch, list) or not batch:
            break
        all_rows.extend(batch)
        last_t = batch[-1].get("t", cursor)
        next_cursor = last_t + 86_400_000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < 5000:
            break

    if not all_rows:
        logger.warning(f"[hl] {spec.symbol}: no candles")
        return 0

    df = pl.DataFrame(all_rows)
    df = df.unique(subset=["t"]).sort("t")
    df = df.with_columns(
        (pl.col("t").cast(pl.Int64) * 1000).cast(pl.Datetime("us")).alias("ts"),
        pl.col("o").cast(pl.Float64).alias("open"),
        pl.col("h").cast(pl.Float64).alias("high"),
        pl.col("l").cast(pl.Float64).alias("low"),
        pl.col("c").cast(pl.Float64).alias("close"),
        pl.col("v").cast(pl.Float64).alias("volume"),
        pl.lit(spec.symbol).alias("asset"),
        pl.lit("1d").alias("timeframe"),
        pl.lit("hyperliquid").alias("source"),
    )
    df = df.select(
        ["asset", "timeframe", "ts", "open", "high", "low", "close", "volume", "source"]
    )
    n = upsert_ohlcv(df)
    logger.info(f"[hl] {spec.symbol}: upserted {n} candle rows")
    return n


def fetch_hyperliquid_funding(spec: AssetSpec, backfill_days: int = 3650) -> int:
    """Fetch hourly funding rates and upsert into `funding_rates`."""
    last_ts = latest_funding_ts(spec.symbol, HL_VENUE)
    if last_ts is None:
        start_dt = datetime.now(UTC) - timedelta(days=backfill_days)
        logger.info(f"[hl-fund] {spec.symbol}: cold backfill from {start_dt.date()}")
    else:
        start_dt = last_ts - timedelta(hours=2)
        logger.info(f"[hl-fund] {spec.symbol}: incremental from {start_dt}")

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(datetime.now(UTC).timestamp() * 1000)

    all_rows: list[dict] = []
    cursor = start_ms
    # HL returns up to 500 funding entries per call (~20 days at hourly).
    max_window_ms = 500 * 3600 * 1000
    while cursor < end_ms:
        window_end = min(cursor + max_window_ms, end_ms)
        batch = _post(
            {
                "type": "fundingHistory",
                "coin": spec.source_symbol,
                "startTime": cursor,
                "endTime": window_end,
            }
        )
        if not isinstance(batch, list) or not batch:
            break
        all_rows.extend(batch)
        last_time = batch[-1].get("time", cursor)
        next_cursor = last_time + 3600 * 1000
        if next_cursor <= cursor:
            break
        cursor = next_cursor

    if not all_rows:
        logger.warning(f"[hl-fund] {spec.symbol}: no funding rows")
        return 0

    normalized = [
        {
            "time": int(r["time"]),
            "rate": float(r.get("fundingRate", 0) or 0),
            "premium": float(r["premium"]) if r.get("premium") not in (None, "") else 0.0,
        }
        for r in all_rows
        if "time" in r
    ]
    if not normalized:
        logger.warning(f"[hl-fund] {spec.symbol}: no usable rows after normalization")
        return 0

    df = pl.DataFrame(normalized)
    df = df.unique(subset=["time"]).sort("time")
    df = df.with_columns(
        (pl.col("time") * 1000).cast(pl.Datetime("us")).alias("ts"),
        pl.lit(spec.symbol).alias("asset"),
        pl.lit(HL_VENUE).alias("venue"),
        pl.lit(1.0).alias("interval_h"),
    )
    df = df.select(["asset", "venue", "ts", "rate", "interval_h", "premium"])
    n = upsert_funding(df)
    logger.info(f"[hl-fund] {spec.symbol}: upserted {n} funding rows")
    return n
