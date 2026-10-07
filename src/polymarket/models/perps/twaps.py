"""Experimental active TWAP runs and acceptance receipts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, NewType

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    _require_epoch_ms,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.perps.types import PerpsInstrumentId, PerpsOrderId
from polymarket.models.types import OrderSide

PerpsTwapId = NewType("PerpsTwapId", int)


class PerpsTwapStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"


class PerpsTwapAccepted(BaseModel):
    """Acceptance receipt; the full quantity is not guaranteed to fill."""

    status: Literal["ok"]
    twap_id: PerpsTwapId = Field(validation_alias="twid", gt=0, le=2**53 - 1, strict=True)
    timestamp: datetime = Field(validation_alias="ts")

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return value if isinstance(value, datetime) else _require_epoch_ms(value)


class PerpsTwap(BaseModel):
    """An active run. Ended runs are absent from the active collection.

    Zero slippage uses the venue default (300 bps); zero price bounds are unset.
    """

    twap_id: PerpsTwapId = Field(validation_alias="twid", gt=0, le=2**53 - 1, strict=True)
    instrument_id: PerpsInstrumentId = Field(
        validation_alias="iid", ge=0, le=2**32 - 1, strict=True
    )
    side: OrderSide = Field(validation_alias="buy")
    quantity: Decimal = Field(validation_alias="qty", gt=0)
    filled_quantity: Decimal = Field(validation_alias="fill", ge=0)
    duration_ms: int = Field(validation_alias="dur", gt=0, strict=True)
    interval_ms: int = Field(validation_alias="ivl", gt=0, strict=True)
    randomize: bool = Field(validation_alias="rnd", strict=True)
    slippage_bps: int = Field(validation_alias="slip_bps", ge=0, le=10000, strict=True)
    min_price: Decimal = Field(validation_alias="min_px", ge=0)
    max_price: Decimal = Field(validation_alias="max_px", ge=0)
    reduce_only: bool = Field(validation_alias="ro", strict=True)
    status: PerpsTwapStatus = Field(validation_alias="st")
    slices: int = Field(ge=0, strict=True)
    slice_count: int = Field(gt=0, strict=True)
    started_at: datetime = Field(validation_alias="sts")
    ends_at: datetime = Field(validation_alias="ets")
    created_at: datetime = Field(validation_alias="cts")
    average_price: Decimal | None = Field(default=None, validation_alias="avg_px", ge=0)
    client_order_id: str | None = Field(
        default=None, validation_alias="coid", pattern=r"^[0-9a-f]{32}$"
    )
    order_id: PerpsOrderId | None = Field(
        default=None, validation_alias="oid", gt=0, le=2**53 - 1, strict=True
    )

    @field_validator("side", mode="before")
    @classmethod
    def _parse_side(cls, value: object) -> object:
        if value is True:
            return "BUY"
        if value is False:
            return "SELL"
        return value

    @field_validator("started_at", "ends_at", "created_at", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return value if isinstance(value, datetime) else _require_epoch_ms(value)


__all__ = ["PerpsTwap", "PerpsTwapAccepted", "PerpsTwapId", "PerpsTwapStatus"]
