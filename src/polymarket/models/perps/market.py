"""Perps market data models."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal, cast

from pydantic import AliasChoices, Field, model_validator

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


def _normalize_field(
    data: dict[str, object],
    aliases: tuple[str, ...],
    parser: Callable[[object], object],
) -> None:
    for alias in aliases:
        if alias in data:
            data[alias] = parser(data[alias])
            return


def _normalize_market_data(
    data: object,
    *,
    decimals: tuple[tuple[str, ...], ...] = (),
    timestamps: tuple[tuple[str, ...], ...] = (),
    optional_timestamps: tuple[tuple[str, ...], ...] = (),
    optional_hashes: tuple[tuple[str, ...], ...] = (),
) -> object:
    if not isinstance(data, Mapping):
        return data
    normalized = dict(cast("Mapping[str, object]", data))
    for aliases in decimals:
        _normalize_field(normalized, aliases, _coerce_decimalish)
    for aliases in timestamps:
        _normalize_field(normalized, aliases, _require_epoch_ms)
    for aliases in optional_timestamps:
        _normalize_field(normalized, aliases, _parse_epoch_ms)
    for aliases in optional_hashes:
        _normalize_field(normalized, aliases, _parse_tx_hash)
    return normalized


class PerpsRiskTier(BaseModel):
    """One leverage risk tier for a Perps instrument."""

    lower_bound: Decimal
    max_leverage: int

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(data, decimals=(("lower_bound",),))


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

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(
            data,
            decimals=(
                ("price_bounds",),
                ("liquidation_fee",),
                ("min_notional",),
                ("max_market_notional",),
                ("max_limit_notional",),
            ),
        )


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

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(
            data,
            decimals=(
                ("index_price",),
                ("mark_price",),
                ("last_price",),
                ("mid_price",),
                ("open_interest",),
                ("funding_rate",),
                ("open_price",),
                ("volume_24h",),
            ),
            timestamps=(("next_funding",),),
            optional_timestamps=(("timestamp",),),
        )


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

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(
            data,
            decimals=(
                ("idx", "index_price"),
                ("mark", "mark_price"),
                ("last", "last_price"),
                ("mid", "mid_price"),
                ("oi", "open_interest"),
                ("fr", "funding_rate"),
            ),
            timestamps=(("nxf", "next_funding"),),
        )


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
        return _normalize_market_data(
            _candle_from_tuple(data),
            decimals=(("open",), ("high",), ("low",), ("close",), ("volume",)),
            timestamps=(("timestamp",),),
        )


class PerpsStatistic(BaseModel):
    """24-hour trading statistics for a Perps instrument."""

    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    symbol: str | None = None
    volume: Decimal = Field(validation_alias=AliasChoices("volume", "vol"))
    open_price: Decimal = Field(validation_alias=AliasChoices("open_price", "open"))
    klines: tuple[PerpsCandle, ...]

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(
            data,
            decimals=(("volume", "vol"), ("open_price", "open")),
        )


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
        return _normalize_market_data(
            _level_from_tuple(data),
            decimals=(("price",), ("quantity",)),
        )


class PerpsBook(BaseModel):
    """An order book snapshot for a Perps instrument."""

    instrument_id: PerpsInstrumentId
    bids: tuple[PerpsBookLevel, ...]
    asks: tuple[PerpsBookLevel, ...]
    timestamp: datetime
    sequence: int

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(data, timestamps=(("timestamp",),))


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

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(
            data,
            decimals=(
                ("bid_price", "bp"),
                ("bid_quantity", "bq"),
                ("ask_price", "ap"),
                ("ask_quantity", "aq"),
            ),
            optional_timestamps=(("timestamp",),),
        )


class PerpsTrade(BaseModel):
    """One public Perps trade."""

    trade_id: PerpsTradeId = Field(validation_alias=AliasChoices("trade_id", "tid"))
    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    side: PerpsSide
    price: Decimal = Field(validation_alias=AliasChoices("price", "p"))
    quantity: Decimal = Field(validation_alias=AliasChoices("quantity", "qty"))
    timestamp: datetime = Field(validation_alias=AliasChoices("timestamp", "ts"))
    hash: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(
            data,
            decimals=(("price", "p"), ("quantity", "qty")),
            timestamps=(("timestamp", "ts"),),
            optional_hashes=(("hash",),),
        )


class PerpsFundingRate(BaseModel):
    """One historical funding rate observation."""

    funding_rate: Decimal
    timestamp: datetime

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(
            data,
            decimals=(("funding_rate",),),
            timestamps=(("timestamp",),),
        )


class PerpsFeeTier(BaseModel):
    """One volume-based fee tier for a Perps instrument category."""

    min_volume_30d: Decimal
    taker_fee_rate: Decimal
    maker_fee_rate: Decimal

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(
            data,
            decimals=(("min_volume_30d",), ("taker_fee_rate",), ("maker_fee_rate",)),
        )


class PerpsFeeScheduleEntry(BaseModel):
    """Maker and taker fee rates for a Perps instrument category."""

    category: PerpsInstrumentCategory
    taker_fee_rate: Decimal
    maker_fee_rate: Decimal
    tiers: tuple[PerpsFeeTier, ...]

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _normalize_market_data(
            data,
            decimals=(("taker_fee_rate",), ("maker_fee_rate",)),
        )


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
