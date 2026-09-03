from __future__ import annotations

from decimal import Decimal

from pydantic import AliasChoices, Field, computed_field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.gamma.common import parse_optional_decimal
from polymarket.models.types import ClobAssetId, ConditionId, validate_optional_condition_id
from polymarket.types import EvmAddress


class MarketPosition(BaseModel):
    wallet: EvmAddress | None = Field(default=None, validation_alias="proxyWallet")
    name: str | None = None
    profile_image: str | None = Field(default=None, validation_alias="profileImage")
    verified: bool | None = None
    asset_id: ClobAssetId | None = Field(
        default=None,
        validation_alias=AliasChoices("asset_id", "asset", "token_id"),
    )
    condition_id: ConditionId | None = Field(default=None, validation_alias="conditionId")
    avg_price: Decimal | None = Field(default=None, validation_alias="avgPrice")
    size: Decimal | None = None
    cur_price: Decimal | None = Field(default=None, validation_alias="currPrice")
    current_value: Decimal | None = Field(default=None, validation_alias="currentValue")
    cash_pnl: Decimal | None = Field(default=None, validation_alias="cashPnl")
    total_bought: Decimal | None = Field(default=None, validation_alias="totalBought")
    realized_pnl: Decimal | None = Field(default=None, validation_alias="realizedPnl")
    total_pnl: Decimal | None = Field(default=None, validation_alias="totalPnl")
    outcome: str | None = None
    outcome_index: int | None = Field(default=None, validation_alias="outcomeIndex")

    @computed_field
    @property
    def token_id(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId | None:
        return validate_optional_condition_id(value)

    @field_validator(
        "avg_price",
        "size",
        "cur_price",
        "current_value",
        "cash_pnl",
        "total_bought",
        "realized_pnl",
        "total_pnl",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class MetaMarketPosition(BaseModel):
    asset_id: ClobAssetId | None = Field(
        default=None, validation_alias=AliasChoices("asset_id", "token")
    )
    positions: tuple[MarketPosition, ...] | None = None

    @computed_field
    @property
    def token(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id


__all__ = ["MarketPosition", "MetaMarketPosition"]
