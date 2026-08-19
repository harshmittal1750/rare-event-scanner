from ..config import DEFAULT_ASSETS, AssetSpec
from .binance_source import fetch_binance_daily
from .hyperliquid_source import fetch_hyperliquid_daily, fetch_hyperliquid_funding
from .yfinance_source import fetch_yfinance_daily


def ingest_all(assets: list[AssetSpec] | None = None, backfill_days: int = 3650) -> dict:
    assets = assets or DEFAULT_ASSETS
    totals = {"inserted_ohlcv": 0, "inserted_funding": 0, "errors": []}
    for spec in assets:
        try:
            if spec.source == "yfinance":
                totals["inserted_ohlcv"] += fetch_yfinance_daily(spec, backfill_days=backfill_days)
            elif spec.source == "binance":
                totals["inserted_ohlcv"] += fetch_binance_daily(spec, backfill_days=backfill_days)
            elif spec.source == "hyperliquid":
                totals["inserted_ohlcv"] += fetch_hyperliquid_daily(
                    spec, backfill_days=backfill_days
                )
                totals["inserted_funding"] += fetch_hyperliquid_funding(
                    spec, backfill_days=backfill_days
                )
            else:
                raise ValueError(f"unknown source {spec.source}")
        except Exception as e:
            totals["errors"].append(f"{spec.symbol}: {e}")
    return totals


__all__ = [
    "ingest_all",
    "fetch_yfinance_daily",
    "fetch_binance_daily",
    "fetch_hyperliquid_daily",
    "fetch_hyperliquid_funding",
]
