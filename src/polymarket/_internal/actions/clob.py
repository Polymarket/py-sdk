from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated, cast

from pydantic import BeforeValidator, TypeAdapter, ValidationError, field_validator

from polymarket._internal.request import QueryParamValue
from polymarket._internal.validation import require_nonempty
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models._validators import parse_decimal_string
from polymarket.models.base import BaseModel
from polymarket.models.clob import (
    LastTradePrice,
    LastTradePriceForToken,
    OrderBook,
    PriceHistoryInterval,
    PriceHistoryPoint,
    PriceRequest,
)
from polymarket.models.types import OrderSide, TokenId


class _MidpointResponse(BaseModel):
    mid: Decimal

    @field_validator("mid", mode="before")
    @classmethod
    def _parse_mid(cls, value: object) -> object:
        return parse_decimal_string(value)


class _PriceResponse(BaseModel):
    price: Decimal

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> object:
        return parse_decimal_string(value)


class _SpreadResponse(BaseModel):
    spread: Decimal

    @field_validator("spread", mode="before")
    @classmethod
    def _parse_spread(cls, value: object) -> object:
        return parse_decimal_string(value)


_PRICE_HISTORY_INTERVALS: frozenset[str] = frozenset({"max", "1w", "1d", "6h", "1h"})
_VALID_ORDER_SIDES: frozenset[str] = frozenset({"BUY", "SELL"})

_StrictDecimalValue = Annotated[Decimal, BeforeValidator(parse_decimal_string)]

_MidpointsAdapter = TypeAdapter(dict[TokenId, _StrictDecimalValue])
_SpreadsAdapter = TypeAdapter(dict[TokenId, _StrictDecimalValue])
_PricesAdapter = TypeAdapter(dict[TokenId, dict[OrderSide, _StrictDecimalValue]])
_OrderBookListAdapter = TypeAdapter(tuple[OrderBook, ...])
_LastTradePriceListAdapter = TypeAdapter(tuple[LastTradePriceForToken, ...])
_PriceHistoryListAdapter = TypeAdapter(tuple[PriceHistoryPoint, ...])


def _require_string_token_id(token_id: object) -> str:
    if not isinstance(token_id, str):
        raise UserInputError(f"token_id must be a string, got {type(token_id).__name__}.")
    return require_nonempty("token_id", token_id)


def _validate_side(side: object) -> None:
    if side not in _VALID_ORDER_SIDES:
        raise UserInputError(f"side must be 'BUY' or 'SELL', got {side!r}.")


