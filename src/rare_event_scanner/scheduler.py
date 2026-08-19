from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from .config import settings
from .ingest import ingest_all
from .publisher import publish_all
from .scanners import scan_all


def run_cycle() -> dict:
    logger.info("=== cycle start ===")
    ingest_result = ingest_all(backfill_days=settings.backfill_days)
    logger.info(f"ingest: {ingest_result}")
    events = scan_all()
    logger.info(f"scanners produced {len(events)} candidate events")
    sent = publish_all(events)
    logger.info(f"publisher sent {sent} events")
    logger.info("=== cycle done ===")
    return {"ingest": ingest_result, "events": len(events), "sent": sent}


def run_forever() -> None:
    scheduler = BlockingScheduler(timezone="UTC")
    interval = settings.scan_interval_minutes
    logger.info(f"scheduling cycle every {interval}m")
    scheduler.add_job(
        run_cycle,
        CronTrigger(minute=f"*/{interval}" if interval < 60 else 0, hour="*"),
        id="rare_event_cycle",
        max_instances=1,
        coalesce=True,
    )
    run_cycle()
    scheduler.start()
