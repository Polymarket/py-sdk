from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from pydantic import (
    AliasChoices,
    Field,
    TypeAdapter,
    ValidationError,
    computed_field,
    field_validator,
)

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    _coerce_decimalish,  # pyright: ignore[reportPrivateUsage]
    _coerce_optional_decimalish,  # pyright: ignore[reportPrivateUsage]
    _parse_epoch_seconds_or_ms_timestamp,  # pyright: ignore[reportPrivateUsage]
    _parse_epoch_seconds_timestamp,  # pyright: ignore[reportPrivateUsage]
    _parse_expiration_timestamp,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.clob.account import (
    TradeStatus,
    _normalize_trade_status,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.types import ClobAssetId, ConditionId, OrderSide


def _uppercase_string(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


_OrderEventType = Literal["PLACEMENT", "UPDATE", "CANCELLATION"]


_OrderStatus = Literal["LIVE", "MATCHED", "DELAYED", "UNMATCHED", "CANCELED"]


_OrderType = Literal["GTC", "FOK", "IOC", "GTD", "FAK"]


class UserOrderPayload(BaseModel):
    id: str
    owner: str
    condition_id: ConditionId = Field(validation_alias="market")
    market: ConditionId = Field(
        validation_alias="market", description="Deprecated: use condition_id."
    )
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    side: OrderSide
    original_size: Decimal
    size_matched: Decimal
    price: Decimal
    order_event_type: _OrderEventType = Field(validation_alias="type")
    timestamp: datetime | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = Field(default=None, validation_alias="expiration")
    order_type: _OrderType | None = None
    status: _OrderStatus | None = None
    maker_address: str | None = None
    order_owner: str | None = None
    associate_trades: tuple[str, ...] | None = None
    outcome: str | None = None

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("side", mode="before")
    @classmethod
    def _normalize_side(cls, value: object) -> object:
        return _uppercase_string(value)

    @field_validator("original_size", "size_matched", "price", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_seconds_or_ms_timestamp(value)

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_created_at(cls, value: object) -> object:
        return _parse_epoch_seconds_timestamp(value)

    @field_validator("expires_at", mode="before")
    @classmethod
    def _parse_expires_at(cls, value: object) -> object:
        return _parse_expiration_timestamp(value)


class UserTradeMakerOrder(BaseModel):
    order_id: str
    owner: str
    maker_address: str | None = None
    matched_amount: Decimal
    price: Decimal
    fee_rate_bps: Decimal | None = None
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    side: OrderSide
    outcome: str | None = None
    outcome_index: int | None = None

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("matched_amount", "price", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("fee_rate_bps", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> object:
        return _coerce_optional_decimalish(value)

    @field_validator("side", mode="before")
    @classmethod
    def _normalize_side(cls, value: object) -> object:
        return _uppercase_string(value)


class UserTradePayload(BaseModel):
    id: str
    taker_order_id: str
    condition_id: ConditionId = Field(validation_alias="market")
    market: ConditionId = Field(
        validation_alias="market", description="Deprecated: use condition_id."
    )
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    side: OrderSide
    size: Decimal
    price: Decimal
    status: TradeStatus
    owner: str
    timestamp: datetime | None = None
    fee_rate_bps: Decimal | None = None
    matched_at: datetime | None = Field(
        default=None, validation_alias=AliasChoices("match_time", "matchtime")
    )
    updated_at: datetime | None = Field(default=None, validation_alias="last_update")
    trade_owner: str | None = None
    maker_address: str | None = None
    transaction_hash: str | None = None
    bucket_index: int | None = None
    maker_orders: tuple[UserTradeMakerOrder, ...] | None = None
    trader_side: Literal["TAKER", "MAKER"] | None = None
    outcome: str | None = None

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("side", "trader_side", mode="before")
    @classmethod
    def _normalize_sides(cls, value: object) -> object:
        return _uppercase_string(value)

    @field_validator("size", "price", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("fee_rate_bps", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> object:
        return _coerce_optional_decimalish(value)

    @field_validator("status", mode="before")
    @classmethod
    def _parse_status(cls, value: object) -> object:
        return _normalize_trade_status(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_seconds_or_ms_timestamp(value)

    @field_validator("matched_at", "updated_at", mode="before")
    @classmethod
    def _parse_seconds_timestamp(cls, value: object) -> object:
        return _parse_epoch_seconds_timestamp(value)


class UserOrderEvent(BaseModel):
    topic: Literal["user"] = "user"
    type: Literal["order"]
    payload: UserOrderPayload


class UserTradeEvent(BaseModel):
    topic: Literal["user"] = "user"
    type: Literal["trade"]
    payload: UserTradePayload


UserEvent = Annotated[UserOrderEvent | UserTradeEvent, Field(discriminator="type")]


_USER_EVENT_ADAPTER: TypeAdapter[UserEvent] = TypeAdapter(UserEvent)


def _normalize_to_envelope(raw: object) -> Any:
    if not isinstance(raw, dict):
        return raw
    wire = cast(dict[str, Any], raw)
    if "type" in wire and "payload" in wire and "topic" in wire:
        return wire
    event_type = wire.get("event_type")
    if event_type is None:
        raise ValueError("user event missing event_type")
    return {
        "topic": "user",
        "type": event_type,
        "payload": {k: v for k, v in wire.items() if k not in ("event_type", "topic")},
    }


def parse_user_event(raw: object) -> UserEvent:
    return _USER_EVENT_ADAPTER.validate_python(_normalize_to_envelope(raw))


def parse_user_events(raw: object) -> tuple[list[UserEvent], int]:
    items: list[object] = list(cast(list[object], raw)) if isinstance(raw, list) else [raw]
    parsed: list[UserEvent] = []
    dropped = 0
    for item in items:
        try:
            parsed.append(parse_user_event(item))
        except (ValueError, ValidationError):
            dropped += 1
    return parsed, dropped


__all__ = [
    "UserEvent",
    "UserOrderEvent",
    "UserOrderPayload",
    "UserTradeEvent",
    "UserTradeMakerOrder",
    "UserTradePayload",
    "parse_user_event",
    "parse_user_events",
]
