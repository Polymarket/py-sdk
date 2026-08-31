import pytest

from polymarket._internal.actions.orders.cancel import (
    build_cancel_all_request,
    build_cancel_market_orders_request,
    build_cancel_order_request,
    build_cancel_orders_request,
    parse_cancel_orders_response,
)
from polymarket.errors import UnexpectedResponseError, UserInputError


def test_build_cancel_order_request_uses_capital_order_id_key() -> None:
    path, body = build_cancel_order_request(order_id="ord-1")
    assert path == "/order"
    assert body == {"orderID": "ord-1"}


def test_build_cancel_order_request_rejects_empty_id() -> None:
    with pytest.raises(UserInputError):
        build_cancel_order_request(order_id="")


def test_build_cancel_orders_request_returns_list_payload() -> None:
    path, body = build_cancel_orders_request(order_ids=["a", "b", "c"])
    assert path == "/orders"
    assert body == ["a", "b", "c"]


def test_build_cancel_orders_request_rejects_empty_list() -> None:
    with pytest.raises(UserInputError, match="non-empty"):
        build_cancel_orders_request(order_ids=[])


def test_build_cancel_orders_request_rejects_bare_string() -> None:
    with pytest.raises(UserInputError, match="sequence"):
        build_cancel_orders_request(order_ids="abc")  # type: ignore[arg-type]


def test_build_cancel_orders_request_rejects_over_three_thousand() -> None:
    with pytest.raises(UserInputError, match="3000"):
        build_cancel_orders_request(order_ids=["x"] * 3001)


def test_build_cancel_all_request_has_no_body() -> None:
    path, body = build_cancel_all_request()
    assert path == "/cancel-all"
    assert body is None


def test_build_cancel_market_orders_request_requires_condition_or_asset() -> None:
    with pytest.raises(UserInputError, match="condition_id or asset_id"):
        build_cancel_market_orders_request()


def test_build_cancel_market_orders_request_includes_provided_filters() -> None:
    path, body = build_cancel_market_orders_request(market="0xMARKET", token_id="8501497")
    assert path == "/cancel-market-orders"
    assert body == {"asset_id": "8501497", "market": "0xMARKET"}


def test_build_cancel_market_orders_request_token_only() -> None:
    _, body = build_cancel_market_orders_request(token_id="8501497")
    assert body == {"asset_id": "8501497"}


def test_parse_cancel_orders_response_returns_model() -> None:
    parsed = parse_cancel_orders_response(
        {"canceled": ["a", "b"], "not_canceled": {"c": "in flight"}}
    )
    assert parsed.canceled == ("a", "b")
    assert parsed.not_canceled == {"c": "in flight"}


def test_parse_cancel_orders_response_accepts_empty_collections() -> None:
    parsed = parse_cancel_orders_response({"canceled": [], "not_canceled": {}})
    assert parsed.canceled == ()
    assert parsed.not_canceled == {}


def test_parse_cancel_orders_response_rejects_non_dict() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_cancel_orders_response([])
