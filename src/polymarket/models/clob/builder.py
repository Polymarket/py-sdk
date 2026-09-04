from __future__ import annotations

from datetime import datetime
from decimal import Decimal, DecimalException
from typing import Any, cast

from pydantic import AliasChoices, Field, computed_field, field_validator, model_validator

from polymarket.models._validators import parse_decimal_string
from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    _parse_epoch_or_iso_timestamp,  # pyright: ignore[reportPrivateUsage]
    _require_epoch_or_iso_timestamp,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.types import ClobAssetId, ConditionId, OrderSide

_BUILDER_FEES_BPS = Decimal(10_000)


class BuilderFeeRates(BaseModel):
    maker: Decimal = Field(validation_alias="builder_maker_fee_rate_bps")
    taker: Decimal = Field(validation_alias="builder_taker_fee_rate_bps")

    @model_validator(mode="before")
    @classmethod
    def _scale_bps(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(cast(dict[str, Any], value))
        for key in ("builder_maker_fee_rate_bps", "builder_taker_fee_rate_bps"):
            raw = data.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            if not isinstance(raw, int | float | str):
                continue
            try:
                data[key] = Decimal(str(raw)) / _BUILDER_FEES_BPS
            except DecimalException as error:
                raise ValueError(f"{key} is not a valid number: {raw!r}") from error
        return data


class BuilderTrade(BaseModel):
    id: str
    trade_type: str = Field(validation_alias="tradeType")
    taker_order_hash: str = Field(validation_alias="takerOrderHash")
    builder: str
    market: ConditionId = Field(
        description="Deprecated: use condition_id. Retained for backward compatibility."
    )
    condition_id: ConditionId = Field(
        validation_alias="market",
        description="Condition ID for the market associated with this trade.",
    )
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "assetId", "token_id"))
    side: OrderSide
    size: Decimal
    size_usdc: Decimal = Field(validation_alias="sizeUsdc")
    price: Decimal
    status: str
    outcome: str
    outcome_index: int = Field(validation_alias="outcomeIndex")
    owner: str
    maker: str
    transaction_hash: str = Field(validation_alias="transactionHash")
    matched_at: datetime = Field(validation_alias="matchTime")
    bucket_index: int = Field(validation_alias="bucketIndex")
    fee: Decimal
    fee_usdc: Decimal = Field(validation_alias="feeUsdc")
    error_msg: str | None = Field(default=None, validation_alias="err_msg")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("size", "size_usdc", "price", "fee", "fee_usdc", mode="before")
    @classmethod
    def _parse_decimal_fields(cls, value: object) -> object:
        return parse_decimal_string(value)

    @field_validator("matched_at", mode="before")
    @classmethod
    def _parse_matched_at(cls, value: object) -> object:
        return _require_epoch_or_iso_timestamp(value)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_optional_timestamps(cls, value: object) -> object:
        return _parse_epoch_or_iso_timestamp(value)


__all__ = ["BuilderFeeRates", "BuilderTrade"]
