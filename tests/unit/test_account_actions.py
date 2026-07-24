from typing import Any

import pytest

from polymarket._internal.actions.account import (
    END_CURSOR,
    build_balance_allowance_request,
    build_closed_only_mode_request,
    build_drop_notifications_request,
    build_get_order_request,
    build_list_account_trades_request,
    build_list_open_orders_request,
    build_notifications_request,
    parse_account_trades_page,
    parse_balance_allowance,
    parse_closed_only_mode,
    parse_notifications,
    parse_open_order,
    parse_open_orders_page,
)
from polymarket.errors import UnexpectedResponseError, UserInputError

_OPEN_ORDER_PAYLOAD: dict[str, Any] = {
    "asset_id": "8501497",
    "associate_trades": ["trade-1"],
    "created_at": 1700000000000,
    "expiration": 1800000000000,
    "id": "order-1",
    "maker_address": "0xMAKER",
    "market": "0xMARKET",
    "order_type": "GTC",
    "original_size": "100",
    "outcome": "Yes",
    "owner": "0xOWNER",
    "price": "0.5",
    "side": "BUY",
    "size_matched": "50",
    "status": "LIVE",
}

_CLOB_TRADE_PAYLOAD: dict[str, Any] = {
    "asset_id": "8501497",
    "bucket_index": 7,
    "fee_rate_bps": "10",
    "id": "trade-1",
    "last_update": 1700000010000,
    "maker_address": "0xMAKER",
    "maker_orders": [
        {
            "asset_id": "8501497",
            "fee_rate_bps": "10",
            "maker_address": "0xMAKER",
            "matched_amount": "5",
            "order_id": "order-1",
            "outcome": "Yes",
            "owner": "0xOWNER",
            "price": "0.5",
            "side": "BUY",
        }
    ],
    "market": "0xMARKET",
    "match_time": 1700000000000,
    "outcome": "Yes",
    "owner": "0xOWNER",
    "price": "0.5",
    "side": "BUY",
    "size": "5",
    "status": "MINED",
    "taker_order_id": "order-2",
    "trader_side": "TAKER",
    "transaction_hash": "0xTX",
}


def test_build_closed_only_mode_request_targets_correct_path() -> None:
    path, params = build_closed_only_mode_request()
    assert path == "/auth/ban-status/closed-only"
    assert params == {}


def test_parse_closed_only_mode_returns_bool() -> None:
    assert parse_closed_only_mode({"closed_only": True}) is True
    assert parse_closed_only_mode({"closed_only": False}) is False


def test_parse_closed_only_mode_rejects_non_bool() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_closed_only_mode({"closed_only": "false"})


def test_parse_closed_only_mode_rejects_missing_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_closed_only_mode({})


def test_build_list_open_orders_request_includes_all_filter_params() -> None:
    path, params = build_list_open_orders_request(
        token_id="t1", id="order-1", market="0xMARKET", cursor="abc"
    )
    assert path == "/data/orders"
    assert params == {
        "asset_id": "t1",
        "id": "order-1",
        "market": "0xMARKET",
        "next_cursor": "abc",
    }


def test_build_list_open_orders_request_omits_unset_params() -> None:
    path, params = build_list_open_orders_request()
    assert path == "/data/orders"
    assert params == {}


def test_parse_open_orders_page_decodes_end_cursor_as_none() -> None:
    page = parse_open_orders_page(
        {"data": [_OPEN_ORDER_PAYLOAD], "next_cursor": END_CURSOR, "count": 1}
    )
    assert page.next_cursor is None
    assert page.total_count is None
    assert len(page.items) == 1
    assert page.items[0].id == "order-1"


def test_parse_open_orders_page_keeps_non_terminal_cursor() -> None:
    page = parse_open_orders_page({"data": [], "next_cursor": "next-page-token", "count": 0})
    assert page.next_cursor == "next-page-token"


def test_parse_open_orders_page_rejects_non_dict() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_open_orders_page([])


def test_parse_open_orders_page_returns_none_total_count_when_missing() -> None:
    page = parse_open_orders_page({"data": [], "next_cursor": END_CURSOR})
    assert page.total_count is None
    assert page.next_cursor is None


def test_parse_open_orders_page_treats_missing_next_cursor_as_terminal() -> None:
    page = parse_open_orders_page({"data": [], "count": 0})
    assert page.next_cursor is None
    assert page.has_more is False


def test_parse_open_orders_page_rejects_non_string_next_cursor() -> None:
    with pytest.raises(UnexpectedResponseError, match="next_cursor"):
        parse_open_orders_page({"data": [], "next_cursor": 42})


def test_build_get_order_request_includes_order_id_in_path() -> None:
    path, params = build_get_order_request(order_id="order-1")
    assert path == "/data/order/order-1"
    assert params == {}


def test_build_get_order_request_rejects_empty_order_id() -> None:
    with pytest.raises(UserInputError):
        build_get_order_request(order_id="")


