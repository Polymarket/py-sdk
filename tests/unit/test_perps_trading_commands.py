"""Perps trading command construction tests."""

from typing import Any, cast

import pytest

from polymarket._internal.actions.perps.signing import build_perps_op_typed_data
from polymarket._internal.actions.perps.trading import (
    auto_cancel_op,
    cancel_all_orders_op,
    cancel_orders_by_client_id_op,
    cancel_orders_op,
    create_orders_op,
    to_command_body_op,
    to_raw_order,
    to_raw_tp_sl_order,
    update_leverage_op,
)
from polymarket.errors import UserInputError
from polymarket.models.perps.requests import (
    PerpsOrderRequest,
    PerpsPositionTpSlTrigger,
    PerpsTpSlTrigger,
)

# Pinned by the TypeScript SDK trading suite for the same command.
_CREATE_ORDER_DATA_HASH = "0x817207b7b8b31044a8f27e43c16e24d9fd5e11d3f106feb962f104f3ef28d52a"


def test_create_orders_hash_matches_typescript_suite() -> None:
    request = PerpsOrderRequest(
        instrument_id=1,
        side="BUY",
        price="100.50",
        quantity="10",
        time_in_force="gtc",
    )
    op = create_orders_op([to_raw_order(request)])
    payload = build_perps_op_typed_data(
        chain_id=31_337, op=op, salt=1, timestamp_ms=1_739_491_200_000
    )
    assert payload["message"]["data"] == _CREATE_ORDER_DATA_HASH
    assert to_command_body_op(op) == {
        "type": "createOrders",
        "args": [{"iid": 1, "buy": True, "po": False, "qty": "10", "tif": "gtc", "p": "100.50"}],
    }


def test_market_style_order_omits_price_from_body() -> None:
    request = PerpsOrderRequest(instrument_id=2, side="SELL", quantity="1.5", time_in_force="ioc")
    body = to_command_body_op(create_orders_op([to_raw_order(request)]))
    assert body["args"] == [{"iid": 2, "buy": False, "po": False, "qty": "1.5", "tif": "ioc"}]


def test_reduce_only_order_sets_body_flag() -> None:
    request = PerpsOrderRequest(
        instrument_id=2,
        side="SELL",
        price="99",
        quantity="1.5",
        reduce_only=True,
        time_in_force="ioc",
    )
    body = to_command_body_op(create_orders_op([to_raw_order(request)]))
    assert body["args"] == [
        {"iid": 2, "buy": False, "po": False, "qty": "1.5", "ro": True, "tif": "ioc", "p": "99"}
    ]


def test_client_order_id_round_trips_into_body() -> None:
    request = PerpsOrderRequest(
        instrument_id=3,
        side="BUY",
        price="1",
        quantity="2",
        time_in_force="gtc",
        client_order_id="aabbccddeeff00112233445566778899",
    )
    body = to_command_body_op(create_orders_op([to_raw_order(request)]))
    assert body["args"][0]["c"] == "aabbccddeeff00112233445566778899"


def test_tp_sl_rows_carry_reduce_only_and_trigger_metadata() -> None:
    market_trigger = to_raw_tp_sl_order(
        buy=False,
        instrument_id=7,
        kind="tp",
        quantity="3",
        trigger=PerpsTpSlTrigger(trigger_price="200"),
    )
    limit_trigger = to_raw_tp_sl_order(
        buy=False,
        instrument_id=7,
        kind="sl",
        quantity="3",
        trigger=PerpsTpSlTrigger(trigger_price="49", limit_price="50"),
    )
    op = create_orders_op([market_trigger, limit_trigger], group="order")
    body = to_command_body_op(op)
    assert body["grp"] == "order"
    assert body["args"][0] == {
        "iid": 7,
        "buy": False,
        "po": False,
        "qty": "3",
        "ro": True,
        "tr": {"tpsl": "tp", "trp": "200", "market": True},
    }
    assert body["args"][1] == {
        "iid": 7,
        "buy": False,
        "po": False,
        "qty": "3",
        "ro": True,
        "p": "50",
        "tr": {"tpsl": "sl", "trp": "49"},
    }


def test_position_tp_sl_uses_zero_quantity() -> None:
    row = to_raw_tp_sl_order(
        buy=True,
        instrument_id=9,
        kind="sl",
        quantity="0",
        trigger=PerpsPositionTpSlTrigger(trigger_price="10"),
    )
    body = to_command_body_op(create_orders_op([row], group="position"))
    assert body["grp"] == "position"
    assert body["args"][0]["qty"] == "0"


