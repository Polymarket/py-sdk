from __future__ import annotations

from decimal import Decimal

from pydantic import field_validator

from polymarket.models._validators import parse_decimal_string
from polymarket.models.base import BaseModel
from polymarket.models.types import OrderSide, TokenId


class LastTradePrice(BaseModel):
    price: Decimal
    side: OrderSide

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> object:
        return parse_decimal_string(value)


class LastTradePriceForToken(BaseModel):
    token_id: TokenId
    price: Decimal
    side: OrderSide

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> object:
        return parse_decimal_string(value)


__all__ = ["LastTradePrice", "LastTradePriceForToken"]
