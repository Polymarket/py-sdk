from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field, computed_field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.data.common import (
    datetime_from_epoch_seconds,
    decimal_from_number,
    optional_decimal_from_number,
    optional_outcome_index,
    optional_text,
)
from polymarket.models.types import (
    ClobAssetId,
    ConditionId,
    validate_optional_condition_id_response,
)
from polymarket.types import EvmAddress


class MarketLiveVolume(BaseModel):
    """Market taker volume in shares."""

    condition_id: ConditionId | None
    taker_volume: Decimal

    @field_validator("condition_id", mode="before")
    @classmethod
    def _parse_condition(cls, value: object) -> ConditionId | None:
        return validate_optional_condition_id_response(optional_text(value))

    _decimal_from_number = field_validator("taker_volume", mode="before")(decimal_from_number)


class LiveVolume(BaseModel):
    """Event taker volume in shares and its market breakdown."""

    taker_volume_total: Decimal
    markets: tuple[MarketLiveVolume, ...] = Field(validation_alias="conditions")

    _decimal_from_number = field_validator("taker_volume_total", mode="before")(decimal_from_number)


class OpenInterest(BaseModel):
    """Open interest in USDC; ``condition_id=None`` denotes global interest."""

    condition_id: ConditionId | None
    value: Decimal

    _decimal_from_number = field_validator("value", mode="before")(decimal_from_number)

    @field_validator("condition_id", mode="before")
    @classmethod
    def _parse_condition(cls, value: object) -> ConditionId | None:
        return None if value == "GLOBAL" else validate_optional_condition_id_response(value)


class Holder(BaseModel):
    """A holder. ``amount`` is shares; prices, cost, value and PnL are USDC."""

    wallet: EvmAddress = Field(validation_alias="proxy_wallet")
    asset_id: ClobAssetId = Field(validation_alias="token_id")
    amount: Decimal
    outcome_index: int | None = None
    display_username_public: bool
    verified: bool
    name: str | None = None
    pseudonym: str | None = None
    bio: str | None = None
    profile_image: str | None = None
    profile_image_optimized: str | None = None
    avg_price: Decimal | None = None
    entry_cost_usdc: Decimal | None = None
    current_price: Decimal | None = None
    current_value: Decimal | None = None
    realized_pnl: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    total_pnl: Decimal | None = None

    _decimal_from_number = field_validator("amount", mode="before")(decimal_from_number)

    _optional_outcome_index = field_validator("outcome_index", mode="before")(
        optional_outcome_index
    )

    _optional_text = field_validator(
        "name", "pseudonym", "bio", "profile_image", "profile_image_optimized", mode="before"
    )(optional_text)

    _optional_decimal_from_number = field_validator(
        "avg_price",
        "entry_cost_usdc",
        "current_price",
        "current_value",
        "realized_pnl",
        "unrealized_pnl",
        "total_pnl",
        mode="before",
    )(optional_decimal_from_number)

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""
        return self.asset_id


class MetaHolder(BaseModel):
    """Holders grouped by outcome asset."""

    asset_id: ClobAssetId = Field(validation_alias="token_id")
    holders: tuple[Holder, ...]

    @computed_field
    @property
    def token(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""
        return self.asset_id


class PriceHistoryPoint(BaseModel):
    """An historical price in USDC per share; resolution 0 denotes an exact tick."""

    timestamp: datetime
    price: Decimal
    resolution_seconds: int

    _datetime_from_epoch_seconds = field_validator("timestamp", mode="before")(
        datetime_from_epoch_seconds
    )

    _decimal_from_number = field_validator("price", mode="before")(decimal_from_number)

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr

        @safe_html_repr
        def render(self: PriceHistoryPoint) -> str:
            return card(
                "PriceHistoryPoint",
                rows=[("timestamp", self.timestamp.isoformat()), ("price", str(self.price))],
            )

        return render(self)


__all__ = [
    "MarketLiveVolume",
    "LiveVolume",
    "OpenInterest",
    "Holder",
    "MetaHolder",
    "PriceHistoryPoint",
]
