import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from pydantic import BeforeValidator, Field, TypeAdapter, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    _coerce_decimalish,  # pyright: ignore[reportPrivateUsage]
    _parse_epoch_ms_or_iso_timestamp,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.gamma.comment import (
    Comment,
    CommentMedia,
    CommentProfile,
    Reaction,
)
from polymarket.models.gamma.common import parse_optional_datetime

_WIRE_TO_API_TOPIC: dict[str, str] = {
    "comments": "comments",
    "crypto_prices": "prices.crypto.binance",
    "crypto_prices_chainlink": "prices.crypto.chainlink",
    "crypto_prices_twap_thirty": "prices.crypto.chainlink.twap",
    "crypto_prices_twap_sixty": "prices.crypto.chainlink.twap",
    "equity_prices": "prices.equity.pyth",
}

_API_TO_WIRE_TOPIC: dict[str, str] = {
    "comments": "comments",
    "prices.crypto.binance": "crypto_prices",
    "prices.crypto.chainlink": "crypto_prices_chainlink",
    "prices.equity.pyth": "equity_prices",
}

_TWAP_WINDOW_BY_WIRE_TOPIC: dict[str, Literal[30, 60]] = {
    "crypto_prices_twap_thirty": 30,
    "crypto_prices_twap_sixty": 60,
}

_CHAINLINK_PRICE_SCALE = 10**18
_SIGNED_INTEGER_PATTERN = re.compile(r"-?[0-9]+")
_DECIMALISH_ADAPTER: TypeAdapter[Decimal] = TypeAdapter(
    Annotated[Decimal, BeforeValidator(_coerce_decimalish)]
)


def wire_topic_to_api(wire: str) -> str | None:
    return _WIRE_TO_API_TOPIC.get(wire)


def api_topic_to_wire(api: str) -> str:
    return _API_TO_WIRE_TOPIC[api]


class CommentRemovedPayload(BaseModel):
    id: str
    body: str | None = None
    parent_entity_type: Literal["Event", "Market"] | None = Field(
        default=None, validation_alias="parentEntityType"
    )
    parent_entity_id: int | None = Field(default=None, validation_alias="parentEntityID")
    parent_comment_id: str | None = Field(default=None, validation_alias="parentCommentID")
    user_address: str | None = Field(default=None, validation_alias="userAddress")
    reply_address: str | None = Field(default=None, validation_alias="replyAddress")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")
    media: tuple[CommentMedia, ...] | None = None
    profile: CommentProfile | None = None
    reactions: tuple[Reaction, ...] | None = None
    report_count: int | None = Field(default=None, validation_alias="reportCount")
    reaction_count: int | None = Field(default=None, validation_alias="reactionCount")
    trade_asset: str | None = Field(default=None, validation_alias="tradeAsset")

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class CommentCreatedEvent(BaseModel):
    topic: Literal["comments"] = "comments"
    type: Literal["comment_created"]
    timestamp: datetime | None
    payload: Comment

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


class CommentRemovedEvent(BaseModel):
    topic: Literal["comments"] = "comments"
    type: Literal["comment_removed"]
    timestamp: datetime | None
    payload: CommentRemovedPayload

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


class ReactionCreatedEvent(BaseModel):
    topic: Literal["comments"] = "comments"
    type: Literal["reaction_created"]
    timestamp: datetime | None
    payload: Reaction

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


class ReactionRemovedEvent(BaseModel):
    topic: Literal["comments"] = "comments"
    type: Literal["reaction_removed"]
    timestamp: datetime | None
    payload: Reaction

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


CommentsEvent = (
    CommentCreatedEvent | CommentRemovedEvent | ReactionCreatedEvent | ReactionRemovedEvent
)


