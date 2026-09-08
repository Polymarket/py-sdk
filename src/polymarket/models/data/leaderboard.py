from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.data.common import (
    datetime_from_epoch_or_iso,
    decimal_from_number,
    optional_text,
)
from polymarket.models.types import (
    ClobAssetId,
    ComboConditionId,
    ConditionId,
    EventId,
    PositionId,
    validate_combo_condition_id,
    validate_condition_id_response,
)
from polymarket.types import EvmAddress, HexString


class TraderLeaderboardEntry(BaseModel):
    """A ranked trader; PnL is USDC and volume is shares."""

    rank: int
    wallet: EvmAddress = Field(validation_alias="user_id")
    pnl: Decimal
    volume: Decimal
    user_name: str | None = None
    profile_image: str | None = None
    x_username: str | None = None
    verified: bool

    _decimal_from_number = field_validator("pnl", "volume", mode="before")(decimal_from_number)

    _optional_text = field_validator("user_name", "profile_image", "x_username", mode="before")(
        optional_text
    )


class TraderLeaderboardStanding(BaseModel):
    """Trader rankings; PnL is USDC and volume is shares. Unranked values are ``None``."""

    wallet: EvmAddress = Field(validation_alias="user_id")
    pnl: Decimal
    volume: Decimal
    user_name: str | None = None
    profile_image: str | None = None
    x_username: str | None = None
    verified: bool
    pnl_rank: int | None = Field(default=None, validation_alias="rank_pnl")
    volume_rank: int | None = Field(default=None, validation_alias="rank_volume")

    _decimal_from_number = field_validator("pnl", "volume", mode="before")(decimal_from_number)

    _optional_text = field_validator("user_name", "profile_image", "x_username", mode="before")(
        optional_text
    )

    @field_validator("pnl_rank", "volume_rank", mode="before")
    @classmethod
    def _parse_rank(cls, value: object) -> object:
        return None if value == 0 else value


class MarketBiggestWinner(BaseModel):
    """A winning market position; PnL and values are USDC."""

    rank: int = Field(validation_alias="win_rank")
    wallet: EvmAddress = Field(validation_alias="user_id")
    pnl: Decimal
    initial_value: Decimal
    final_value: Decimal
    resolved_at: datetime
    user_name: str | None = None
    profile_image: str | None = None
    event_title: str | None = None
    kind: Literal["market"]
    condition_id: ConditionId
    asset_id: ClobAssetId = Field(validation_alias="position_id")
    event_id: EventId
    event_slug: str | None = None

    _decimal_from_number = field_validator("pnl", "initial_value", "final_value", mode="before")(
        decimal_from_number
    )

    _datetime_from_epoch_or_iso = field_validator("resolved_at", mode="before")(
        datetime_from_epoch_or_iso
    )

    _optional_text = field_validator(
        "user_name", "profile_image", "event_title", "event_slug", mode="before"
    )(optional_text)

    _validate_condition_id_response = field_validator("condition_id", mode="before")(
        validate_condition_id_response
    )

    @field_validator("event_id", mode="before")
    @classmethod
    def _event_id(cls, value: object) -> str:
        return str(value)


class ComboBiggestWinner(BaseModel):
    """A winning combo position; PnL and values are USDC."""

    rank: int = Field(validation_alias="win_rank")
    wallet: EvmAddress = Field(validation_alias="user_id")
    pnl: Decimal
    initial_value: Decimal
    final_value: Decimal
    resolved_at: datetime
    user_name: str | None = None
    profile_image: str | None = None
    event_title: str | None = None
    kind: Literal["combo"]
    condition_id: ComboConditionId
    position_id: PositionId

    _decimal_from_number = field_validator("pnl", "initial_value", "final_value", mode="before")(
        decimal_from_number
    )

    _datetime_from_epoch_or_iso = field_validator("resolved_at", mode="before")(
        datetime_from_epoch_or_iso
    )

    _optional_text = field_validator("user_name", "profile_image", "event_title", mode="before")(
        optional_text
    )

    _validate_combo_condition_id = field_validator("condition_id", mode="before")(
        validate_combo_condition_id
    )


class BuilderStanding(BaseModel):
    """Builder rankings; volume is USDC."""

    rank: int
    builder_name: str
    builder_code: HexString
    profile_image: str | None = None
    verified: bool
    volume: Decimal
    active_users: int

    _optional_text = field_validator("profile_image", mode="before")(optional_text)

    _decimal_from_number = field_validator("volume", mode="before")(decimal_from_number)


class BuilderVolumePoint(BaseModel):
    """Builder volume in USDC for a calendar bucket."""

    rank: int
    builder_name: str
    builder_code: HexString
    profile_image: str | None = None
    verified: bool
    volume: Decimal
    active_users: int
    bucket_date: date = Field(validation_alias="date")

    _optional_text = field_validator("profile_image", mode="before")(optional_text)

    _decimal_from_number = field_validator("volume", mode="before")(decimal_from_number)


def parse_biggest_winners(payload: object) -> tuple[MarketBiggestWinner | ComboBiggestWinner, ...]:
    from polymarket.errors import UnexpectedResponseError

    if not isinstance(payload, list):
        raise UnexpectedResponseError("Biggest winners must be a list")
    rows: list[MarketBiggestWinner | ComboBiggestWinner] = []
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            raise UnexpectedResponseError("Biggest winner must be an object")
        kind = cast(dict[str, object], item).get("kind")
        if kind == "market":
            rows.append(MarketBiggestWinner.parse_response(cast(dict[str, object], item)))
        elif kind == "combo":
            rows.append(ComboBiggestWinner.parse_response(cast(dict[str, object], item)))
        else:
            raise UnexpectedResponseError("Unknown biggest winner kind")
    return tuple(rows)


__all__ = [
    "TraderLeaderboardEntry",
    "TraderLeaderboardStanding",
    "MarketBiggestWinner",
    "ComboBiggestWinner",
    "BuilderStanding",
    "BuilderVolumePoint",
]
