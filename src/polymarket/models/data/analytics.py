from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, Field, computed_field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.gamma.common import parse_optional_decimal
from polymarket.models.types import (
    ClobAssetId,
    ConditionId,
    validate_optional_condition_id,
)
from polymarket.types import EvmAddress

OpenInterestMarket = ConditionId | Literal["GLOBAL"]


class MarketVolume(BaseModel):
    condition_id: ConditionId | None = Field(default=None, validation_alias="market")
    market: ConditionId | None = Field(
        default=None, validation_alias="market", description="Deprecated: use condition_id."
    )
    value: Decimal | None = None

    @field_validator("condition_id", "market", mode="before")
    @classmethod
    def _validate_market(cls, value: object) -> ConditionId | None:
        return validate_optional_condition_id(value)

    @field_validator("value", mode="before")
    @classmethod
    def _parse_value(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class LiveVolume(BaseModel):
    total: Decimal | None = None
    markets: tuple[MarketVolume, ...] | None = None

    @field_validator("total", mode="before")
    @classmethod
    def _parse_total(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class OpenInterest(BaseModel):
    condition_id: OpenInterestMarket | None = Field(default=None, validation_alias="market")
    market: OpenInterestMarket | None = Field(
        default=None, description="Deprecated: use condition_id."
    )
    value: Decimal | None = None

    @field_validator("condition_id", "market", mode="before")
    @classmethod
    def _validate_market(cls, value: object) -> OpenInterestMarket | None:
        if value == "GLOBAL":
            return "GLOBAL"
        return validate_optional_condition_id(value)

    @field_validator("value", mode="before")
    @classmethod
    def _parse_value(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class Holder(BaseModel):
    wallet: EvmAddress | None = Field(default=None, validation_alias="proxyWallet")
    asset_id: ClobAssetId | None = Field(
        default=None,
        validation_alias=AliasChoices("asset_id", "asset", "token_id"),
    )
    amount: Decimal | None = None
    outcome_index: int | None = Field(default=None, validation_alias="outcomeIndex")
    name: str | None = None
    pseudonym: str | None = None
    bio: str | None = None
    display_username_public: bool | None = Field(
        default=None, validation_alias="displayUsernamePublic"
    )
    profile_image: str | None = Field(default=None, validation_alias="profileImage")
    profile_image_optimized: str | None = Field(
        default=None, validation_alias="profileImageOptimized"
    )

    @computed_field
    @property
    def token_id(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class MetaHolder(BaseModel):
    asset_id: ClobAssetId | None = Field(
        default=None, validation_alias=AliasChoices("asset_id", "token")
    )
    holders: tuple[Holder, ...] | None = None

    @computed_field
    @property
    def token(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id


__all__ = [
    "Holder",
    "LiveVolume",
    "MarketVolume",
    "MetaHolder",
    "OpenInterest",
]
