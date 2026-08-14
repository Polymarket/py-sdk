"""Perps public market data reads."""

import asyncio
import time
from datetime import datetime
from typing import Any, cast

from pydantic import field_validator

from polymarket._internal.actions.perps.paging import (
    ONE_DAY_MS,
    as_json_dict,
    decode_perps_candles_cursor,
    decode_perps_funding_cursor,
    decode_perps_trades_cursor,
    encode_perps_cursor,
    interval_ms,
    parse_data_envelope,
    to_epoch_ms,
)
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    _require_epoch_ms,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.perps.market import (
    PerpsBook,
    PerpsCandle,
    PerpsFeeScheduleEntry,
    PerpsFundingRate,
    PerpsInstrument,
    PerpsStatistic,
    PerpsTicker,
    PerpsTrade,
)
from polymarket.models.perps.types import (
    PerpsBookDepth,
    PerpsInstrumentCategory,
    PerpsKlineInterval,
)
from polymarket.pagination import AsyncPaginator, Page

_BOOK_DEPTHS = (10, 100, 500, 1000)
_CATEGORIES = ("equity", "commodity", "index", "crypto")
_KLINE_INTERVALS = ("1s", "1m", "5m", "15m", "1h", "4h", "1d", "1w")


class _PerpsServerTimeResponse(BaseModel):
    time: datetime

    @field_validator("time", mode="before")
    @classmethod
    def _parse_time(cls, value: object) -> object:
        return _require_epoch_ms(value)


def _validate_instrument_id(instrument_id: object, *, optional: bool = False) -> int | None:
    if instrument_id is None and optional:
        return None
    if isinstance(instrument_id, bool) or not isinstance(instrument_id, int):
        raise UserInputError("instrument_id must be an int")
    if instrument_id < 0:
        raise UserInputError("instrument_id must be non-negative")
    return instrument_id


async def get_server_time(perps: AsyncTransport) -> datetime:
    """Return the Perps server clock as an aware UTC datetime."""
    response = _PerpsServerTimeResponse.parse_response(await perps.get_json("/v1/info/time"))
    return response.time


async def fetch_instruments(
    perps: AsyncTransport,
    *,
    instrument_id: int | None = None,
    category: PerpsInstrumentCategory | None = None,
) -> tuple[PerpsInstrument, ...]:
    _validate_instrument_id(instrument_id, optional=True)
    if category is not None and category not in _CATEGORIES:
        raise UserInputError(f"category must be one of {list(_CATEGORIES)}, got {category!r}")
    payload = await perps.get_json(
        "/v1/info/instruments",
        params={"instrument_id": instrument_id, "category": category},
    )
    return PerpsInstrument.parse_response_list(payload)


async def fetch_tickers(
    perps: AsyncTransport, *, instrument_id: int | None = None
) -> tuple[PerpsTicker, ...]:
    _validate_instrument_id(instrument_id, optional=True)
    params = {"instrument_id": instrument_id}
    tickers_payload, statistics_payload = await asyncio.gather(
        perps.get_json("/v1/info/tickers", params=params),
        perps.get_json("/v1/info/statistics", params=params),
    )
    statistics = PerpsStatistic.parse_response_list(statistics_payload)
    by_instrument = {statistic.instrument_id: statistic for statistic in statistics}
    if not isinstance(tickers_payload, list):
        raise UnexpectedResponseError("PerpsTicker response did not match expected shape")
    tickers: list[PerpsTicker] = []
    for item in cast("list[object]", tickers_payload):
        ticker = PerpsTicker.parse_response(item)
        statistic = by_instrument.get(ticker.instrument_id)
        if statistic is not None:
            ticker = ticker.model_copy(
                update={"open_price": statistic.open_price, "volume_24h": statistic.volume}
            )
        tickers.append(ticker)
    return tuple(tickers)


