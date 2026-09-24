"""Experimental builder receipts; may change in any release, including patches."""

from datetime import datetime
from typing import Literal

from pydantic import field_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import _require_epoch_ms
from polymarket.models.perps.builders import PerpsBuilderEarning
from polymarket.models.perps.events import PerpsResyncEvent


class PerpsBuilderFillEvent(BaseModel):
    """Experimental: a batch of builder receipts; engine sequences may be sparse."""

    type: Literal["builder_fill"] = "builder_fill"
    channel: Literal["builderFills"] = "builderFills"
    timestamp: datetime
    sequence: int
    payload: tuple[PerpsBuilderEarning, ...]

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


PerpsBuilderFillsEvent = PerpsBuilderFillEvent | PerpsResyncEvent
"""Experimental: live builder receipts or a signal to reconcile earnings history."""
