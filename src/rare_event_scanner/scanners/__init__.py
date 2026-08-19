from ..config import DEFAULT_ASSETS, AssetSpec
from ..models import RareEvent
from .funding import scan_funding_extreme
from .sigma import scan_sigma
from .streak import scan_streaks


def scan_all(assets: list[AssetSpec] | None = None) -> list[RareEvent]:
    assets = assets or DEFAULT_ASSETS
    events: list[RareEvent] = []
    for spec in assets:
        events.extend(scan_streaks(spec))
        events.extend(scan_sigma(spec))
        events.extend(scan_funding_extreme(spec))
    events.sort(key=lambda e: e.rarity_percentile, reverse=True)
    return events


__all__ = [
    "scan_all",
    "scan_streaks",
    "scan_sigma",
    "scan_funding_extreme",
]
