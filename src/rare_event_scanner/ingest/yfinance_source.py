from datetime import UTC, datetime, timedelta

import polars as pl
import yfinance as yf
from loguru import logger

from ..config import AssetSpec
from ..db import latest_ts, upsert_ohlcv


def fetch_yfinance_daily(spec: AssetSpec, backfill_days: int = 3650) -> int:
    last_ts = latest_ts(spec.symbol, "1d")
    if last_ts is None:
        start = datetime.now(UTC) - timedelta(days=backfill_days)
        logger.info(f"[yf] {spec.symbol}: cold backfill from {start.date()}")
    else:
        start = last_ts - timedelta(days=5)
        logger.info(f"[yf] {spec.symbol}: incremental from {start.date()}")

    ticker = yf.Ticker(spec.source_symbol)
    df_pd = ticker.history(start=start.date().isoformat(), interval="1d", auto_adjust=False)
    if df_pd is None or df_pd.empty:
        logger.warning(f"[yf] {spec.symbol}: no rows returned")
        return 0

    df_pd = df_pd.reset_index()
    df = pl.from_pandas(df_pd)

    ts_col = "Date" if "Date" in df.columns else "Datetime"
    df = df.rename(
        {
            ts_col: "ts",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    df = df.with_columns(
        pl.col("ts").cast(pl.Datetime("us")),
        pl.lit(spec.symbol).alias("asset"),
        pl.lit("1d").alias("timeframe"),
        pl.lit("yfinance").alias("source"),
    )
    df = df.select(
        ["asset", "timeframe", "ts", "open", "high", "low", "close", "volume", "source"]
    )
    df = df.drop_nulls(subset=["close"])
    n = upsert_ohlcv(df)
    logger.info(f"[yf] {spec.symbol}: upserted {n} rows")
    return n