def test_cancel_and_leverage_ops() -> None:
    assert to_command_body_op(cancel_orders_op([11, 22])) == {
        "type": "cancelOrders",
        "args": [11, 22],
    }
    assert to_command_body_op(
        cancel_orders_by_client_id_op(["aabbccddeeff00112233445566778899"])
    ) == {"type": "cancelOrdersCOID", "args": ["aabbccddeeff00112233445566778899"]}
    assert cancel_all_orders_op() == ["cancelAll", []]
    assert to_command_body_op(cancel_all_orders_op()) == {"type": "cancelAll", "args": {}}
    assert cancel_all_orders_op(instrument_id=3) == ["cancelAll", [3]]
    assert to_command_body_op(cancel_all_orders_op(instrument_id=3)) == {
        "type": "cancelAll",
        "args": {"iid": 3},
    }
    assert to_command_body_op(
        update_leverage_op(instrument_id=3, leverage=20, cross_margin=True)
    ) == {"type": "updateLeverage", "args": {"cross": True, "iid": 3, "lev": 20}}


def test_auto_cancel_op() -> None:
    assert auto_cancel_op(time_ms=1_767_000_045_000) == ["autoCancel", [1_767_000_045_000]]
    assert to_command_body_op(auto_cancel_op(time_ms=1_767_000_045_000)) == {
        "type": "autoCancel",
        "args": {"time": 1_767_000_045_000},
    }
    assert to_command_body_op(auto_cancel_op(time_ms=0)) == {
        "type": "autoCancel",
        "args": {"time": 0},
    }


def test_invalid_auto_cancel_time_rejected() -> None:
    with pytest.raises(UserInputError, match="time_ms must be an int"):
        auto_cancel_op(time_ms=True)  # type: ignore[arg-type]
    with pytest.raises(UserInputError, match="non-negative"):
        auto_cancel_op(time_ms=-1)


def test_gtc_order_requires_price() -> None:
    with pytest.raises(UserInputError, match="price is required for gtc"):
        PerpsOrderRequest(
            instrument_id=1,
            side="BUY",
            quantity="1",
            time_in_force=cast(Any, "gtc"),
        )


def test_post_only_rejected_for_ioc_and_fok() -> None:
    for tif in ("ioc", "fok"):
        with pytest.raises(UserInputError, match="post_only"):
            PerpsOrderRequest(
                instrument_id=1,
                side="BUY",
                quantity="1",
                time_in_force=tif,  # type: ignore[arg-type]
                post_only=True,
            )


def test_reduce_only_must_be_bool() -> None:
    with pytest.raises(UserInputError, match="reduce_only"):
        PerpsOrderRequest(
            instrument_id=1,
            side="BUY",
            price="1",
            quantity="1",
            reduce_only=cast(Any, "yes"),
            time_in_force="gtc",
        )


def test_invalid_client_order_id_rejected() -> None:
    with pytest.raises(UserInputError, match="client_order_id"):
        PerpsOrderRequest(
            instrument_id=1,
            side="BUY",
            price="1",
            quantity="1",
            time_in_force="gtc",
            client_order_id="not-hex",
        )


def test_invalid_decimal_inputs_rejected() -> None:
    with pytest.raises(UserInputError, match="quantity"):
        PerpsOrderRequest(
            instrument_id=1, side="BUY", price="1", quantity="abc", time_in_force="gtc"
        )
    with pytest.raises(UserInputError, match="side"):
        PerpsOrderRequest(
            instrument_id=1,
            side="LONG",  # type: ignore[arg-type]
            price="1",
            quantity="1",
            time_in_force="gtc",
        )


def test_empty_cancel_batches_rejected() -> None:
    with pytest.raises(UserInputError):
        cancel_orders_op([])
    with pytest.raises(UserInputError):
        cancel_orders_by_client_id_op([])


def test_invalid_cancel_all_instrument_id_rejected() -> None:
    with pytest.raises(UserInputError, match="instrument_id"):
        cancel_all_orders_op(instrument_id=True)  # type: ignore[arg-type]
    with pytest.raises(UserInputError, match="non-negative"):
        cancel_all_orders_op(instrument_id=-1)
