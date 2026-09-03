from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, Field, computed_field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.gamma.common import (
    empty_string_to_none,
    parse_epoch_seconds_optional,
    parse_optional_date,
    parse_optional_decimal,
)
from polymarket.models.types import (
    ClobAssetId,
    ComboConditionId,
    ConditionId,
    PositionId,
    validate_combo_condition_id,
    validate_condition_id,
    validate_optional_condition_id,
)
from polymarket.types import EvmAddress

ComboPositionStatus = Literal[
    "OPEN", "PARTIAL", "RESOLVED_PARTIAL", "RESOLVED_WIN", "RESOLVED_LOSS"
]
ComboPositionOutcome = Literal["YES", "NO"]


class PortfolioValue(BaseModel):
    """Current portfolio value for a user."""

    user: EvmAddress | None = None
    value: Decimal | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _parse_value(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class TradedMarketCount(BaseModel):
    """Number of markets traded by a user."""

    user: EvmAddress | None = None
    traded: int | None = None


class Position(BaseModel):
    """Open market position held by a wallet."""

    condition_id: ConditionId = Field(validation_alias="conditionId")
    wallet: EvmAddress | None = Field(default=None, validation_alias="proxyWallet")
    asset_id: ClobAssetId | None = Field(
        default=None,
        validation_alias=AliasChoices("asset_id", "asset", "token_id"),
    )
    size: Decimal | None = None
    avg_price: Decimal | None = Field(default=None, validation_alias="avgPrice")
    initial_value: Decimal | None = Field(default=None, validation_alias="initialValue")
    current_value: Decimal | None = Field(default=None, validation_alias="currentValue")
    cash_pnl: Decimal | None = Field(default=None, validation_alias="cashPnl")
    percent_pnl: float | None = Field(default=None, validation_alias="percentPnl")
    total_bought: Decimal | None = Field(default=None, validation_alias="totalBought")
    realized_pnl: Decimal | None = Field(default=None, validation_alias="realizedPnl")
    percent_realized_pnl: float | None = Field(default=None, validation_alias="percentRealizedPnl")
    cur_price: Decimal | None = Field(default=None, validation_alias="curPrice")
    redeemable: bool | None = None
    mergeable: bool | None = None
    title: str | None = None
    slug: str | None = None
    icon: str | None = None
    event_id: str | None = Field(default=None, validation_alias="eventId")
    event_slug: str | None = Field(default=None, validation_alias="eventSlug")
    outcome: str | None = None
    outcome_index: int | None = Field(default=None, validation_alias="outcomeIndex")
    opposite_outcome: str | None = Field(default=None, validation_alias="oppositeOutcome")
    opposite_asset_id: ClobAssetId | None = Field(
        default=None,
        validation_alias=AliasChoices("opposite_asset_id", "oppositeAsset", "opposite_token_id"),
    )
    end_date: date | None = Field(default=None, validation_alias="endDate")
    negative_risk: bool | None = Field(default=None, validation_alias="negativeRisk")

    @computed_field
    @property
    def token_id(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @computed_field
    @property
    def opposite_token_id(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`opposite_asset_id`."""

        return self.opposite_asset_id

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId:
        return validate_condition_id(value)

    @field_validator(
        "size",
        "avg_price",
        "initial_value",
        "current_value",
        "cash_pnl",
        "total_bought",
        "realized_pnl",
        "cur_price",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)

    @field_validator("end_date", mode="before")
    @classmethod
    def _parse_end_date(cls, value: object) -> date | None:
        return parse_optional_date(value)

    @field_validator("icon", mode="before")
    @classmethod
    def _normalize_icon(cls, value: object) -> object | None:
        return empty_string_to_none(value)

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: Position) -> str:
            label = self.title or truncate_mid(self.condition_id)
            title = f"Position  ·  {label}"
            rows: list[tuple[str, str]] = []
            if self.outcome:
                rows.append(("side", self.outcome))
            if self.size is not None:
                rows.append(("size", str(self.size)))
            if self.avg_price is not None:
                rows.append(("avg_price", str(self.avg_price)))
            if self.cur_price is not None:
                rows.append(("current", str(self.cur_price)))
            if self.cash_pnl is not None:
                rows.append(("pnl", str(self.cash_pnl)))
            return card(title, rows=rows)

        return render(self)


class ClosedPosition(BaseModel):
    """Closed market position for a wallet."""

    wallet: EvmAddress | None = Field(default=None, validation_alias="proxyWallet")
    asset_id: ClobAssetId | None = Field(
        default=None,
        validation_alias=AliasChoices("asset_id", "asset", "token_id"),
    )
    condition_id: ConditionId | None = Field(default=None, validation_alias="conditionId")
    avg_price: Decimal | None = Field(default=None, validation_alias="avgPrice")
    total_bought: Decimal | None = Field(default=None, validation_alias="totalBought")
    realized_pnl: Decimal | None = Field(default=None, validation_alias="realizedPnl")
    cur_price: Decimal | None = Field(default=None, validation_alias="curPrice")
    timestamp: datetime | None = None
    title: str | None = None
    slug: str | None = None
    icon: str | None = None
    event_slug: str | None = Field(default=None, validation_alias="eventSlug")
    outcome: str | None = None
    outcome_index: int | None = Field(default=None, validation_alias="outcomeIndex")
    opposite_outcome: str | None = Field(default=None, validation_alias="oppositeOutcome")
    opposite_asset_id: ClobAssetId | None = Field(
        default=None,
        validation_alias=AliasChoices("opposite_asset_id", "oppositeAsset", "opposite_token_id"),
    )
    end_date: date | None = Field(default=None, validation_alias="endDate")

    @computed_field
    @property
    def token_id(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @computed_field
    @property
    def opposite_token_id(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`opposite_asset_id`."""

        return self.opposite_asset_id

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId | None:
        return validate_optional_condition_id(value)

    @field_validator(
        "avg_price",
        "total_bought",
        "realized_pnl",
        "cur_price",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime | None:
        return parse_epoch_seconds_optional(value)

    @field_validator("end_date", mode="before")
    @classmethod
    def _parse_end_date(cls, value: object) -> date | None:
        return parse_optional_date(value)

    @field_validator("icon", mode="before")
    @classmethod
    def _normalize_icon(cls, value: object) -> object | None:
        return empty_string_to_none(value)


class ComboPositionMarketEvent(BaseModel):
    event_id: str | None = None
    event_slug: str | None = None
    event_title: str | None = None
    event_image: str | None = None


class ComboPositionMarket(BaseModel):
    market_id: str | None = None
    slug: str | None = None
    title: str | None = None
    outcome: str | None = None
    image_url: str | None = None
    icon_url: str | None = None
    category: str | None = None
    subcategory: str | None = None
    tags: tuple[str, ...] | None = None
    end_date: datetime | None = None
    event: ComboPositionMarketEvent | None = None


class ComboPositionLeg(BaseModel):
    leg_index: int
    leg_position_id: PositionId
    leg_condition_id: ConditionId
    leg_outcome_index: int
    leg_outcome_label: str | None = None
    leg_status: ComboPositionStatus
    leg_resolved_at: datetime | None = None
    leg_current_price: Decimal | None = None
    market: ComboPositionMarket | None = None

    @field_validator("leg_condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId:
        return validate_condition_id(value)

    @field_validator("leg_current_price", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class ComboPosition(BaseModel):
    condition_id: ComboConditionId = Field(validation_alias="combo_condition_id")
    position_id: PositionId = Field(validation_alias="combo_position_id")
    outcome: ComboPositionOutcome = Field(validation_alias="side")
    module_id: int = Field(validation_alias="module_id")
    wallet: EvmAddress = Field(validation_alias="user_address")
    shares: Decimal = Field(validation_alias="shares_balance")
    entry_avg_price_usdc: Decimal | None = None
    entry_cost_usdc: Decimal | None = None
    realized_payout_usdc: Decimal | None = None
    total_cost_usdc: Decimal | None = None
    status: ComboPositionStatus
    redeemable: bool
    first_entry_at: datetime
    resolved_at: datetime | None = None
    updated_at: datetime | None = None
    legs_total: int
    legs_resolved: int
    legs_pending: int
    legs: tuple[ComboPositionLeg, ...]

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ComboConditionId:
        return validate_combo_condition_id(value)

    @field_validator(
        "shares",
        "entry_avg_price_usdc",
        "entry_cost_usdc",
        "realized_payout_usdc",
        "total_cost_usdc",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


__all__ = [
    "ClosedPosition",
    "ComboPosition",
    "ComboPositionOutcome",
    "ComboPositionLeg",
    "ComboPositionMarket",
    "ComboPositionMarketEvent",
    "ComboPositionStatus",
    "PortfolioValue",
    "Position",
    "TradedMarketCount",
]
