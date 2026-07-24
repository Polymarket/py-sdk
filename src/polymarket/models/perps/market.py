"""Perps market data models."""

from collections.abc import Sequence
from typing import Literal, cast

from pydantic import AliasChoices, Field, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    OptionalPerpsTimestamp,
    OptionalTxHash,
    PerpsTimestamp,
    _Decimal,
)
from polymarket.models.perps.types import (
    PerpsInstrumentCategory,
    PerpsInstrumentId,
    PerpsSide,
    PerpsTradeId,
)


class PerpsRiskTier(BaseModel):
    """One leverage risk tier for a Perps instrument."""

    lower_bound: _Decimal
    max_leverage: int


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
    price_bounds: _Decimal
    liquidation_fee: _Decimal
    max_order_count: int
    min_notional: _Decimal
    max_market_notional: _Decimal
    max_limit_notional: _Decimal
    max_leverage: int
    isolated_only: bool
    risk_tiers: tuple[PerpsRiskTier, ...]


class PerpsTicker(BaseModel):
    """Current prices and funding state for a Perps instrument."""

    instrument_id: PerpsInstrumentId
    symbol: str
    index_price: _Decimal
    mark_price: _Decimal
    last_price: _Decimal
    mid_price: _Decimal
    open_interest: _Decimal
    funding_rate: _Decimal
    next_funding: PerpsTimestamp
    timestamp: OptionalPerpsTimestamp = None
    open_price: _Decimal | None = None
    volume_24h: _Decimal | None = None


class PerpsTickerUpdate(BaseModel):
    """Streaming ticker update for a Perps instrument."""

    instrument_id: PerpsInstrumentId = Field(validation_alias="iid")
    index_price: _Decimal = Field(validation_alias="idx")
    mark_price: _Decimal = Field(validation_alias="mark")
    last_price: _Decimal = Field(validation_alias="last")
    mid_price: _Decimal = Field(validation_alias="mid")
    open_interest: _Decimal = Field(validation_alias="oi")
    funding_rate: _Decimal = Field(validation_alias="fr")
    next_funding: PerpsTimestamp = Field(validation_alias="nxf")


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

    timestamp: PerpsTimestamp
    open: _Decimal
    high: _Decimal
    low: _Decimal
    close: _Decimal
    volume: _Decimal
    trades: int

    @model_validator(mode="before")
    @classmethod
    def _from_tuple(cls, data: object) -> object:
        return _candle_from_tuple(data)


class PerpsStatistic(BaseModel):
    """24-hour trading statistics for a Perps instrument."""

    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    symbol: str | None = None
    volume: _Decimal = Field(validation_alias=AliasChoices("volume", "vol"))
    open_price: _Decimal = Field(validation_alias=AliasChoices("open_price", "open"))
    klines: tuple[PerpsCandle, ...]


def _level_from_tuple(value: object) -> object:
    if not isinstance(value, (list, tuple)):
        return value
    entries = cast("Sequence[object]", value)
    if len(entries) != 2:
        return list(entries)
    return {"price": entries[0], "quantity": entries[1]}


class PerpsBookLevel(BaseModel):
    """One price level of a Perps order book."""

    price: _Decimal
    quantity: _Decimal

    @model_validator(mode="before")
    @classmethod
    def _from_tuple(cls, data: object) -> object:
        return _level_from_tuple(data)


class PerpsBook(BaseModel):
    """An order book snapshot for a Perps instrument."""

    instrument_id: PerpsInstrumentId
    bids: tuple[PerpsBookLevel, ...]
    asks: tuple[PerpsBookLevel, ...]
    timestamp: PerpsTimestamp
    sequence: int


class PerpsBookUpdate(BaseModel):
    """Streaming order book delta for a Perps instrument."""

    instrument_id: PerpsInstrumentId
    bids: tuple[PerpsBookLevel, ...] = Field(validation_alias=AliasChoices("bids", "b"))
    asks: tuple[PerpsBookLevel, ...] = Field(validation_alias=AliasChoices("asks", "a"))


class PerpsBbo(BaseModel):
    """Best bid and ask for a Perps instrument."""

    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    bid_price: _Decimal = Field(validation_alias=AliasChoices("bid_price", "bp"))
    bid_quantity: _Decimal = Field(validation_alias=AliasChoices("bid_quantity", "bq"))
    ask_price: _Decimal = Field(validation_alias=AliasChoices("ask_price", "ap"))
    ask_quantity: _Decimal = Field(validation_alias=AliasChoices("ask_quantity", "aq"))
    timestamp: OptionalPerpsTimestamp = None


class PerpsTrade(BaseModel):
    """One public Perps trade."""

    trade_id: PerpsTradeId = Field(validation_alias=AliasChoices("trade_id", "tid"))
    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    side: PerpsSide
    price: _Decimal = Field(validation_alias=AliasChoices("price", "p"))
    quantity: _Decimal = Field(validation_alias=AliasChoices("quantity", "qty"))
    timestamp: PerpsTimestamp = Field(validation_alias=AliasChoices("timestamp", "ts"))
    hash: OptionalTxHash = None


class PerpsFundingRate(BaseModel):
    """One historical funding rate observation."""

    funding_rate: _Decimal
    timestamp: PerpsTimestamp


class PerpsFeeTier(BaseModel):
    """One volume-based fee tier for a Perps instrument category."""

    min_volume_30d: _Decimal
    taker_fee_rate: _Decimal
    maker_fee_rate: _Decimal


class PerpsFeeScheduleEntry(BaseModel):
    """Maker and taker fee rates for a Perps instrument category."""

    category: PerpsInstrumentCategory
    taker_fee_rate: _Decimal
    maker_fee_rate: _Decimal
    tiers: tuple[PerpsFeeTier, ...]


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
