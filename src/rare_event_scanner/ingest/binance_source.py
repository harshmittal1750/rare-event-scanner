from datetime import UTC, datetime, timedelta

import ccxt
import polars as pl
from loguru import logger

from ..config import AssetSpec
from ..db import latest_ts, upsert_ohlcv


def fetch_binance_daily(spec: AssetSpec, backfill_days: int = 3650) -> int:
    exchange = ccxt.binance({"enableRateLimit": True})

    last_ts = latest_ts(spec.symbol, "1d")
    if last_ts is None:
        since_dt = datetime.now(UTC) - timedelta(days=backfill_days)
        logger.info(f"[binance] {spec.symbol}: cold backfill from {since_dt.date()}")
    else:
        since_dt = last_ts - timedelta(days=3)
        logger.info(f"[binance] {spec.symbol}: incremental from {since_dt.date()}")

    since_ms = int(since_dt.timestamp() * 1000)
    all_rows: list[list] = []
    while True:
        batch = exchange.fetch_ohlcv(spec.source_symbol, "1d", since=since_ms, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        last_batch_ts = batch[-1][0]
        next_since = last_batch_ts + 86_400_000
        if next_since <= since_ms or len(batch) < 1000:
            break
        since_ms = next_since
        if since_ms >= int(datetime.now(UTC).timestamp() * 1000):
            break

    if not all_rows:
        logger.warning(f"[binance] {spec.symbol}: no rows returned")
        return 0

    df = pl.DataFrame(
        all_rows,
        schema=["ts_ms", "open", "high", "low", "close", "volume"],
        orient="row",
    )
    df = df.unique(subset=["ts_ms"]).sort("ts_ms")
    df = df.with_columns(
        (pl.col("ts_ms") * 1000).cast(pl.Datetime("us")).alias("ts"),
        pl.lit(spec.symbol).alias("asset"),
        pl.lit("1d").alias("timeframe"),
        pl.lit("binance").alias("source"),
    )
    df = df.select(
        ["asset", "timeframe", "ts", "open", "high", "low", "close", "volume", "source"]
    )
    n = upsert_ohlcv(df)
    logger.info(f"[binance] {spec.symbol}: upserted {n} rows")
    return n
