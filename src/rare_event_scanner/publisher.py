import httpx
from loguru import logger

from .config import settings
from .db import record_published
from .models import RareEvent


def publish(event: RareEvent) -> bool:
    """Publish an event to insight-coin-ai. Returns True if a new event was sent."""
    payload = event.model_dump(mode="json")
    if not record_published(event.dedup_key(), payload):
        logger.debug(f"[publisher] skip — already sent: {event.dedup_key()}")
        return False

    if settings.dry_run or not settings.publisher_enabled:
        logger.info(f"[publisher] DRY RUN — {event.headline}")
        return True

    try:
        resp = httpx.post(
            settings.publisher_url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.publisher_token}"},
            timeout=20.0,
        )
        resp.raise_for_status()
        logger.info(
            f"[publisher] posted {event.event_type}/{event.asset} → "
            f"status {resp.status_code}"
        )
        return True
    except httpx.HTTPError as e:
        logger.error(f"[publisher] failed to post {event.dedup_key()}: {e}")
        return False


def publish_all(events: list[RareEvent], limit: int | None = None) -> int:
    if limit:
        events = events[:limit]
    sent = 0
    for ev in events:
        if publish(ev):
            sent += 1
    return sent