class PriceUpdatePayload(BaseModel):
    symbol: str
    timestamp: int
    value: Decimal

    @field_validator("value", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class CryptoPricesBinanceEvent(BaseModel):
    topic: Literal["prices.crypto.binance"] = "prices.crypto.binance"
    type: Literal["update"]
    timestamp: datetime | None
    payload: PriceUpdatePayload

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


class CryptoPricesChainlinkEvent(BaseModel):
    topic: Literal["prices.crypto.chainlink"] = "prices.crypto.chainlink"
    type: Literal["update"]
    timestamp: datetime | None
    payload: PriceUpdatePayload

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


def _chainlink_e18_to_decimal(value: object) -> Decimal:
    if not isinstance(value, str) or _SIGNED_INTEGER_PATTERN.fullmatch(value) is None:
        msg = "full_accuracy_value must be a signed integer string"
        raise ValueError(msg)

    scaled_value = int(value)
    absolute_value = abs(scaled_value)
    whole, fraction = divmod(absolute_value, _CHAINLINK_PRICE_SCALE)
    fraction_text = f"{fraction:018d}".rstrip("0")
    sign = "-" if scaled_value < 0 else ""
    normalized = f"{sign}{whole}"
    if fraction_text:
        normalized = f"{normalized}.{fraction_text}"
    return Decimal(normalized)


class CryptoPricesChainlinkTwapPayload(BaseModel):
    symbol: str
    timestamp: int
    value: Decimal
    window_seconds: Literal[30, 60] = Field(validation_alias="window_s")

    @model_validator(mode="before")
    @classmethod
    def _use_full_accuracy_value(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(cast(dict[str, Any], value))
        if "full_accuracy_value" not in data:
            if "window_s" not in data and "window_seconds" in data:
                return data
            msg = "full_accuracy_value is required"
            raise ValueError(msg)
        _DECIMALISH_ADAPTER.validate_python(data.get("value"))
        data["value"] = _chainlink_e18_to_decimal(data.pop("full_accuracy_value"))
        return data

    @field_validator("value", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class CryptoPricesChainlinkTwapEvent(BaseModel):
    topic: Literal["prices.crypto.chainlink.twap"] = "prices.crypto.chainlink.twap"
    type: Literal["update"]
    timestamp: datetime | None
    payload: CryptoPricesChainlinkTwapPayload

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


CryptoPricesEvent = CryptoPricesBinanceEvent | CryptoPricesChainlinkEvent


class EquityPriceUpdatePayload(BaseModel):
    symbol: str
    value: Decimal
    timestamp: int
    received_at: int | None = None
    is_carried_forward: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _prefer_full_accuracy_value(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(cast(dict[str, Any], value))
        full = data.pop("full_accuracy_value", None)
        if full is not None:
            data["value"] = full
        return data

    @field_validator("value", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class EquityPriceSnapshotEntry(BaseModel):
    timestamp: int
    value: Decimal

    @field_validator("value", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class EquityPriceSubscribePayload(BaseModel):
    symbol: str
    data: tuple[EquityPriceSnapshotEntry, ...]


class EquityPricesUpdateEvent(BaseModel):
    topic: Literal["prices.equity.pyth"] = "prices.equity.pyth"
    type: Literal["update"]
    timestamp: datetime | None
    payload: EquityPriceUpdatePayload

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


class EquityPricesSubscribeEvent(BaseModel):
    topic: Literal["prices.equity.pyth"] = "prices.equity.pyth"
    type: Literal["subscribe"]
    timestamp: datetime | None
    payload: EquityPriceSubscribePayload

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


EquityPricesEvent = EquityPricesUpdateEvent | EquityPricesSubscribeEvent


RtdsEvent = (
    CommentsEvent
    | CryptoPricesBinanceEvent
    | CryptoPricesChainlinkEvent
    | CryptoPricesChainlinkTwapEvent
    | EquityPricesUpdateEvent
    | EquityPricesSubscribeEvent
)


_RTDS_VARIANTS: dict[tuple[str, str], type[BaseModel]] = {
    ("comments", "comment_created"): CommentCreatedEvent,
    ("comments", "comment_removed"): CommentRemovedEvent,
    ("comments", "reaction_created"): ReactionCreatedEvent,
    ("comments", "reaction_removed"): ReactionRemovedEvent,
    ("prices.crypto.binance", "update"): CryptoPricesBinanceEvent,
    ("prices.crypto.chainlink", "update"): CryptoPricesChainlinkEvent,
    ("prices.crypto.chainlink.twap", "update"): CryptoPricesChainlinkTwapEvent,
    ("prices.equity.pyth", "update"): EquityPricesUpdateEvent,
    ("prices.equity.pyth", "subscribe"): EquityPricesSubscribeEvent,
}

_TYPE_ADAPTERS: dict[tuple[str, str], TypeAdapter[Any]] = {
    key: TypeAdapter(model) for key, model in _RTDS_VARIANTS.items()
}


def parse_rtds_event(raw: object) -> RtdsEvent:
    if not isinstance(raw, dict):
        msg = f"expected dict, got {type(raw).__name__}"
        raise ValueError(msg)
    wire = cast(dict[str, Any], raw)
    topic_raw = wire.get("topic")
    type_raw = wire.get("type")
    if not isinstance(topic_raw, str) or not isinstance(type_raw, str):
        msg = "RTDS event missing topic/type"
        raise ValueError(msg)
    api_topic = wire_topic_to_api(topic_raw)
    if api_topic is None:
        msg = f"unknown RTDS wire topic: {topic_raw!r}"
        raise ValueError(msg)
    expected_window = _TWAP_WINDOW_BY_WIRE_TOPIC.get(topic_raw)
    if expected_window is not None:
        payload_raw = wire.get("payload")
        if not isinstance(payload_raw, dict):
            msg = f"RTDS TWAP topic {topic_raw!r} requires window_s={expected_window}"
            raise ValueError(msg)
        payload = cast(dict[str, Any], payload_raw)
        window = payload.get("window_s")
        if isinstance(window, bool) or not isinstance(window, int) or window != expected_window:
            msg = f"RTDS TWAP topic {topic_raw!r} requires window_s={expected_window}"
            raise ValueError(msg)
    key = (api_topic, type_raw)
    adapter = _TYPE_ADAPTERS.get(key)
    if adapter is None:
        msg = f"unknown RTDS event: topic={api_topic!r}, type={type_raw!r}"
        raise ValueError(msg)
    normalized = {**wire, "topic": api_topic}
    return cast(RtdsEvent, adapter.validate_python(normalized))


__all__ = [
    "Comment",
    "CommentCreatedEvent",
    "CommentMedia",
    "CommentProfile",
    "CommentRemovedEvent",
    "CommentRemovedPayload",
    "CommentsEvent",
    "CryptoPricesBinanceEvent",
    "CryptoPricesChainlinkEvent",
    "CryptoPricesChainlinkTwapEvent",
    "CryptoPricesChainlinkTwapPayload",
    "CryptoPricesEvent",
    "EquityPriceSnapshotEntry",
    "EquityPriceSubscribePayload",
    "EquityPriceUpdatePayload",
    "EquityPricesEvent",
    "EquityPricesSubscribeEvent",
    "EquityPricesUpdateEvent",
    "PriceUpdatePayload",
    "Reaction",
    "ReactionCreatedEvent",
    "ReactionRemovedEvent",
    "RtdsEvent",
    "api_topic_to_wire",
    "parse_rtds_event",
    "wire_topic_to_api",
]
