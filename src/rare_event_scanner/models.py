from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RareEvent(BaseModel):
    """A rare market event ready for publishing."""

    event_type: str = Field(description="e.g. 'streak_up', 'streak_down', 'sigma_move'")
    asset: str
    asset_class: str
    timeframe: str = Field(description="e.g. '1d', '1h'")
    detected_at: datetime

    headline: str = Field(description="Ready-to-tweet one-liner.")
    description: str = Field(default="", description="Longer context, optional thread body.")

    rarity_percentile: float = Field(ge=0.0, le=100.0)
    historical_occurrences: int = Field(
        description="How many times this (or rarer) happened in full history."
    )
    history_span_days: int

    metrics: dict[str, Any] = Field(default_factory=dict)
    chart_data: dict[str, Any] | None = None

    def dedup_key(self) -> str:
        return f"{self.event_type}:{self.asset}:{self.timeframe}:{self.detected_at.date()}"
