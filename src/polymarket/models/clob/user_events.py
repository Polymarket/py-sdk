from typing import Annotated, Any, Literal, cast

from pydantic import AliasChoices, BeforeValidator, Field, TypeAdapter, ValidationError

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    EpochSecondsOrMsTimestamp,
    EpochSecondsTimestamp,
    ExpirationTimestamp,
    _DecimalFromNumberOrString,  # pyright: ignore[reportPrivateUsage]
    _OptionalDecimalFromNumberOrString,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.clob.account import TradeStatusField
from polymarket.models.types import TokenId


def _uppercase_string(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


_OrderSide = Annotated[Literal["BUY", "SELL"], BeforeValidator(_uppercase_string)]


_OrderEventType = Literal["PLACEMENT", "UPDATE", "CANCELLATION"]


_OrderStatus = Literal["LIVE", "MATCHED", "DELAYED", "UNMATCHED", "CANCELED"]


_OrderType = Literal["GTC", "FOK", "IOC", "GTD", "FAK"]


_TraderSide = Annotated[Literal["TAKER", "MAKER"], BeforeValidator(_uppercase_string)]


class UserOrderPayload(BaseModel):
    id: str
    owner: str
    market: str
    token_id: TokenId = Field(validation_alias="asset_id")
    side: _OrderSide
    original_size: _DecimalFromNumberOrString
    size_matched: _DecimalFromNumberOrString
    price: _DecimalFromNumberOrString
    order_event_type: _OrderEventType = Field(validation_alias="type")
    timestamp: EpochSecondsOrMsTimestamp = None
    created_at: EpochSecondsTimestamp = None
    expires_at: ExpirationTimestamp = Field(default=None, validation_alias="expiration")
    order_type: _OrderType | None = None
    status: _OrderStatus | None = None
    maker_address: str | None = None
    order_owner: str | None = None
    associate_trades: tuple[str, ...] | None = None
    outcome: str | None = None


class UserTradeMakerOrder(BaseModel):
    order_id: str
    owner: str
    maker_address: str | None = None
    matched_amount: _DecimalFromNumberOrString
    price: _DecimalFromNumberOrString
    fee_rate_bps: _OptionalDecimalFromNumberOrString = None
    token_id: TokenId = Field(validation_alias="asset_id")
    side: _OrderSide
    outcome: str | None = None
    outcome_index: int | None = None


class UserTradePayload(BaseModel):
    id: str
    taker_order_id: str
    market: str
    token_id: TokenId = Field(validation_alias="asset_id")
    side: _OrderSide
    size: _DecimalFromNumberOrString
    price: _DecimalFromNumberOrString
    status: TradeStatusField
    owner: str
    timestamp: EpochSecondsOrMsTimestamp = None
    fee_rate_bps: _OptionalDecimalFromNumberOrString = None
    matched_at: EpochSecondsTimestamp = Field(
        default=None, validation_alias=AliasChoices("match_time", "matchtime")
    )
    updated_at: EpochSecondsTimestamp = Field(default=None, validation_alias="last_update")
    trade_owner: str | None = None
    maker_address: str | None = None
    transaction_hash: str | None = None
    bucket_index: int | None = None
    maker_orders: tuple[UserTradeMakerOrder, ...] | None = None
    trader_side: _TraderSide | None = None
    outcome: str | None = None


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
