from __future__ import annotations

from pydantic import Field

from polymarket.models.base import BaseModel
from polymarket.models.types import OrderId


class CancelOrdersResponse(BaseModel):
    canceled: tuple[OrderId, ...]
    not_canceled: dict[OrderId, str] = Field(
        default_factory=dict[OrderId, str], validation_alias="not_canceled"
    )


__all__ = ["CancelOrdersResponse"]
