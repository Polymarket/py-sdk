"""Perps trading command construction.

Signed commands are positional tuples (the signed form); the WebSocket frame
body carries an equivalent keyed form. Both are produced here so the session
can sign one and send the other.
"""

from collections.abc import Sequence
from typing import Any

from polymarket.errors import UserInputError
from polymarket.models.perps.requests import (
    DecimalInput,
    PerpsOrderRequest,
    PerpsPositionTpSlTrigger,
    PerpsTpSlTrigger,
    to_decimal_string,
    validate_client_order_id,
)
from polymarket.models.perps.types import PerpsTpSlKind, PerpsTpSlScope

RawPerpsOrder = list[Any]
"""Positional order row: [iid, buy, price?, qty, tif?, post_only, reduce_only?,
client_order_id?, trigger?]. ``None`` holes are compacted before signing."""


def to_raw_order(request: PerpsOrderRequest) -> RawPerpsOrder:
    return [
        request.instrument_id,
        request.side == "BUY",
        None if request.price is None else to_decimal_string("price", request.price),
        to_decimal_string("quantity", request.quantity),
        request.time_in_force,
        request.post_only,
        True if request.reduce_only else None,
        request.client_order_id,
        None,
    ]


def to_raw_tp_sl_order(
    *,
    buy: bool,
    instrument_id: int,
    kind: PerpsTpSlKind,
    quantity: str,
    trigger: PerpsTpSlTrigger | PerpsPositionTpSlTrigger,
) -> RawPerpsOrder:
    limit_price = getattr(trigger, "limit_price", None)
    return [
        instrument_id,
        buy,
        None if limit_price is None else to_decimal_string("limit_price", limit_price),
        quantity,
        None,
        False,
        True,
        None,
        [
            True if limit_price is None else None,
            to_decimal_string("trigger_price", trigger.trigger_price),
            kind,
        ],
    ]


def create_orders_op(
    orders: Sequence[RawPerpsOrder], *, group: PerpsTpSlScope | None = None
) -> list[Any]:
    op: list[Any] = ["createOrders", list(orders)]
    if group is not None:
        op.append(group)
    return op


def cancel_orders_op(order_ids: Sequence[int]) -> list[Any]:
    ids: list[int] = []
    for order_id in order_ids:
        if isinstance(order_id, bool) or not isinstance(order_id, int):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise UserInputError("order_ids must contain ints")
        ids.append(order_id)
    if not ids:
        raise UserInputError("order_ids must be non-empty")
    return ["cancelOrders", ids]


def cancel_orders_by_client_id_op(client_order_ids: Sequence[str]) -> list[Any]:
    ids = [validate_client_order_id(client_order_id) for client_order_id in client_order_ids]
    if not ids:
        raise UserInputError("client_order_ids must be non-empty")
    return ["cancelOrdersCOID", ids]


def cancel_all_orders_op(*, instrument_id: int | None = None) -> list[Any]:
    if instrument_id is None:
        return ["cancelAll", []]
    if isinstance(instrument_id, bool) or not isinstance(instrument_id, int):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("instrument_id must be an int")
    if instrument_id < 0:
        raise UserInputError("instrument_id must be non-negative")
    return ["cancelAll", [instrument_id]]


def update_leverage_op(*, instrument_id: int, leverage: int, cross_margin: bool) -> list[Any]:
    if isinstance(instrument_id, bool) or not isinstance(instrument_id, int):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("instrument_id must be an int")
    if isinstance(leverage, bool) or not isinstance(leverage, int) or leverage <= 0:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("leverage must be a positive int")
    if not isinstance(cross_margin, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("cross_margin must be a bool")
    return ["updateLeverage", [instrument_id, leverage, cross_margin]]


def update_margin_op(*, instrument_id: int, amount: DecimalInput) -> list[Any]:
    if isinstance(instrument_id, bool) or not isinstance(instrument_id, int):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("instrument_id must be an int")
    if instrument_id < 0:
        raise UserInputError("instrument_id must be non-negative")
    return ["updateMargin", [instrument_id, to_decimal_string("amount", amount)]]


def to_command_body_op(op: Sequence[Any]) -> dict[str, Any]:
    """Convert a signed positional op into the keyed frame body op."""
    op_type = op[0]
    if op_type == "createOrders":
        body: dict[str, Any] = {
            "type": op_type,
            "args": [_to_order_body(row) for row in op[1]],
        }
        if len(op) > 2:
            body["grp"] = op[2]
        return body
    if op_type in ("cancelOrders", "cancelOrdersCOID"):
        return {"type": op_type, "args": op[1]}
    if op_type == "cancelAll":
        args = op[1]
        instrument_id = args[0] if args else None
        return {
            "type": op_type,
            "args": {} if instrument_id is None else {"iid": instrument_id},
        }
    if op_type == "updateLeverage":
        instrument_id, leverage, cross_margin = op[1]
        return {
            "type": op_type,
            "args": {"cross": cross_margin, "iid": instrument_id, "lev": leverage},
        }
    if op_type == "updateMargin":
        instrument_id, amount = op[1]
        return {"type": op_type, "args": {"amt": amount, "iid": instrument_id}}
    raise RuntimeError(f"Unsupported Perps command: {op_type!r}")


def _to_order_body(row: RawPerpsOrder) -> dict[str, Any]:
    body: dict[str, Any] = {"iid": row[0], "buy": row[1], "po": row[5], "qty": row[3]}
    if row[4] is not None:
        body["tif"] = row[4]
    if row[6]:
        body["ro"] = row[6]
    if row[2] is not None:
        body["p"] = row[2]
    if row[7] is not None:
        body["c"] = row[7]
    if row[8] is not None:
        body["tr"] = _to_trigger_body(row[8])
    return body


def _to_trigger_body(trigger: list[Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"tpsl": trigger[2], "trp": trigger[1]}
    if trigger[0] is not None:
        body["market"] = trigger[0]
    return body


__all__ = [
    "RawPerpsOrder",
    "cancel_all_orders_op",
    "cancel_orders_by_client_id_op",
    "cancel_orders_op",
    "create_orders_op",
    "to_command_body_op",
    "to_raw_order",
    "to_raw_tp_sl_order",
    "update_leverage_op",
    "update_margin_op",
]
