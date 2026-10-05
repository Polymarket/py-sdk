"""Experimental running chases and acceptance receipts."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, NewType

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    _require_epoch_ms,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.perps.types import PerpsInstrumentId, PerpsOrderId
from polymarket.models.types import OrderSide

PerpsChaseId = NewType("PerpsChaseId", int)


class PerpsChaseAccepted(BaseModel):
    """Acceptance receipt; does not guarantee a resting child or a fill."""

    status: Literal["ok"]
    chase_id: PerpsChaseId = Field(validation_alias="chid", gt=0, le=2**53 - 1, strict=True)
    timestamp: datetime = Field(validation_alias="ts")

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return value if isinstance(value, datetime) else _require_epoch_ms(value)


class PerpsChase(BaseModel):
    """A running chase with zero bounds meaning unset.

    The reference price is zero before its first resting child.
    """

    chase_id: PerpsChaseId = Field(validation_alias="chid", gt=0, le=2**53 - 1, strict=True)
    instrument_id: PerpsInstrumentId = Field(
        validation_alias="iid", ge=0, le=2**32 - 1, strict=True
    )
    side: OrderSide = Field(validation_alias="buy")
    quantity: Decimal = Field(validation_alias="qty", gt=0)
    filled_quantity: Decimal = Field(validation_alias="fill", ge=0)
    limit_price: Decimal = Field(validation_alias="lim", ge=0)
    max_distance: Decimal = Field(validation_alias="max_dist", ge=0)
    max_distance_bps: int = Field(validation_alias="max_dist_bps", ge=0, le=1000, strict=True)
    post_only: bool = Field(validation_alias="po", strict=True)
    reduce_only: bool = Field(validation_alias="ro", strict=True)
    reference_price: Decimal = Field(ge=0)
    reprices: int = Field(ge=0, strict=True)
    post_only_rejections: int = Field(ge=0, strict=True)
    created_at: datetime = Field(validation_alias="cts")
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

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return value if isinstance(value, datetime) else _require_epoch_ms(value)


__all__ = ["PerpsChase", "PerpsChaseAccepted", "PerpsChaseId"]
