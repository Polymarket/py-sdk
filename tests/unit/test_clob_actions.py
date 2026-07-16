from decimal import Decimal
from typing import assert_type

import pytest

from polymarket._internal.actions.clob import (
    build_last_trade_price_request,
    build_last_trade_prices_request,
    build_midpoint_request,
    build_midpoints_request,
    build_order_book_request,
    build_order_books_request,
    build_price_history_request,
    build_price_request,
    build_prices_request,
    build_spread_request,
    build_spreads_request,
    parse_last_trade_price,
    parse_last_trade_prices,
    parse_midpoint,
    parse_midpoints,
    parse_order_book,
    parse_order_books,
    parse_price,
    parse_price_history,
    parse_prices,
    parse_spread,
    parse_spreads,
)
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models import OrderSide, PriceRequest, TokenId


def test_build_midpoint_request_targets_midpoint_path_with_token_id() -> None:
    path, params = build_midpoint_request(token_id="123")

    assert path == "/midpoint"
    assert params == {"token_id": "123"}


def test_build_midpoint_request_rejects_empty_token_id() -> None:
    with pytest.raises(UserInputError, match="token_id"):
        build_midpoint_request(token_id="")


def test_build_midpoint_request_rejects_non_string_token_id() -> None:
    with pytest.raises(UserInputError, match="must be a string"):
        build_midpoint_request(token_id=123)  # type: ignore[arg-type]


def test_build_order_book_request_rejects_non_string_token_id() -> None:
    with pytest.raises(UserInputError, match="must be a string"):
        build_order_book_request(token_id=123)  # type: ignore[arg-type]


def test_parse_midpoint_returns_decimal_for_decimal_string() -> None:
    assert parse_midpoint({"mid": "0.53"}) == Decimal("0.53")


def test_parse_midpoint_rejects_non_dict_response() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_midpoint([])


def test_parse_midpoint_rejects_missing_mid_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_midpoint({})


def test_parse_midpoint_rejects_non_decimal_mid_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_midpoint({"mid": "not-a-decimal"})


def test_build_midpoints_request_emits_post_body_with_each_token_id() -> None:
    path, body = build_midpoints_request(token_ids=["1", "2"])

    assert path == "/midpoints"
    assert body == [{"token_id": "1"}, {"token_id": "2"}]


def test_build_midpoints_request_rejects_empty_sequence() -> None:
    with pytest.raises(UserInputError):
        build_midpoints_request(token_ids=[])


def test_build_midpoints_request_rejects_empty_token_id_entry() -> None:
    with pytest.raises(UserInputError, match="token_id"):
        build_midpoints_request(token_ids=["1", ""])


def test_build_midpoints_request_rejects_bare_string() -> None:
    with pytest.raises(UserInputError, match="sequence"):
        build_midpoints_request(token_ids="123")  # type: ignore[arg-type]


def test_build_midpoints_request_rejects_non_string_entry() -> None:
    with pytest.raises(UserInputError, match="must be a string"):
        build_midpoints_request(token_ids=[1, 2])  # type: ignore[list-item]


def test_build_order_books_request_rejects_bare_string() -> None:
    with pytest.raises(UserInputError, match="sequence"):
        build_order_books_request(token_ids="123")  # type: ignore[arg-type]


def test_build_spreads_request_rejects_bare_string() -> None:
    with pytest.raises(UserInputError, match="sequence"):
        build_spreads_request(token_ids="123")  # type: ignore[arg-type]


def test_build_last_trade_prices_request_rejects_bare_string() -> None:
    with pytest.raises(UserInputError, match="sequence"):
        build_last_trade_prices_request(token_ids="123")  # type: ignore[arg-type]


def test_parse_midpoints_returns_decimal_keyed_by_token_id() -> None:
    result = parse_midpoints({"1": "0.5", "2": "0.4"})

    assert_type(result, dict[TokenId, Decimal])
    assert result == {
        TokenId("1"): Decimal("0.5"),
        TokenId("2"): Decimal("0.4"),
    }


def test_parse_midpoints_accepts_empty_dict() -> None:
    assert parse_midpoints({}) == {}


def test_parse_midpoints_rejects_non_dict() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_midpoints([])