async def fetch_ticker(perps: AsyncTransport, *, instrument_id: int) -> PerpsTicker:
    _validate_instrument_id(instrument_id)
    tickers = await fetch_tickers(perps, instrument_id=instrument_id)
    if not tickers:
        raise UnexpectedResponseError(f"Perps ticker {instrument_id} was not returned by the API")
    return tickers[0]


async def fetch_book(
    perps: AsyncTransport, *, instrument_id: int, depth: PerpsBookDepth = 100
) -> PerpsBook:
    _validate_instrument_id(instrument_id)
    if depth not in _BOOK_DEPTHS:
        raise UserInputError(f"depth must be one of {list(_BOOK_DEPTHS)}, got {depth!r}")
    payload = await perps.get_json(
        "/v1/info/book", params={"instrument_id": instrument_id, "depth": depth}
    )
    return PerpsBook.parse_response(payload)


async def fetch_fees(perps: AsyncTransport) -> tuple[PerpsFeeScheduleEntry, ...]:
    payload = as_json_dict(await perps.get_json("/v1/info/fees"))
    if payload is None or not isinstance(payload.get("fee_schedule"), list):
        raise UnexpectedResponseError("Perps fees response did not match expected shape")
    return PerpsFeeScheduleEntry.parse_response_list(payload["fee_schedule"])


def list_candles(
    perps: AsyncTransport,
    *,
    instrument_id: int,
    interval: PerpsKlineInterval,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
) -> AsyncPaginator[PerpsCandle]:
    _validate_instrument_id(instrument_id)
    if interval not in _KLINE_INTERVALS:
        raise UserInputError(f"interval must be one of {list(_KLINE_INTERVALS)}, got {interval!r}")
    start_ms = to_epoch_ms("start", start)
    end_ms = to_epoch_ms("end", end)

    async def fetch(cursor: str | None) -> Page[PerpsCandle]:
        if cursor is None:
            now = int(time.time() * 1000)
            state: dict[str, Any] = {
                "kind": "perpsCandles",
                "instrument_id": instrument_id,
                "interval": interval,
                "start_timestamp": start_ms if start_ms is not None else now - ONE_DAY_MS,
                "end_timestamp": end_ms if end_ms is not None else now,
            }
        else:
            state = decode_perps_candles_cursor(cursor, intervals=_KLINE_INTERVALS)
        payload = await perps.get_json(
            "/v1/info/klines",
            params={
                "instrument_id": state["instrument_id"],
                "interval": state["interval"],
                "start_timestamp": state["start_timestamp"],
                "end_timestamp": state["end_timestamp"],
            },
        )
        data, more = parse_data_envelope(payload)
        items = tuple(PerpsCandle.parse_response(item) for item in data)
        last_ts = _tuple_timestamp(data[-1]) if data else None
        has_more = more and last_ts is not None
        next_cursor = None
        if has_more and last_ts is not None:
            next_cursor = encode_perps_cursor(
                {**state, "start_timestamp": last_ts + interval_ms(state["interval"])}
            )
        return Page(items=items, has_more=has_more, next_cursor=next_cursor)

    return AsyncPaginator(fetch=fetch)


def list_funding_history(
    perps: AsyncTransport,
    *,
    instrument_id: int,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
) -> AsyncPaginator[PerpsFundingRate]:
    _validate_instrument_id(instrument_id)
    start_ms = to_epoch_ms("start", start)
    end_ms = to_epoch_ms("end", end)

    async def fetch(cursor: str | None) -> Page[PerpsFundingRate]:
        if cursor is None:
            now = int(time.time() * 1000)
            state: dict[str, Any] = {
                "kind": "perpsFundingHistory",
                "instrument_id": instrument_id,
                "start_timestamp": start_ms if start_ms is not None else now - ONE_DAY_MS,
                "end_timestamp": end_ms if end_ms is not None else now,
            }
        else:
            state = decode_perps_funding_cursor(cursor)
        payload = await perps.get_json(
            "/v1/info/funding",
            params={
                "instrument_id": state["instrument_id"],
                "start_timestamp": state["start_timestamp"],
                "end_timestamp": state["end_timestamp"],
            },
        )
        data, more = parse_data_envelope(payload)
        items = tuple(PerpsFundingRate.parse_response(item) for item in data)
        raw_last = as_json_dict(data[-1]) if data else None
        last_ts = raw_last.get("timestamp") if raw_last is not None else None
        has_more = more and isinstance(last_ts, int) and last_ts > int(state["start_timestamp"])
        next_cursor = None
        if has_more and isinstance(last_ts, int):
            next_cursor = encode_perps_cursor({**state, "end_timestamp": last_ts - 1})
        return Page(items=items, has_more=has_more, next_cursor=next_cursor)

    return AsyncPaginator(fetch=fetch)


