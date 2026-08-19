from datetime import UTC, datetime

import polars as pl
from loguru import logger

from ..config import AssetSpec, settings
from ..db import load_ohlcv
from ..models import RareEvent


def _streak_lengths(directions: pl.Series) -> tuple[list[int], list[int]]:
    """Given a Series of daily directions (+1/0/-1), return (up_lengths, down_lengths)
    for every COMPLETED streak (plus the tail/current run included)."""
    ups: list[int] = []
    downs: list[int] = []
    run = 0
    run_sign = 0
    for v in directions.to_list():
        if v == 0:
            if run > 0:
                if run_sign > 0:
                    ups.append(run)
                else:
                    downs.append(run)
            run = 0
            run_sign = 0
            continue
        if v == run_sign:
            run += 1
        else:
            if run > 0:
                (ups if run_sign > 0 else downs).append(run)
            run = 1
            run_sign = v
    if run > 0:
        (ups if run_sign > 0 else downs).append(run)
    return ups, downs


def _current_run(directions: pl.Series) -> tuple[int, int]:
    """Return (length, sign) of the run at the end of the series. sign=+1/-1, length>=1."""
    vals = directions.to_list()
    if not vals:
        return 0, 0
    sign = 0
    length = 0
    for v in reversed(vals):
        if v == 0:
            break
        if sign == 0:
            sign = v
            length = 1
        elif v == sign:
            length += 1
        else:
            break
    return length, sign


def _percentile_rank(sample: int, population: list[int]) -> float:
    """Return percent of population values strictly less than sample. 100 = rarest."""
    if not population:
        return 0.0
    under = sum(1 for x in population if x < sample)
    return 100.0 * under / len(population)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_history_span(days: int) -> str:
    years = days / 365.25
    if years >= 50:
        return f"in {int(years)} years of history"
    if years >= 2:
        return f"in {years:.1f} years of history"
    return f"in {days} trading days of history"


def _make_headline(
    spec: AssetSpec,
    direction_word: str,
    length: int,
    historical_occurrences: int,
    history_span_days: int,
) -> str:
    symbol = f"${spec.symbol}"
    base = f"🚨 {symbol} just posted its {_ordinal(length)} consecutive {direction_word} day"
    if historical_occurrences == 0:
        return f"{base} — a new record {_format_history_span(history_span_days)}."
    return (
        f"{base} — only happened {historical_occurrences} other times "
        f"{_format_history_span(history_span_days)}."
    )


def scan_streaks(spec: AssetSpec) -> list[RareEvent]:
    df = load_ohlcv(spec.symbol, "1d")
    if df.is_empty() or df.height < 30:
        logger.debug(f"[streak] {spec.symbol}: insufficient data ({df.height} rows)")
        return []

    df = df.sort("ts").with_columns(
        pl.col("close").diff().sign().cast(pl.Int8).alias("dir"),
    )
    df = df.drop_nulls(subset=["dir"])
    directions = df["dir"]

    current_length, current_sign = _current_run(directions)
    if current_length < 3 or current_sign == 0:
        return []

    ups, downs = _streak_lengths(directions)
    population = ups if current_sign > 0 else downs
    pct = _percentile_rank(current_length, population)

    historical_occurrences = sum(1 for x in population if x >= current_length) - 1
    historical_occurrences = max(0, historical_occurrences)

    if pct < settings.rarity_threshold:
        logger.debug(
            f"[streak] {spec.symbol}: current run {current_length} "
            f"({'up' if current_sign > 0 else 'down'}) at pct {pct:.1f} — below threshold"
        )
        return []

    direction_word = "green" if current_sign > 0 else "red"
    event_type = f"streak_{'up' if current_sign > 0 else 'down'}"
    history_span_days = (df["ts"].max() - df["ts"].min()).days

    headline = _make_headline(
        spec, direction_word, current_length, historical_occurrences, history_span_days
    )

    tail = df.tail(current_length + 5)
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
            f"{spec.symbol} closed {direction_word} {current_length} sessions in a row. "
            f"Across {history_span_days} days of history, this run is in the "
            f"{pct:.2f}th percentile — {historical_occurrences} prior runs matched or exceeded it."
        ),
        rarity_percentile=pct,
        historical_occurrences=historical_occurrences,
        history_span_days=history_span_days,
        metrics={
            "streak_length": current_length,
            "direction": "up" if current_sign > 0 else "down",
            "last_close": float(df["close"][-1]),
            "pct_since_streak_start": (
                float(df["close"][-1]) / float(df["close"][-current_length - 1]) - 1
            )
            * 100,
        },
        chart_data=chart_data,
    )
    logger.info(f"[streak] {spec.symbol}: emitting — {headline}")
    return [event]