def _require_nonneg_int(name: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise UserInputError(f"{name} must be an integer.")
    if value < 0:
        raise UserInputError(f"{name} must be a non-negative integer.")


def _require_positive_int(name: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise UserInputError(f"{name} must be an integer.")
    if value <= 0:
        raise UserInputError(f"{name} must be a positive integer.")


def _require_nonempty_token_ids(token_ids: Sequence[str]) -> tuple[str, ...]:
    if isinstance(token_ids, str | bytes):
        raise UserInputError("token_ids must be a sequence of strings, not a single string.")
    if not token_ids:
        raise UserInputError("token_ids must be a non-empty sequence.")
    return tuple(_require_string_token_id(tid) for tid in token_ids)


def _require_nonempty_price_requests(requests: Sequence[PriceRequest]) -> tuple[PriceRequest, ...]:
    if isinstance(requests, str | bytes | PriceRequest):
        raise UserInputError("requests must be a sequence of PriceRequest values.")
    if not requests:
        raise UserInputError("requests must be a non-empty sequence.")
    result: list[PriceRequest] = []
    for raw in cast(Sequence[object], requests):
        if not isinstance(raw, PriceRequest):
            raise UserInputError(f"each entry must be a PriceRequest, got {type(raw).__name__}.")
        token_id = _require_string_token_id(raw.token_id)
        _validate_side(raw.side)
        result.append(PriceRequest(token_id, raw.side))
    return tuple(result)


def build_midpoint_request(*, token_id: str) -> tuple[str, dict[str, str]]:
    return "/midpoint", {"token_id": _require_string_token_id(token_id)}


def parse_midpoint(data: object) -> Decimal:
    return _MidpointResponse.parse_response(data).mid


def build_midpoints_request(*, token_ids: Sequence[str]) -> tuple[str, list[dict[str, str]]]:
    validated = _require_nonempty_token_ids(token_ids)
    return "/midpoints", [{"token_id": tid} for tid in validated]


def parse_midpoints(data: object) -> dict[TokenId, Decimal]:
    try:
        return _MidpointsAdapter.validate_python(data)
    except ValidationError as error:
        raise UnexpectedResponseError("midpoints response did not match expected shape") from error


def build_price_request(*, token_id: str, side: OrderSide) -> tuple[str, dict[str, str]]:
    validated = _require_string_token_id(token_id)
    _validate_side(side)
    return "/price", {"token_id": validated, "side": side}


def parse_price(data: object) -> Decimal:
    return _PriceResponse.parse_response(data).price


def build_prices_request(*, requests: Sequence[PriceRequest]) -> tuple[str, list[dict[str, str]]]:
    validated = _require_nonempty_price_requests(requests)
    return "/prices", [{"token_id": r.token_id, "side": r.side} for r in validated]


def parse_prices(data: object) -> dict[TokenId, dict[OrderSide, Decimal]]:
    try:
        return _PricesAdapter.validate_python(data)
    except ValidationError as error:
        raise UnexpectedResponseError("prices response did not match expected shape") from error


def build_order_book_request(*, token_id: str) -> tuple[str, dict[str, str]]:
    return "/book", {"token_id": _require_string_token_id(token_id)}


def parse_order_book(data: object) -> OrderBook:
    return OrderBook.parse_response(data)


def build_order_books_request(*, token_ids: Sequence[str]) -> tuple[str, list[dict[str, str]]]:
    validated = _require_nonempty_token_ids(token_ids)
    return "/books", [{"token_id": tid} for tid in validated]


def parse_order_books(data: object) -> tuple[OrderBook, ...]:
    try:
        return _OrderBookListAdapter.validate_python(data)
    except ValidationError as error:
        raise UnexpectedResponseError(
            "order books response did not match expected shape"
        ) from error


def build_spread_request(*, token_id: str) -> tuple[str, dict[str, str]]:
    return "/spread", {"token_id": _require_string_token_id(token_id)}


def parse_spread(data: object) -> Decimal:
    return _SpreadResponse.parse_response(data).spread


def build_spreads_request(*, token_ids: Sequence[str]) -> tuple[str, list[dict[str, str]]]:
    validated = _require_nonempty_token_ids(token_ids)
    return "/spreads", [{"token_id": tid} for tid in validated]


def parse_spreads(data: object) -> dict[TokenId, Decimal]:
    try:
        return _SpreadsAdapter.validate_python(data)
    except ValidationError as error:
        raise UnexpectedResponseError("spreads response did not match expected shape") from error


def build_last_trade_price_request(*, token_id: str) -> tuple[str, dict[str, str]]:
    return "/last-trade-price", {"token_id": _require_string_token_id(token_id)}


def parse_last_trade_price(data: object) -> LastTradePrice:
    return LastTradePrice.parse_response(data)


def build_last_trade_prices_request(
    *, token_ids: Sequence[str]
) -> tuple[str, list[dict[str, str]]]:
    validated = _require_nonempty_token_ids(token_ids)
    return "/last-trades-prices", [{"token_id": tid} for tid in validated]


def parse_last_trade_prices(data: object) -> tuple[LastTradePriceForToken, ...]:
    try:
        return _LastTradePriceListAdapter.validate_python(data)
    except ValidationError as error:
        raise UnexpectedResponseError(
            "last trade prices response did not match expected shape"
        ) from error


def build_price_history_request(
    *,
    token_id: str,
    start_ts: int | None = None,
    end_ts: int | None = None,
    fidelity: int | None = None,
    interval: PriceHistoryInterval | None = None,
) -> tuple[str, dict[str, QueryParamValue]]:
    validated_token_id = _require_string_token_id(token_id)
    _require_nonneg_int("start_ts", start_ts)
    _require_nonneg_int("end_ts", end_ts)
    _require_positive_int("fidelity", fidelity)
    if interval is not None and interval not in _PRICE_HISTORY_INTERVALS:
        raise UserInputError(
            f"interval must be one of {sorted(_PRICE_HISTORY_INTERVALS)}, got {interval!r}."
        )

    params: dict[str, QueryParamValue] = {"market": validated_token_id}
    if start_ts is not None:
        params["startTs"] = start_ts
    if end_ts is not None:
        params["endTs"] = end_ts
    if fidelity is not None:
        params["fidelity"] = fidelity
    if interval is not None:
        params["interval"] = interval
    return "/prices-history", params


def parse_price_history(data: object) -> tuple[PriceHistoryPoint, ...]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("price history response did not match expected shape")
    history = cast(dict[str, object], data).get("history")
    try:
        return _PriceHistoryListAdapter.validate_python(history)
    except ValidationError as error:
        raise UnexpectedResponseError(
            "price history response did not match expected shape"
        ) from error


__all__ = [
    "build_last_trade_price_request",
    "build_last_trade_prices_request",
    "build_midpoint_request",
    "build_midpoints_request",
    "build_order_book_request",
    "build_order_books_request",
    "build_price_history_request",
    "build_price_request",
    "build_prices_request",
    "build_spread_request",
    "build_spreads_request",
    "parse_last_trade_price",
    "parse_last_trade_prices",
    "parse_midpoint",
    "parse_midpoints",
    "parse_order_book",
    "parse_order_books",
    "parse_price",
    "parse_price_history",
    "parse_prices",
    "parse_spread",
    "parse_spreads",
]
