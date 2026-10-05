from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from pydantic import AliasChoices, Field, TypeAdapter, computed_field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    _coerce_decimalish,  # pyright: ignore[reportPrivateUsage]
    _coerce_optional_decimalish,  # pyright: ignore[reportPrivateUsage]
    _parse_epoch_ms_timestamp,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.clob.order_book import OrderBookLevel
from polymarket.models.types import (
    ClobAssetId,
    ConditionId,
    validate_optional_condition_id,
)


def _uppercase_order_side(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


class MarketEventMessage(BaseModel):
    id: str
    ticker: str | None = None
    slug: str | None = None
    title: str | None = None
    description: str | None = None


class PriceChange(BaseModel):
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    price: Decimal
    size: Decimal
    side: Literal["BUY", "SELL"]
    hash: str | None = None
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("price", "size", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("best_bid", "best_ask", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> object:
        return _coerce_optional_decimalish(value)

    @field_validator("side", mode="before")
    @classmethod
    def _normalize_side(cls, value: object) -> object:
        return _uppercase_order_side(value)


# --- Payloads (the variant-specific data; lifted out of the wire's top level) ---


class MarketBookPayload(BaseModel):
    condition_id: ConditionId = Field(validation_alias="market")
    market: ConditionId = Field(
        validation_alias="market", description="Deprecated: use condition_id."
    )
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    hash: str | None = None
    timestamp: datetime | None = None
    min_order_size: Decimal | None = None
    tick_size: Decimal | None = None
    neg_risk: bool | None = None
    last_trade_price: Decimal | None = None

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("min_order_size", "tick_size", "last_trade_price", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> object:
        return _coerce_optional_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_timestamp(value)


class MarketPriceChangePayload(BaseModel):
    condition_id: ConditionId = Field(validation_alias="market")
    market: ConditionId = Field(
        validation_alias="market", description="Deprecated: use condition_id."
    )
    price_changes: tuple[PriceChange, ...]
    timestamp: datetime | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_timestamp(value)


class MarketLastTradePricePayload(BaseModel):
    condition_id: ConditionId = Field(validation_alias="market")
    market: ConditionId = Field(
        validation_alias="market", description="Deprecated: use condition_id."
    )
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    price: Decimal
    size: Decimal | None = None
    side: Literal["BUY", "SELL"]
    fee_rate_bps: Decimal | None = None
    transaction_hash: str | None = None
    timestamp: datetime | None = None

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("price", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("size", "fee_rate_bps", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> object:
        return _coerce_optional_decimalish(value)

    @field_validator("side", mode="before")
    @classmethod
    def _normalize_side(cls, value: object) -> object:
        return _uppercase_order_side(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_timestamp(value)


class MarketTickSizeChangePayload(BaseModel):
    condition_id: ConditionId = Field(validation_alias="market")
    market: ConditionId = Field(
        validation_alias="market", description="Deprecated: use condition_id."
    )
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    old_tick_size: Decimal | None = None
    new_tick_size: Decimal
    timestamp: datetime | None = None

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("new_tick_size", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("old_tick_size", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> object:
        return _coerce_optional_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_timestamp(value)


class MarketBestBidAskPayload(BaseModel):
    condition_id: ConditionId = Field(validation_alias="market")
    market: ConditionId = Field(
        validation_alias="market", description="Deprecated: use condition_id."
    )
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    spread: Decimal | None = None
    timestamp: datetime | None = None

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("best_bid", "best_ask", "spread", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> object:
        return _coerce_optional_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_timestamp(value)


class NewMarketPayload(BaseModel):
    id: str
    condition_id: ConditionId | None = None
    market: str
    question: str | None = None
    slug: str | None = None
    description: str | None = None
    asset_ids: tuple[ClobAssetId, ...] | None = Field(
        default=None,
        validation_alias=AliasChoices("asset_ids", "assets_ids", "token_ids"),
    )
    outcomes: tuple[str, ...] | None = None
    event_message: MarketEventMessage | None = None
    timestamp: datetime | None = None
    tags: tuple[str, ...] | None = None
    active: bool | None = None
    clob_token_ids: tuple[str, ...] | None = None
    sports_market_type: str | None = None
    line: Decimal | None = None
    game_start_time: datetime | None = None
    order_price_min_tick_size: Decimal | None = None
    group_item_title: str | None = None
    taker_base_fee: Decimal | None = None
    fees_enabled: bool | None = None
    fee_schedule: object | None = None

    @computed_field
    @property
    def token_ids(self) -> tuple[ClobAssetId, ...] | None:
        """Deprecated alias for :attr:`asset_ids`."""

        return self.asset_ids

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId | None:
        return validate_optional_condition_id(value)

    @field_validator("line", "order_price_min_tick_size", "taker_base_fee", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> object:
        return _coerce_optional_decimalish(value)

    @field_validator("timestamp", "game_start_time", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_timestamp(value)


class MarketResolvedPayload(BaseModel):
    id: str
    condition_id: ConditionId = Field(validation_alias="market")
    market: ConditionId = Field(
        validation_alias="market", description="Deprecated: use condition_id."
    )
    asset_ids: tuple[ClobAssetId, ...] | None = Field(
        default=None,
        validation_alias=AliasChoices("asset_ids", "assets_ids", "token_ids"),
    )
    winning_asset_id: ClobAssetId | None = Field(
        default=None,
        validation_alias=AliasChoices("winning_asset_id", "winning_token_id"),
    )
    winning_outcome: str | None = None
    event_message: MarketEventMessage | None = None
    timestamp: datetime | None = None
    tags: tuple[str, ...] | None = None

    @computed_field
    @property
    def token_ids(self) -> tuple[ClobAssetId, ...] | None:
        """Deprecated alias for :attr:`asset_ids`."""

        return self.asset_ids

    @computed_field
    @property
    def winning_token_id(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`winning_asset_id`."""

        return self.winning_asset_id

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_timestamp(value)


# --- Envelope: every event is {topic, type, payload} ---


class MarketBookEvent(BaseModel):
    topic: Literal["market"] = "market"
    type: Literal["book"]
    payload: MarketBookPayload


class MarketPriceChangeEvent(BaseModel):
    topic: Literal["market"] = "market"
    type: Literal["price_change"]
    payload: MarketPriceChangePayload


class MarketLastTradePriceEvent(BaseModel):
    topic: Literal["market"] = "market"
    type: Literal["last_trade_price"]
    payload: MarketLastTradePricePayload


class MarketTickSizeChangeEvent(BaseModel):
    topic: Literal["market"] = "market"
    type: Literal["tick_size_change"]
    payload: MarketTickSizeChangePayload


class MarketBestBidAskEvent(BaseModel):
    topic: Literal["market"] = "market"
    type: Literal["best_bid_ask"]
    payload: MarketBestBidAskPayload


class NewMarketEvent(BaseModel):
    topic: Literal["market"] = "market"
    type: Literal["new_market"]
    payload: NewMarketPayload


class MarketResolvedEvent(BaseModel):
    topic: Literal["market"] = "market"
    type: Literal["market_resolved"]
    payload: MarketResolvedPayload


MarketEvent = Annotated[
    MarketBookEvent
    | MarketPriceChangeEvent
    | MarketLastTradePriceEvent
    | MarketTickSizeChangeEvent
    | MarketBestBidAskEvent
    | NewMarketEvent
    | MarketResolvedEvent,
    Field(discriminator="type"),
]

_MARKET_EVENT_ADAPTER: TypeAdapter[MarketEvent] = TypeAdapter(MarketEvent)


def _normalize_to_envelope(raw: object) -> Any:
    """Lift the wire's flat ``{event_type, ...}`` shape into the envelope
    ``{topic, type, payload}`` so the discriminated union can dispatch on
    ``type``. Already-enveloped input is passed through unchanged.
    """
    if not isinstance(raw, dict):
        return raw
    wire = cast(dict[str, Any], raw)
    if "type" in wire and "payload" in wire and "topic" in wire:
        return wire
    type_value = wire.get("event_type") or wire.get("type")
    return {
        "topic": "market",
        "type": type_value,
        "payload": {k: v for k, v in wire.items() if k not in ("event_type", "type", "topic")},
    }


def parse_market_event(raw: object) -> MarketEvent:
    return _MARKET_EVENT_ADAPTER.validate_python(_normalize_to_envelope(raw))


__all__ = [
    "MarketBestBidAskEvent",
    "MarketBestBidAskPayload",
    "MarketBookEvent",
    "MarketBookPayload",
    "MarketEvent",
    "MarketEventMessage",
    "MarketLastTradePriceEvent",
    "MarketLastTradePricePayload",
    "MarketPriceChangeEvent",
    "MarketPriceChangePayload",
    "MarketResolvedEvent",
    "MarketResolvedPayload",
    "MarketTickSizeChangeEvent",
    "MarketTickSizeChangePayload",
    "NewMarketEvent",
    "NewMarketPayload",
    "PriceChange",
    "parse_market_event",
]
