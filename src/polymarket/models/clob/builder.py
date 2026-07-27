from __future__ import annotations

from decimal import Decimal, DecimalException
from typing import Any, cast

from pydantic import Field, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    EpochOrIsoTimestamp,
    RequiredEpochOrIsoTimestamp,
    _DecimalFromString,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.types import CtfConditionId, OrderSide, TokenId

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
    market: CtfConditionId = Field(
        description="Deprecated: use condition_id. Retained for backward compatibility."
    )
    condition_id: CtfConditionId = Field(
        validation_alias="market",
        description="CTF condition id for the market associated with this trade.",
    )
    token_id: TokenId = Field(validation_alias="assetId")
    side: OrderSide
    size: _DecimalFromString
    size_usdc: _DecimalFromString = Field(validation_alias="sizeUsdc")
    price: _DecimalFromString
    status: str
    outcome: str
    outcome_index: int = Field(validation_alias="outcomeIndex")
    owner: str
    maker: str
    transaction_hash: str = Field(validation_alias="transactionHash")
    matched_at: RequiredEpochOrIsoTimestamp = Field(validation_alias="matchTime")
    bucket_index: int = Field(validation_alias="bucketIndex")
    fee: _DecimalFromString
    fee_usdc: _DecimalFromString = Field(validation_alias="feeUsdc")
    error_msg: str | None = Field(default=None, validation_alias="err_msg")
    created_at: EpochOrIsoTimestamp = Field(default=None, validation_alias="createdAt")
    updated_at: EpochOrIsoTimestamp = Field(default=None, validation_alias="updatedAt")


__all__ = ["BuilderFeeRates", "BuilderTrade"]