def test_parse_open_order_succeeds_on_valid_payload() -> None:
    order = parse_open_order(_OPEN_ORDER_PAYLOAD)
    assert order.id == "order-1"
    assert order.token_id == "8501497"


def test_build_list_account_trades_request_includes_filters_and_cursor() -> None:
    path, params = build_list_account_trades_request(
        token_id="t1",
        market="0xMARKET",
        maker_address="0xMAKER",
        after="100",
        before="200",
        cursor="next",
    )
    assert path == "/data/trades"
    assert params == {
        "asset_id": "t1",
        "market": "0xMARKET",
        "maker_address": "0xMAKER",
        "after": "100",
        "before": "200",
        "next_cursor": "next",
    }


def test_parse_account_trades_page_returns_empty_tuple_for_empty_data() -> None:
    page = parse_account_trades_page({"data": [], "next_cursor": END_CURSOR, "count": 0})
    assert page.items == ()
    assert page.next_cursor is None


def test_parse_account_trades_page_parses_full_trade() -> None:
    page = parse_account_trades_page(
        {"data": [_CLOB_TRADE_PAYLOAD], "next_cursor": END_CURSOR, "count": 1}
    )
    assert len(page.items) == 1
    trade = page.items[0]
    assert trade.id == "trade-1"
    assert trade.maker_orders[0].order_id == "order-1"
    assert trade.trader_side == "TAKER"


def test_build_notifications_request_includes_signature_type() -> None:
    path, params = build_notifications_request(signature_type=3)
    assert path == "/notifications"
    assert params == {"signature_type": 3}


def test_parse_notifications_decodes_payload() -> None:
    result = parse_notifications(
        [
            {
                "id": 7,
                "owner": "0xOWNER",
                "type": 1,
                "payload": {"order_id": "x"},
                "timestamp": 1700000000000,
            }
        ]
    )
    assert len(result) == 1
    assert result[0].id == 7
    assert result[0].type == 1


def test_parse_notifications_rejects_non_list() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_notifications({})


def test_build_drop_notifications_request_joins_ids_and_sends_signature_type() -> None:
    path, params = build_drop_notifications_request(ids=["a", "b", "c"], signature_type=2)
    assert path == "/notifications"
    assert params == {"ids": "a,b,c", "signature_type": 2}


def test_build_drop_notifications_request_rejects_empty_sequence() -> None:
    with pytest.raises(UserInputError):
        build_drop_notifications_request(ids=[], signature_type=0)


def test_build_drop_notifications_request_rejects_bare_string() -> None:
    with pytest.raises(UserInputError, match="sequence"):
        build_drop_notifications_request(ids="abc", signature_type=0)  # type: ignore[arg-type]


def test_build_drop_notifications_request_rejects_empty_id_entry() -> None:
    with pytest.raises(UserInputError, match="notification id"):
        build_drop_notifications_request(ids=["", "b"], signature_type=0)


def test_build_drop_notifications_request_stringifies_int_ids() -> None:
    path, params = build_drop_notifications_request(ids=[1, 2, 3], signature_type=0)
    assert path == "/notifications"
    assert params == {"ids": "1,2,3", "signature_type": 0}


def test_build_drop_notifications_request_accepts_mixed_int_and_string_ids() -> None:
    _, params = build_drop_notifications_request(ids=[1, "2", 3], signature_type=0)
    assert params["ids"] == "1,2,3"


def test_build_balance_allowance_request_includes_signature_type_and_asset_type() -> None:
    path, params = build_balance_allowance_request(
        asset_type="COLLATERAL", token_id=None, signature_type=0
    )
    assert path == "/balance-allowance"
    assert params == {"asset_type": "COLLATERAL", "signature_type": 0}


def test_build_balance_allowance_request_adds_token_id_for_conditional() -> None:
    path, params = build_balance_allowance_request(
        asset_type="CONDITIONAL", token_id="t1", signature_type=1
    )
    assert path == "/balance-allowance"
    assert params == {
        "asset_type": "CONDITIONAL",
        "signature_type": 1,
        "token_id": "t1",
    }


def test_build_balance_allowance_request_rejects_invalid_asset_type() -> None:
    with pytest.raises(UserInputError, match="asset_type"):
        build_balance_allowance_request(
            asset_type="STAKE",  # type: ignore[arg-type]
            token_id=None,
            signature_type=0,
        )


def test_parse_balance_allowance_returns_model() -> None:
    result = parse_balance_allowance(
        {
            "balance": "5000000",
            "allowances": {"0xABCDEF": "1000000", "0x123456": "2000000"},
        }
    )
    assert result.balance == 5000000
    assert result.allowances == {"0xABCDEF": 1000000, "0x123456": 2000000}


def test_parse_balance_allowance_rejects_missing_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_balance_allowance({"balance": "0"})