def list_trades(
    perps: AsyncTransport,
    *,
    instrument_id: int,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
) -> AsyncPaginator[PerpsTrade]:
    _validate_instrument_id(instrument_id)
    start_ms = to_epoch_ms("start", start)
    end_ms = to_epoch_ms("end", end)

    async def fetch(cursor: str | None) -> Page[PerpsTrade]:
        if cursor is None:
            now = int(time.time() * 1000)
            state: dict[str, Any] = {
                "kind": "perpsTrades",
                "instrument_id": instrument_id,
                "start_timestamp": start_ms if start_ms is not None else now - ONE_DAY_MS,
                "end_timestamp": end_ms if end_ms is not None else now,
                "seen_trade_ids": [],
            }
        else:
            state = decode_perps_trades_cursor(cursor)
        payload = await perps.get_json(
            "/v1/info/trades",
            params={
                "instrument_id": state["instrument_id"],
                "start_timestamp": state["start_timestamp"],
                "end_timestamp": state["end_timestamp"],
            },
        )
        data, more = parse_data_envelope(payload)
        seen: set[int] = set(cast("list[int]", state.get("seen_trade_ids", [])))
        fresh: list[dict[str, Any]] = []
        for raw_item in data:
            item = as_json_dict(raw_item)
            if item is not None and item.get("trade_id") not in seen:
                fresh.append(item)
        items = tuple(PerpsTrade.parse_response(item) for item in fresh)
        raw_last = as_json_dict(data[-1]) if data else None
        raw_last_ts = raw_last.get("timestamp") if raw_last is not None else None
        last = fresh[-1] if fresh else None
        cursor_ts = last.get("timestamp") if last is not None else raw_last_ts
        has_more = more and isinstance(cursor_ts, int) and cursor_ts > int(state["start_timestamp"])
        next_cursor = None
        if has_more and isinstance(cursor_ts, int):
            next_state: dict[str, Any]
            if last is None:
                next_state = {**state, "end_timestamp": cursor_ts - 1, "seen_trade_ids": []}
            else:
                boundary: set[int] = (
                    set(cast("list[int]", state.get("seen_trade_ids", [])))
                    if state["end_timestamp"] == cursor_ts
                    else set()
                )
                for item in fresh:
                    trade_id = item.get("trade_id")
                    if item.get("timestamp") == cursor_ts and isinstance(trade_id, int):
                        boundary.add(trade_id)
                next_state = {
                    **state,
                    "end_timestamp": cursor_ts,
                    "seen_trade_ids": sorted(boundary),
                }
            next_cursor = encode_perps_cursor(next_state)
        return Page(items=items, has_more=has_more, next_cursor=next_cursor)

    return AsyncPaginator(fetch=fetch)


def _tuple_timestamp(item: object) -> int | None:
    if isinstance(item, list):
        entries = cast("list[object]", item)
        if entries and isinstance(entries[0], int):
            return entries[0]
    return None


__all__ = [
    "fetch_book",
    "fetch_fees",
    "fetch_instruments",
    "fetch_ticker",
    "fetch_tickers",
    "list_candles",
    "list_funding_history",
    "list_trades",
]
