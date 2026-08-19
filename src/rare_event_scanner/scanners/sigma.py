from datetime import UTC, datetime

import polars as pl
from loguru import logger

from ..config import AssetSpec, settings
from ..db import load_ohlcv
from ..models import RareEvent

ROLLING_WINDOW = 252  # ~1 trading year
MIN_ABS_Z = 2.0


def _percentile_rank(sample: float, population: list[float]) -> float:
    if not population:
        return 0.0
    under = sum(1 for x in population if x < sample)
    return 100.0 * under / len(population)


def _format_history_span(days: int) -> str:
    years = days / 365.25
    if years >= 50:
        return f"in {int(years)} years of history"
    if years >= 2:
        return f"in {years:.1f} years of history"
    return f"in {days} trading days of history"


def scan_sigma(spec: AssetSpec) -> list[RareEvent]:
    df = load_ohlcv(spec.symbol, "1d")
    if df.is_empty() or df.height < ROLLING_WINDOW + 10:
        logger.debug(f"[sigma] {spec.symbol}: insufficient data ({df.height} rows)")
        return []

    df = df.sort("ts").with_columns(
        pl.col("close").pct_change().alias("ret"),
    )
    df = df.with_columns(
        pl.col("ret").rolling_mean(window_size=ROLLING_WINDOW, min_samples=ROLLING_WINDOW)
            .alias("mean_ret"),
        pl.col("ret").rolling_std(window_size=ROLLING_WINDOW, min_samples=ROLLING_WINDOW)
            .alias("std_ret"),
    )
    df = df.with_columns(
        ((pl.col("ret") - pl.col("mean_ret")) / pl.col("std_ret")).alias("z"),
    )
    df = df.drop_nulls(subset=["z"])
    if df.is_empty():
        return []

    latest = df.tail(1)
    current_z = float(latest["z"][0])
    current_ret = float(latest["ret"][0])
    current_close = float(latest["close"][0])

    if abs(current_z) < MIN_ABS_Z:
        logger.debug(f"[sigma] {spec.symbol}: |z|={abs(current_z):.2f} < {MIN_ABS_Z} (quiet day)")
        return []

    abs_z_history = df["z"].abs().to_list()[:-1]
    pct = _percentile_rank(abs(current_z), abs_z_history)

    higher_or_equal = sum(1 for z in abs_z_history if z >= abs(current_z))

    if pct < settings.rarity_threshold:
        logger.debug(
            f"[sigma] {spec.symbol}: |z|={abs(current_z):.2f} at pct {pct:.1f} — below threshold"
        )
        return []

    direction_word = "gain" if current_ret > 0 else "drop"
    sign = "+" if current_ret > 0 else ""
    event_type = "sigma_up" if current_ret > 0 else "sigma_down"
    history_span_days = (df["ts"].max() - df["ts"].min()).days

    if higher_or_equal == 0:
        rarity_phrase = f"the largest {direction_word} {_format_history_span(history_span_days)}"
    else:
        rarity_phrase = (
            f"only {higher_or_equal} larger {direction_word}s "
            f"{_format_history_span(history_span_days)}"
        )

    headline = (
        f"🚨 ${spec.symbol} just had a {abs(current_z):.1f}σ {direction_word} "
        f"({sign}{current_ret * 100:.2f}%) — {rarity_phrase}."
    )

    tail = df.tail(60)
    chart_data = {
        "timestamps": [t.isoformat() for t in tail["ts"].to_list()],
        "closes": tail["close"].to_list(),
    }

    event = RareEvent(
        event_type=event_type,
        asset=spec.symbol,
        asset_class=spec.asset_class,
        timeframe="1d",
        detected_at=datetime.now(UTC),
        headline=headline,
        description=(
            f"{spec.symbol} closed {sign}{current_ret * 100:.2f}% on the day. "
            f"Rolling {ROLLING_WINDOW}d z-score: {current_z:.2f}. "
            f"In the {pct:.2f}th percentile of |z| values across "
            f"{history_span_days} days of history."
        ),
        rarity_percentile=pct,
        historical_occurrences=higher_or_equal,
        history_span_days=history_span_days,
        metrics={
            "z_score": current_z,
            "return_pct": current_ret * 100,
            "close": current_close,
            "rolling_window": ROLLING_WINDOW,
        },
        chart_data=chart_data,
    )
    logger.info(f"[sigma] {spec.symbol}: emitting — {headline}")
    return [event]