def test_parse_midpoints_rejects_non_decimal_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_midpoints({"1": "bad"})


def test_parse_midpoints_rejects_numeric_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_midpoints({"1": 0.5})  # type: ignore[dict-item]


def test_parse_midpoint_rejects_numeric_mid_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_midpoint({"mid": 0.5})


def test_parse_price_rejects_numeric_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_price({"price": 0.52})


def test_parse_spread_rejects_numeric_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_spread({"spread": 0.02})


def test_build_price_request_includes_token_id_and_side() -> None:
    path, params = build_price_request(token_id="123", side="BUY")

    assert path == "/price"
    assert params == {"token_id": "123", "side": "BUY"}


def test_build_price_request_rejects_empty_token_id() -> None:
    with pytest.raises(UserInputError):
        build_price_request(token_id="", side="BUY")


def test_build_price_request_rejects_invalid_side() -> None:
    with pytest.raises(UserInputError, match="side"):
        build_price_request(token_id="1", side="HOLD")  # type: ignore[arg-type]


def test_parse_price_returns_decimal() -> None:
    assert parse_price({"price": "0.52"}) == Decimal("0.52")


def test_parse_price_rejects_missing_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_price({})


def test_build_prices_request_emits_post_body_with_token_id_and_side() -> None:
    path, body = build_prices_request(
        requests=[PriceRequest("1", "BUY"), PriceRequest("2", "SELL")]
    )

    assert path == "/prices"
    assert body == [
        {"token_id": "1", "side": "BUY"},
        {"token_id": "2", "side": "SELL"},
    ]


def test_build_prices_request_rejects_empty_sequence() -> None:
    with pytest.raises(UserInputError):
        build_prices_request(requests=[])


def test_build_prices_request_rejects_empty_token_id() -> None:
    with pytest.raises(UserInputError):
        build_prices_request(requests=[PriceRequest("", "BUY")])


def test_build_prices_request_rejects_invalid_side() -> None:
    with pytest.raises(UserInputError, match="side"):
        build_prices_request(requests=[PriceRequest("1", "HOLD")])  # type: ignore[list-item]


def test_build_prices_request_rejects_single_price_request_passed_directly() -> None:
    with pytest.raises(UserInputError, match="sequence"):
        build_prices_request(requests=PriceRequest("1", "BUY"))  # type: ignore[arg-type]


def test_build_prices_request_rejects_plain_tuple_entry() -> None:
    with pytest.raises(UserInputError, match="must be a PriceRequest"):
        build_prices_request(requests=[("1", "BUY")])  # type: ignore[list-item]


def test_build_prices_request_rejects_dict_entry() -> None:
    with pytest.raises(UserInputError, match="must be a PriceRequest"):
        build_prices_request(requests=[{"token_id": "1", "side": "BUY"}])  # type: ignore[list-item]


def test_parse_prices_returns_nested_decimal_dict() -> None:
    result = parse_prices({"1": {"BUY": "0.52", "SELL": "0.53"}})

    assert_type(result, dict[TokenId, dict[OrderSide, Decimal]])
    assert result == {TokenId("1"): {"BUY": Decimal("0.52"), "SELL": Decimal("0.53")}}


def test_parse_prices_rejects_invalid_side_key() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_prices({"1": {"HOLD": "0.5"}})


_ORDER_BOOK_PAYLOAD = {
    "market": "0xMARKET",
    "asset_id": "8501497",
    "timestamp": "1716000000000",
    "bids": [{"price": "0.51", "size": "100"}],
    "asks": [{"price": "0.53", "size": "200"}, {"price": "0.54", "size": "50"}],
    "min_order_size": "5",
    "tick_size": "0.01",
    "neg_risk": False,
    "last_trade_price": "0.52",
    "hash": "abc123",
}


def test_build_order_book_request_targets_book_path() -> None:
    path, params = build_order_book_request(token_id="123")

    assert path == "/book"
    assert params == {"token_id": "123"}


def test_parse_order_book_parses_full_response() -> None:
    book = parse_order_book(_ORDER_BOOK_PAYLOAD)

    assert book.market == "0xMARKET"
    assert book.token_id == "8501497"
    assert book.timestamp is not None
    assert book.min_order_size == Decimal("5")
    assert book.tick_size == Decimal("0.01")
    assert book.neg_risk is False
    assert book.last_trade_price == Decimal("0.52")
    assert book.hash == "abc123"
    assert len(book.bids) == 1
    assert book.bids[0].price == Decimal("0.51")
    assert book.bids[0].size == Decimal("100")
    assert len(book.asks) == 2


