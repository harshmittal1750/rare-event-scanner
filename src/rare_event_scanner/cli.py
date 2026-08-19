import sys

import typer
from loguru import logger

from . import db, scheduler
from .config import DEFAULT_ASSETS, settings
from .ingest import ingest_all
from .publisher import publish_all
from .scanners import scan_all

app = typer.Typer(
    name="scanner",
    help="Rare event scanner — detect rare market events and publish them.",
    no_args_is_help=True,
)


def _configure_logger(level: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level, colorize=True)


@app.callback()
def _root(log_level: str = typer.Option("INFO", "--log-level")) -> None:
    _configure_logger(log_level)


@app.command()
def ingest(
    backfill_days: int = typer.Option(settings.backfill_days, "--backfill-days"),
) -> None:
    """Fetch OHLCV for all configured assets into DuckDB."""
    result = ingest_all(backfill_days=backfill_days)
    logger.info(f"done: {result}")


@app.command()
def scan(
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run"),
    limit: int = typer.Option(0, "--limit", help="Max events to publish (0 = all)."),
) -> None:
    """Scan for rare events using data already in DuckDB; publish via webhook."""
    if dry_run:
        settings.dry_run = True
    events = scan_all()
    logger.info(f"found {len(events)} events")
    for ev in events:
        logger.info(f"  [{ev.rarity_percentile:5.2f}%] {ev.headline}")
    sent = publish_all(events, limit=limit or None)
    logger.info(f"published {sent} events")


@app.command()
def cycle() -> None:
    """Run a full ingest → scan → publish cycle once."""
    scheduler.run_cycle()


@app.command()
def run() -> None:
    """Run forever, scanning on the configured interval."""
    scheduler.run_forever()


@app.command()
def stats() -> None:
    """Show DB stats."""
    db.stats()


@app.command()
def assets() -> None:
    """List configured assets."""
    for a in DEFAULT_ASSETS:
        logger.info(
            f"  {a.symbol:<6} class={a.asset_class:<10} source={a.source:<10} "
            f"src_symbol={a.source_symbol}"
        )


if __name__ == "__main__":
    app()
