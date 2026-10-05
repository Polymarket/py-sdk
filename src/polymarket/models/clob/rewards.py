from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeAlias

from pydantic import AliasChoices, Field, computed_field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    _coerce_decimalish,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.types import ClobAssetId, ConditionId, validate_condition_id


def _from_epoch_ms(value: int) -> datetime:
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        msg = f"epoch-ms timestamp out of range: {value!r}"
        raise ValueError(msg) from error


def _parse_epoch_ms(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, bool):
        msg = f"expected an epoch-ms timestamp, got bool {value!r}"
        raise ValueError(msg)
    if isinstance(value, int):
        return _from_epoch_ms(value)
    if isinstance(value, str):
        if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            return _from_epoch_ms(int(value))
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError as error:
            msg = f"invalid epoch-ms or ISO timestamp: {value!r}"
            raise ValueError(msg) from error
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    msg = f"expected an epoch-ms timestamp, got {type(value).__name__}"
    raise ValueError(msg)


def _parse_optional_epoch_ms(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    return _parse_epoch_ms(value)


class CurrentRewardConfig(BaseModel):
    id: int | None = None
    asset_address: str = Field(validation_alias="asset_address")
    start_date: datetime = Field(validation_alias="start_date")
    end_date: datetime | None = Field(default=None, validation_alias="end_date")
    rate_per_day: Decimal = Field(validation_alias="rate_per_day")
    total_rewards: Decimal | None = Field(default=None, validation_alias="total_rewards")

    @field_validator("rate_per_day", "total_rewards", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("start_date", mode="before")
    @classmethod
    def _parse_start_date(cls, value: object) -> datetime:
        return _parse_epoch_ms(value)

    @field_validator("end_date", mode="before")
    @classmethod
    def _parse_end_date(cls, value: object) -> datetime | None:
        return _parse_optional_epoch_ms(value)


class CurrentReward(BaseModel):
    condition_id: ConditionId = Field(validation_alias="condition_id")
    rewards_max_spread: float | None = Field(default=None, validation_alias="rewards_max_spread")
    rewards_min_size: Decimal | None = Field(default=None, validation_alias="rewards_min_size")
    rewards_config: tuple[CurrentRewardConfig, ...] = Field(
        default=(), validation_alias="rewards_config"
    )
    sponsored_daily_rate: Decimal | None = Field(
        default=None, validation_alias="sponsored_daily_rate"
    )
    sponsors_count: int | None = Field(default=None, validation_alias="sponsors_count")
    native_daily_rate: Decimal | None = Field(default=None, validation_alias="native_daily_rate")
    total_daily_rate: Decimal | None = Field(default=None, validation_alias="total_daily_rate")

    @field_validator(
        "rewards_min_size",
        "sponsored_daily_rate",
        "native_daily_rate",
        "total_daily_rate",
        mode="before",
    )
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId:
        return validate_condition_id(value)


class MarketRewardConfig(BaseModel):
    asset_address: str = Field(validation_alias="asset_address")
    start_date: datetime = Field(validation_alias="start_date")
    end_date: datetime | None = Field(default=None, validation_alias="end_date")
    rate_per_day: Decimal = Field(validation_alias="rate_per_day")
    total_rewards: Decimal | None = Field(default=None, validation_alias="total_rewards")

    @field_validator("rate_per_day", "total_rewards", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("start_date", mode="before")
    @classmethod
    def _parse_start_date(cls, value: object) -> datetime:
        return _parse_epoch_ms(value)

    @field_validator("end_date", mode="before")
    @classmethod
    def _parse_end_date(cls, value: object) -> datetime | None:
        return _parse_optional_epoch_ms(value)


class MarketRewardToken(BaseModel):
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    outcome: str
    price: Decimal

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> object:
        return _coerce_decimalish(value)


class MarketReward(BaseModel):
    condition_id: ConditionId = Field(validation_alias="condition_id")
    question: str
    market_slug: str | None = Field(default=None, validation_alias="market_slug")
    event_slug: str | None = Field(default=None, validation_alias="event_slug")
    image: str | None = None
    rewards_max_spread: float | None = Field(default=None, validation_alias="rewards_max_spread")
    rewards_min_size: Decimal | None = Field(default=None, validation_alias="rewards_min_size")
    market_competitiveness: float | None = Field(
        default=None, validation_alias="market_competitiveness"
    )
    tokens: tuple[MarketRewardToken, ...]
    rewards_config: tuple[MarketRewardConfig, ...] = Field(
        default=(), validation_alias="rewards_config"
    )

    @field_validator("rewards_min_size", mode="before")
    @classmethod
    def _parse_rewards_min_size(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId:
        return validate_condition_id(value)


class UserEarning(BaseModel):
    asset_address: str = Field(validation_alias="asset_address")
    asset_rate: Decimal = Field(validation_alias="asset_rate")
    condition_id: ConditionId = Field(validation_alias="condition_id")
    date: datetime
    earnings: Decimal
    maker_address: str = Field(validation_alias="maker_address")

    @field_validator("asset_rate", "earnings", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("date", mode="before")
    @classmethod
    def _parse_date(cls, value: object) -> datetime:
        return _parse_epoch_ms(value)

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId:
        return validate_condition_id(value)


class TotalUserEarning(BaseModel):
    asset_address: str = Field(validation_alias="asset_address")
    asset_rate: Decimal = Field(validation_alias="asset_rate")
    date: datetime
    earnings: Decimal
    maker_address: str = Field(validation_alias="maker_address")

    @field_validator("asset_rate", "earnings", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("date", mode="before")
    @classmethod
    def _parse_date(cls, value: object) -> datetime:
        return _parse_epoch_ms(value)


class UserRewardsConfig(BaseModel):
    asset_address: str = Field(validation_alias="asset_address")
    end_date: datetime = Field(validation_alias="end_date")
    rate_per_day: Decimal = Field(validation_alias="rate_per_day")
    start_date: datetime = Field(validation_alias="start_date")
    total_rewards: Decimal = Field(validation_alias="total_rewards")

    @field_validator("rate_per_day", "total_rewards", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _parse_dates(cls, value: object) -> datetime:
        return _parse_epoch_ms(value)


class EarningBreakdown(BaseModel):
    asset_address: str = Field(validation_alias="asset_address")
    asset_rate: Decimal = Field(validation_alias="asset_rate")
    earnings: Decimal

    @field_validator("asset_rate", "earnings", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class UserRewardsEarning(BaseModel):
    condition_id: ConditionId = Field(validation_alias="condition_id")
    earning_percentage: float = Field(validation_alias="earning_percentage")
    earnings: tuple[EarningBreakdown, ...]
    event_slug: str = Field(validation_alias="event_slug")
    image: str
    maker_address: str = Field(validation_alias="maker_address")
    market_competitiveness: float = Field(validation_alias="market_competitiveness")
    market_slug: str = Field(validation_alias="market_slug")
    question: str
    rewards_config: tuple[UserRewardsConfig, ...] = Field(validation_alias="rewards_config")
    rewards_max_spread: float = Field(validation_alias="rewards_max_spread")
    rewards_min_size: Decimal = Field(validation_alias="rewards_min_size")
    tokens: tuple[MarketRewardToken, ...]

    @field_validator("rewards_min_size", mode="before")
    @classmethod
    def _parse_rewards_min_size(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId:
        return validate_condition_id(value)


RewardsPercentages: TypeAlias = dict[ConditionId, float]


__all__ = [
    "CurrentReward",
    "CurrentRewardConfig",
    "EarningBreakdown",
    "MarketReward",
    "MarketRewardConfig",
    "MarketRewardToken",
    "RewardsPercentages",
    "TotalUserEarning",
    "UserEarning",
    "UserRewardsConfig",
    "UserRewardsEarning",
]