def test_parse_order_book_accepts_null_timestamp_and_null_last_trade_price() -> None:
    payload = {**_ORDER_BOOK_PAYLOAD, "timestamp": None, "last_trade_price": None}

    book = parse_order_book(payload)

    assert book.timestamp is None
    assert book.last_trade_price is None


def test_parse_order_book_accepts_missing_timestamp_and_last_trade_price() -> None:
    payload = {
        k: v for k, v in _ORDER_BOOK_PAYLOAD.items() if k not in ("timestamp", "last_trade_price")
    }

    book = parse_order_book(payload)

    assert book.timestamp is None
    assert book.last_trade_price is None


def test_parse_order_book_rejects_malformed_timestamp() -> None:
    payload = {**_ORDER_BOOK_PAYLOAD, "timestamp": "not-a-number"}

    with pytest.raises(UnexpectedResponseError):
        parse_order_book(payload)


@pytest.mark.parametrize("bad_value", [" 1716000000000", "1716000000000 ", "+1", "-1"])
def test_parse_order_book_rejects_loose_numeric_timestamp_strings(bad_value: str) -> None:
    payload = {**_ORDER_BOOK_PAYLOAD, "timestamp": bad_value}

    with pytest.raises(UnexpectedResponseError):
        parse_order_book(payload)


def test_parse_order_book_rejects_missing_required_field() -> None:
    payload = {k: v for k, v in _ORDER_BOOK_PAYLOAD.items() if k != "asset_id"}

    with pytest.raises(UnexpectedResponseError):
        parse_order_book(payload)


def test_parse_order_book_rejects_missing_bids() -> None:
    payload = {k: v for k, v in _ORDER_BOOK_PAYLOAD.items() if k != "bids"}

    with pytest.raises(UnexpectedResponseError):
        parse_order_book(payload)


def test_parse_order_book_rejects_missing_asks() -> None:
    payload = {k: v for k, v in _ORDER_BOOK_PAYLOAD.items() if k != "asks"}

    with pytest.raises(UnexpectedResponseError):
        parse_order_book(payload)


def test_parse_order_book_accepts_empty_bids_and_asks_explicitly() -> None:
    payload = {**_ORDER_BOOK_PAYLOAD, "bids": [], "asks": []}

    book = parse_order_book(payload)

    assert book.bids == ()
    assert book.asks == ()


def test_parse_order_book_rejects_numeric_price_level() -> None:
    payload = {
        **_ORDER_BOOK_PAYLOAD,
        "bids": [{"price": 0.51, "size": "100"}],
    }

    with pytest.raises(UnexpectedResponseError):
        parse_order_book(payload)


def test_parse_order_book_rejects_numeric_tick_size() -> None:
    payload = {**_ORDER_BOOK_PAYLOAD, "tick_size": 0.01}

    with pytest.raises(UnexpectedResponseError):
        parse_order_book(payload)


def test_build_order_books_request_emits_post_body() -> None:
    path, body = build_order_books_request(token_ids=["1", "2"])

    assert path == "/books"
    assert body == [{"token_id": "1"}, {"token_id": "2"}]


def test_parse_order_books_returns_tuple() -> None:
    result = parse_order_books([_ORDER_BOOK_PAYLOAD, _ORDER_BOOK_PAYLOAD])

    assert isinstance(result, tuple)
    assert len(result) == 2
    assert result[0].token_id == "8501497"


def test_parse_order_books_accepts_empty_list() -> None:
    assert parse_order_books([]) == ()


def test_parse_order_books_rejects_non_list() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_order_books({})


def test_build_spread_request_targets_spread_path() -> None:
    path, params = build_spread_request(token_id="123")

    assert path == "/spread"
    assert params == {"token_id": "123"}


def test_parse_spread_returns_decimal() -> None:
    assert parse_spread({"spread": "0.02"}) == Decimal("0.02")


def test_parse_spread_rejects_missing_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_spread({})


