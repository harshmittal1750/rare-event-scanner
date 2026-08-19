from datetime import UTC, datetime

import polars as pl
from loguru import logger

from ..config import AssetSpec, settings
from ..db import load_funding
from ..models import RareEvent

HL_VENUE = "hyperliquid"
HOURS_PER_YEAR = 24 * 365


def _percentile_rank(sample: float, population: list[float]) -> float:
    if not population:
        return 0.0
    under = sum(1 for x in population if x < sample)
    return 100.0 * under / len(population)


def _format_history_days(days: int) -> str:
    if days >= 365:
        return f"in {days / 365.25:.1f} years of funding history"
    return f"in {days} days of funding history"


def scan_funding_extreme(spec: AssetSpec) -> list[RareEvent]:
    if spec.source != "hyperliquid":
        return []

    df = load_funding(spec.symbol, HL_VENUE)
    if df.is_empty() or df.height < 200:
        logger.debug(f"[funding] {spec.symbol}: insufficient rows ({df.height})")
        return []

    df = df.sort("ts").drop_nulls(subset=["rate"])
    latest = df.tail(1)
    current_rate = float(latest["rate"][0])
    current_annualized = current_rate * HOURS_PER_YEAR

    history = df["rate"].abs().to_list()[:-1]
    abs_current = abs(current_rate)
    pct = _percentile_rank(abs_current, history)
    higher_or_equal = sum(1 for r in history if r >= abs_current)

    # Absolute floor: skip tiny rates even if technically rare (very early history).
    if abs(current_annualized) < 0.30:  # 30% annualized
        logger.debug(
            f"[funding] {spec.symbol}: annualized={current_annualized * 100:.1f}% "
            f"below 30% floor — skipping"
        )
        return []
    if pct < settings.rarity_threshold:
        logger.debug(
            f"[funding] {spec.symbol}: |rate|={abs_current:.6f} "
            f"(annualized {current_annualized * 100:.1f}%) at pct {pct:.2f} — below threshold"
        )
        return []

    direction = "long-squeezing" if current_rate > 0 else "short-squeezing"
    sign = "+" if current_rate > 0 else ""
    event_type = "funding_long_extreme" if current_rate > 0 else "funding_short_extreme"

    history_days = (df["ts"].max() - df["ts"].min()).days or 1

    if higher_or_equal == 0:
        rarity_phrase = f"the most extreme reading {_format_history_days(history_days)}"
    else:
        rarity_phrase = (
            f"only {higher_or_equal} more extreme readings "
            f"{_format_history_days(history_days)}"
        )

    headline = (
        f"🚨 ${spec.symbol} funding on Hyperliquid hit "
        f"{sign}{current_rate * 100:.4f}%/hr ({sign}{current_annualized * 100:.0f}% annualized) "
        f"— {direction}. {rarity_phrase}."
    )

    tail = df.tail(72)
    chart_data = {
        "timestamps": [t.isoformat() for t in tail["ts"].to_list()],
        "rates": tail["rate"].to_list(),
    }

    event = RareEvent(
        event_type=event_type,
        asset=spec.symbol,
        asset_class=spec.asset_class,
        timeframe="1h",
        detected_at=datetime.now(UTC),
        headline=headline,
        description=(
            f"{spec.symbol} funding rate on Hyperliquid: {sign}{current_rate * 100:.4f}% per hour "
            f"({sign}{current_annualized * 100:.1f}% annualized). "
            f"{pct:.2f}th percentile of |rate| over {history_days} days."
        ),
        rarity_percentile=pct,
        historical_occurrences=higher_or_equal,
        history_span_days=history_days,
        metrics={
            "rate_per_hour": current_rate,
            "annualized_pct": current_annualized * 100,
            "venue": HL_VENUE,
        },
        chart_data=chart_data,
    )
    logger.info(f"[funding] {spec.symbol}: emitting — {headline}")
    return [event]
