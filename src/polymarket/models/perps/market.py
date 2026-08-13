"""Perps market data models."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal, cast

from pydantic import AliasChoices, Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    _coerce_decimalish,  # pyright: ignore[reportPrivateUsage]
    _parse_epoch_ms,  # pyright: ignore[reportPrivateUsage]
    _parse_tx_hash,  # pyright: ignore[reportPrivateUsage]
    _require_epoch_ms,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.perps.types import (
    PerpsInstrumentCategory,
    PerpsInstrumentId,
    PerpsSide,
    PerpsTradeId,
)


class PerpsRiskTier(BaseModel):
    """One leverage risk tier for a Perps instrument."""

    lower_bound: Decimal
    max_leverage: int

    @field_validator("lower_bound", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsInstrument(BaseModel):
    """A tradable Perps instrument and its trading limits."""

    id: PerpsInstrumentId = Field(validation_alias="instrument_id")
    category: PerpsInstrumentCategory
    symbol: str
    base_asset: str
    quote_asset: str
    funding_interval: str
    quantity_decimals: int
    price_decimals: int
    price_bounds: Decimal
    liquidation_fee: Decimal
    max_order_count: int
    min_notional: Decimal
    max_market_notional: Decimal
    max_limit_notional: Decimal
    max_leverage: int
    isolated_only: bool
    risk_tiers: tuple[PerpsRiskTier, ...]

    @field_validator(
        "price_bounds",
        "liquidation_fee",
        "min_notional",
        "max_market_notional",
        "max_limit_notional",
        mode="before",
    )
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsTicker(BaseModel):
    """Current prices and funding state for a Perps instrument."""

    instrument_id: PerpsInstrumentId
    symbol: str
    index_price: Decimal
    mark_price: Decimal
    last_price: Decimal
    mid_price: Decimal
    open_interest: Decimal
    funding_rate: Decimal
    next_funding: datetime
    timestamp: datetime | None = None
    open_price: Decimal | None = None
    volume_24h: Decimal | None = None

    @field_validator(
        "index_price",
        "mark_price",
        "last_price",
        "mid_price",
        "open_interest",
        "funding_rate",
        "open_price",
        "volume_24h",
        mode="before",
    )
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("next_funding", mode="before")
    @classmethod
    def _parse_next_funding(cls, value: object) -> object:
        return _require_epoch_ms(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms(value)


class PerpsTickerUpdate(BaseModel):
    """Streaming ticker update for a Perps instrument."""

    instrument_id: PerpsInstrumentId = Field(validation_alias="iid")
    index_price: Decimal = Field(validation_alias="idx")
    mark_price: Decimal = Field(validation_alias="mark")
    last_price: Decimal = Field(validation_alias="last")
    mid_price: Decimal = Field(validation_alias="mid")
    open_interest: Decimal = Field(validation_alias="oi")
    funding_rate: Decimal = Field(validation_alias="fr")
    next_funding: datetime = Field(validation_alias="nxf")

    @field_validator(
        "index_price",
        "mark_price",
        "last_price",
        "mid_price",
        "open_interest",
        "funding_rate",
        mode="before",
    )
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("next_funding", mode="before")
    @classmethod
    def _parse_next_funding(cls, value: object) -> object:
        return _require_epoch_ms(value)


def _candle_from_tuple(value: object) -> object:
    if not isinstance(value, (list, tuple)):
        return value
    entries = cast("Sequence[object]", value)
    if len(entries) != 7:
        return list(entries)
    return {
        "timestamp": entries[0],
        "open": entries[1],
        "high": entries[2],
        "low": entries[3],
        "close": entries[4],
        "volume": entries[5],
        "trades": entries[6],
    }


class PerpsCandle(BaseModel):
    """One OHLCV candle for a Perps instrument."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trades: int

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _candle_from_tuple(data)

    @field_validator("open", "high", "low", "close", "volume", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsStatistic(BaseModel):
    """24-hour trading statistics for a Perps instrument."""

    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    symbol: str | None = None
    volume: Decimal = Field(validation_alias=AliasChoices("volume", "vol"))
    open_price: Decimal = Field(validation_alias=AliasChoices("open_price", "open"))
    klines: tuple[PerpsCandle, ...]

    @field_validator("volume", "open_price", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


def _level_from_tuple(value: object) -> object:
    if not isinstance(value, (list, tuple)):
        return value
    entries = cast("Sequence[object]", value)
    if len(entries) != 2:
        return list(entries)
    return {"price": entries[0], "quantity": entries[1]}


class PerpsBookLevel(BaseModel):
    """One price level of a Perps order book."""

    price: Decimal
    quantity: Decimal

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _level_from_tuple(data)

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsBook(BaseModel):
    """An order book snapshot for a Perps instrument."""

    instrument_id: PerpsInstrumentId
    bids: tuple[PerpsBookLevel, ...]
    asks: tuple[PerpsBookLevel, ...]
    timestamp: datetime
    sequence: int

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsBookUpdate(BaseModel):
    """Streaming order book delta for a Perps instrument."""

    instrument_id: PerpsInstrumentId
    bids: tuple[PerpsBookLevel, ...] = Field(validation_alias=AliasChoices("bids", "b"))
    asks: tuple[PerpsBookLevel, ...] = Field(validation_alias=AliasChoices("asks", "a"))


class PerpsBbo(BaseModel):
    """Best bid and ask for a Perps instrument."""

    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    bid_price: Decimal = Field(validation_alias=AliasChoices("bid_price", "bp"))
    bid_quantity: Decimal = Field(validation_alias=AliasChoices("bid_quantity", "bq"))
    ask_price: Decimal = Field(validation_alias=AliasChoices("ask_price", "ap"))
    ask_quantity: Decimal = Field(validation_alias=AliasChoices("ask_quantity", "aq"))
    timestamp: datetime | None = None

    @field_validator("bid_price", "bid_quantity", "ask_price", "ask_quantity", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms(value)


class PerpsTrade(BaseModel):
    """One public Perps trade."""

    trade_id: PerpsTradeId = Field(validation_alias=AliasChoices("trade_id", "tid"))
    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    side: PerpsSide
    price: Decimal = Field(validation_alias=AliasChoices("price", "p"))
    quantity: Decimal = Field(validation_alias=AliasChoices("quantity", "qty"))
    timestamp: datetime = Field(validation_alias=AliasChoices("timestamp", "ts"))
    hash: str | None = None

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)

    @field_validator("hash", mode="before")
    @classmethod
    def _parse_hash(cls, value: object) -> object:
        return _parse_tx_hash(value)


class PerpsFundingRate(BaseModel):
    """One historical funding rate observation."""

    funding_rate: Decimal
    timestamp: datetime

    @field_validator("funding_rate", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsFeeTier(BaseModel):
    """One volume-based fee tier for a Perps instrument category."""

    min_volume_30d: Decimal
    taker_fee_rate: Decimal
    maker_fee_rate: Decimal

    @field_validator("min_volume_30d", "taker_fee_rate", "maker_fee_rate", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsFeeScheduleEntry(BaseModel):
    """Maker and taker fee rates for a Perps instrument category."""

    category: PerpsInstrumentCategory
    taker_fee_rate: Decimal
    maker_fee_rate: Decimal
    tiers: tuple[PerpsFeeTier, ...]

    @field_validator("taker_fee_rate", "maker_fee_rate", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsCandleBatch(BaseModel):
    """Streaming candle batch for one instrument and interval."""

    instrument_id: PerpsInstrumentId
    interval: Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
    candles: tuple[PerpsCandle, ...]


__all__ = [
    "PerpsBbo",
    "PerpsBook",
    "PerpsBookLevel",
    "PerpsBookUpdate",
    "PerpsCandle",
    "PerpsCandleBatch",
    "PerpsFeeScheduleEntry",
    "PerpsFeeTier",
    "PerpsFundingRate",
    "PerpsInstrument",
    "PerpsRiskTier",
    "PerpsStatistic",
    "PerpsTicker",
    "PerpsTickerUpdate",
    "PerpsTrade",
]