def test_build_spreads_request_emits_post_body() -> None:
    path, body = build_spreads_request(token_ids=["1"])

    assert path == "/spreads"
    assert body == [{"token_id": "1"}]


def test_parse_spreads_returns_decimal_keyed_by_token_id() -> None:
    result = parse_spreads({"1": "0.02"})

    assert_type(result, dict[TokenId, Decimal])
    assert result == {TokenId("1"): Decimal("0.02")}


def test_build_last_trade_price_request_targets_last_trade_price_path() -> None:
    path, params = build_last_trade_price_request(token_id="123")

    assert path == "/last-trade-price"
    assert params == {"token_id": "123"}


def test_parse_last_trade_price_returns_model() -> None:
    result = parse_last_trade_price({"price": "0.53", "side": "BUY"})

    assert result.price == Decimal("0.53")
    assert result.side == "BUY"


def test_parse_last_trade_price_rejects_invalid_side() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_last_trade_price({"price": "0.5", "side": "HOLD"})


def test_build_last_trade_prices_request_emits_post_body_at_correct_path() -> None:
    path, body = build_last_trade_prices_request(token_ids=["1", "2"])

    assert path == "/last-trades-prices"
    assert body == [{"token_id": "1"}, {"token_id": "2"}]


def test_parse_last_trade_prices_returns_tuple_of_models() -> None:
    payload = [
        {"token_id": "1", "price": "0.5", "side": "BUY"},
        {"token_id": "2", "price": "0.6", "side": "SELL"},
    ]

    result = parse_last_trade_prices(payload)

    assert len(result) == 2
    assert result[0].token_id == "1"
    assert result[0].price == Decimal("0.5")
    assert result[0].side == "BUY"


def test_build_price_history_request_maps_token_id_to_market_param() -> None:
    path, params = build_price_history_request(token_id="123")

    assert path == "/prices-history"
    assert params == {"market": "123"}


def test_build_price_history_request_preserves_camelcase_optional_params() -> None:
    path, params = build_price_history_request(
        token_id="123",
        start_ts=1000,
        end_ts=2000,
        fidelity=60,
        interval="1d",
    )

    assert path == "/prices-history"
    assert params == {
        "market": "123",
        "startTs": 1000,
        "endTs": 2000,
        "fidelity": 60,
        "interval": "1d",
    }


def test_build_price_history_request_rejects_empty_token_id() -> None:
    with pytest.raises(UserInputError):
        build_price_history_request(token_id="")


def test_build_price_history_request_rejects_negative_start_ts() -> None:
    with pytest.raises(UserInputError):
        build_price_history_request(token_id="1", start_ts=-1)


def test_build_price_history_request_rejects_non_positive_fidelity() -> None:
    with pytest.raises(UserInputError):
        build_price_history_request(token_id="1", fidelity=0)


def test_build_price_history_request_rejects_invalid_interval() -> None:
    with pytest.raises(UserInputError, match="interval"):
        build_price_history_request(token_id="1", interval="weekly")  # type: ignore[arg-type]


def test_build_price_history_request_rejects_float_start_ts() -> None:
    with pytest.raises(UserInputError, match="integer"):
        build_price_history_request(token_id="1", start_ts=1.5)  # type: ignore[arg-type]


def test_build_price_history_request_rejects_bool_fidelity() -> None:
    with pytest.raises(UserInputError, match="integer"):
        build_price_history_request(token_id="1", fidelity=True)  # type: ignore[arg-type]


def test_parse_price_history_extracts_history_array() -> None:
    payload = {"history": [{"t": 1000, "p": 0.5}, {"t": 1060, "p": 0.51}]}

    result = parse_price_history(payload)

    assert len(result) == 2
    assert result[0].t == 1000
    assert result[0].p == 0.5


def test_parse_price_history_accepts_empty_history() -> None:
    assert parse_price_history({"history": []}) == ()


def test_parse_price_history_rejects_missing_history_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_price_history({})


def test_parse_price_history_rejects_non_dict_response() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_price_history([])


def test_parse_price_history_rejects_string_t_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_price_history({"history": [{"t": "1000", "p": 0.5}]})


def test_parse_price_history_rejects_string_p_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_price_history({"history": [{"t": 1000, "p": "0.5"}]})
