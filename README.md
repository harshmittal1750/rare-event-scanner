# rare-event-scanner

Scans daily OHLCV across stocks, crypto, commodities, and macro for **statistically rare events** — streaks, extreme moves, volume blowouts, correlation breakdowns — and POSTs them to a publisher service (e.g. `insight-coin-ai`) which tweets them.

Designed to produce viral "JUST IN — longest streak since ____" style posts, auto-generated 24/7.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Runtime | Python 3.12 | Best-in-class numerical ecosystem |
| Data frames | **Polars** | 10–100× faster than pandas on larger data |
| Storage | **DuckDB** (embedded) | No server needed; SQL on millions of OHLCV rows instantly |
| Crypto source | **ccxt** | Unified API across 100+ exchanges |
| Stocks/macro source | **yfinance** | Free, covers indices/commodities/forex |
| Config | **pydantic-settings** | Type-safe env-driven config |
| HTTP | **httpx** | Modern, sync/async |
| Scheduler | **APScheduler** | In-process cron, no extra infra |
| Logging | **loguru** | Zero-config structured logs |
| CLI | **typer** | Type-hinted CLI from the FastAPI author |
| Lint/format | **ruff** | Rust-based, replaces black + flake8 + isort |
| Package mgr | **uv** | 10–100× faster than pip/poetry |

## Install

```bash
cd /Users/harshmittal/Documents/rare-event-scanner
uv sync
cp .env.example .env
```

Edit `.env` — most important setting is `RARITY_THRESHOLD` (default 99.0 = top 1% events only).

## CLI

```bash
uv run scanner assets          # list configured assets
uv run scanner ingest          # backfill OHLCV (BACKFILL_DAYS)
uv run scanner ingest --backfill-days 90   # shorter backfill for testing
uv run scanner scan --dry-run              # scan without POSTing
uv run scanner cycle                        # one full ingest → scan → publish
uv run scanner run                          # start scheduler, run forever
uv run scanner stats                        # DB stats
```

## How it works

1. **Ingest** — OHLCV per asset (yfinance for stocks/indices/commodities/FX, ccxt/Binance for crypto) goes into DuckDB. Incremental refresh on each cycle.
2. **Scan** — each scanner loads historical data and returns `RareEvent` objects with a `rarity_percentile` (0–100, higher = rarer).
3. **Filter** — only events at/above `RARITY_THRESHOLD` pass.
4. **Dedup** — a local `published_events` table stops re-posting the same event (keyed on `event_type:asset:timeframe:date`).
5. **Publish** — POSTs a structured JSON payload to `PUBLISHER_URL` with a bearer token.

### Current scanners

- **streak** — longest consecutive up/down closes vs. full history percentile
- **sigma** — N-sigma daily return events (`|z-score|` vs 252-day rolling window, ranked against full |z| history)
- **funding_extreme** — Hyperliquid hourly funding rate extremes (abs rate percentile, floored at 30% annualized)

### Current sources

- **yfinance** — US stocks, indices, commodities, FX (daily OHLCV)
- **binance** — crypto spot via ccxt (daily OHLCV)
- **hyperliquid** — crypto perps OHLCV (daily) + funding rates (hourly)

### Event payload (what the publisher receives)

```json
{
  "event_type": "streak_up",
  "asset": "NDX",
  "asset_class": "index",
  "timeframe": "1d",
  "detected_at": "2026-04-19T12:00:00Z",
  "headline": "🚨 $NDX just posted its 13th consecutive green day — a new record in 25.3 years of history.",
  "description": "NDX closed green 13 sessions in a row. Across 9,234 days of history, this run is in the 99.98th percentile — 0 prior runs matched or exceeded it.",
  "rarity_percentile": 99.98,
  "historical_occurrences": 0,
  "history_span_days": 9234,
  "metrics": { "streak_length": 13, "direction": "up", "last_close": 20512.33, "pct_since_streak_start": 4.2 },
  "chart_data": { "timestamps": ["..."], "closes": [...] }
}
```

## Publisher integration (insight-coin-ai)

A matching `POST /api/rare-event` endpoint lives in `insight-coin-ai`. Set `PUBLISHER_TOKEN` in both services to the same value. Set `RARE_EVENT_DRY_RUN=true` in insight-coin-ai to preview without actually tweeting.

## Adding a new scanner

1. Create `src/rare_event_scanner/scanners/<name>.py` exposing `scan_<name>(spec: AssetSpec) -> list[RareEvent]`.
2. Call it from `scanners/__init__.py` inside `scan_all`.
3. Done. Rarity filtering, dedup, and publishing are shared.

## Roadmap

- `volume_spike` — highest volume in X years
- `correlation_break` — assets that always move together, now diverging
- `ratio_extreme` — BTC.D, ETH/BTC, gold/silver at extremes
- `liquidation_record` — Hyperliquid liquidation cascade events
- `funding_cross_venue` — funding divergence Binance vs. Hyperliquid vs. dYdX
- `oi_spike` — open interest % change records on Hyperliquid
