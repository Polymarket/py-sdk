from __future__ import annotations

from decimal import Decimal

from pydantic import AliasChoices, Field, field_validator

from polymarket.models._validators import parse_decimal_string
from polymarket.models.base import BaseModel
from polymarket.models.types import ClobAssetId, OrderSide


class LastTradePrice(BaseModel):
    price: Decimal
    side: OrderSide

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> object:
        return parse_decimal_string(value)


class LastTradePriceForToken(BaseModel):
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    token_id: ClobAssetId = Field(
        validation_alias=AliasChoices("asset_id", "token_id"),
        description="Deprecated: use asset_id. Retained for backward compatibility.",
    )
    price: Decimal
    side: OrderSide

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> object:
        return parse_decimal_string(value)


LastTradePriceForAsset = LastTradePriceForToken
"""Canonical name for an asset-specific last-trade price response."""


__all__ = ["LastTradePrice", "LastTradePriceForAsset", "LastTradePriceForToken"]
