"""Experimental builder receipts; may change in any release, including patches."""

from datetime import datetime
from typing import Literal

from pydantic import field_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import _parse_event_horizon, _require_epoch_ms
from polymarket.models.perps.builders import PerpsBuilderEarning


class PerpsBuilderFillEvent(BaseModel):
    """Experimental: a batch of builder receipts; sequence numbers may skip values."""

    type: Literal["builder_fill"] = "builder_fill"
    channel: Literal["builderFills"] = "builderFills"
    event_timestamp: datetime | None
    """Newest reflected event time; None means the event horizon is unknown."""
    timestamp: datetime
    sequence: int
    payload: tuple[PerpsBuilderEarning, ...]

    @field_validator("event_timestamp", mode="before")
    @classmethod
    def _event_timestamp(cls, value: object) -> object:
        return None if value is None else _parse_event_horizon(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)
