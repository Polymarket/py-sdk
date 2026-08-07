"""Perps trading workflows and command construction.

Signed commands are positional tuples (the signed form); the WebSocket frame
body carries an equivalent keyed form. Both are produced here so the session
can sign one and send the other.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from polymarket.errors import RequestRejectedError, UserInputError
from polymarket.models.perps.events import PerpsOrderEvent, PerpsSessionEvent
from polymarket.models.perps.orders import PerpsOrder, PerpsPostOrderAck
from polymarket.models.perps.requests import (
    DecimalInput,
    PerpsOrderRequest,
    PerpsPositionTpSlTrigger,
    PerpsTpSlTrigger,
    to_decimal_string,
    validate_client_order_id,
)
from polymarket.models.perps.results import (
    PerpsOrderPlacement,
    PerpsPlacedTpSlOrder,
    PerpsPlacedTpSlOrders,
)
from polymarket.models.perps.types import PerpsOrderId, PerpsTpSlKind, PerpsTpSlScope

if TYPE_CHECKING:
    from polymarket._internal.perps_session import PerpsSession

# Purposefully generous: backend order updates are expected in the ~100ms range.
_ORDER_PLACEMENT_UPDATE_TIMEOUT_S = 2.0

RawPerpsOrder = list[Any]
"""Positional order row: [iid, buy, price?, qty, tif?, post_only, reduce_only?,
client_order_id?, trigger?]. ``None`` holes are compacted before signing."""


async def place_order(
    session: PerpsSession,
    request: PerpsOrderRequest,
    *,
    take_profit: PerpsTpSlTrigger | None,
    stop_loss: PerpsTpSlTrigger | None,
    expires_at: datetime | int | None,
) -> PerpsOrderPlacement:
    if request.client_order_id is None:
        request = replace(request, client_order_id=secrets.token_hex(16))
    client_order_id = request.client_order_id
    assert client_order_id is not None

    if take_profit is None and stop_loss is None:
        _, order = await _place_orders_and_wait_for_update(
            session,
            [to_raw_order(request)],
            client_order_id=client_order_id,
            group=None,
            expires_at=expires_at,
        )
        return PerpsOrderPlacement(order=order)

    rows: list[RawPerpsOrder] = [to_raw_order(request)]
    exit_buy = request.side == "SELL"
    quantity_string = to_decimal_string("quantity", request.quantity)
    if take_profit is not None:
        rows.append(
            to_raw_tp_sl_order(
                buy=exit_buy,
                instrument_id=request.instrument_id,
                kind="tp",
                quantity=quantity_string,
                trigger=take_profit,
            )
        )
    if stop_loss is not None:
        rows.append(
            to_raw_tp_sl_order(
                buy=exit_buy,
                instrument_id=request.instrument_id,
                kind="sl",
                quantity=quantity_string,
                trigger=stop_loss,
            )
        )
    placed, order = await _place_orders_and_wait_for_update(
        session,
        rows,
        client_order_id=client_order_id,
        group="order",
        expires_at=expires_at,
    )
    trigger_index = 1
    take_profit_order = None
    stop_loss_order = None
    if take_profit is not None:
        take_profit_order = PerpsPlacedTpSlOrder(order_id=placed[trigger_index])
        trigger_index += 1
    if stop_loss is not None:
        stop_loss_order = PerpsPlacedTpSlOrder(order_id=placed[trigger_index])
    return PerpsOrderPlacement(
        order=order,
        tp_sl=PerpsPlacedTpSlOrders(
            take_profit=take_profit_order,
            stop_loss=stop_loss_order,
        ),
    )


async def post_orders(
    session: PerpsSession,
    orders: Sequence[PerpsOrderRequest],
    *,
    expires_at: datetime | int | None,
) -> tuple[PerpsPostOrderAck, ...]:
    if not orders:
        raise UserInputError("orders must be non-empty")
    acks = await session._send_create_orders(  # pyright: ignore[reportPrivateUsage]
        [to_raw_order(order) for order in orders],
        group=None,
        expires_at=expires_at,
    )
    return tuple(acks)


async def place_position_tp_sl(
    session: PerpsSession,
    *,
    instrument_id: int,
    take_profit: PerpsPositionTpSlTrigger | None,
    stop_loss: PerpsPositionTpSlTrigger | None,
    expires_at: datetime | int | None,
) -> PerpsPlacedTpSlOrders:
    if take_profit is None and stop_loss is None:
        raise UserInputError("Provide take_profit, stop_loss, or both")
    exit_buy = await _position_exit_buy(session, instrument_id)
    rows: list[RawPerpsOrder] = []
    if take_profit is not None:
        rows.append(
            to_raw_tp_sl_order(
                buy=exit_buy,
                instrument_id=instrument_id,
                kind="tp",
                quantity="0",
                trigger=take_profit,
            )
        )
    if stop_loss is not None:
        rows.append(
            to_raw_tp_sl_order(
                buy=exit_buy,
                instrument_id=instrument_id,
                kind="sl",
                quantity="0",
                trigger=stop_loss,
            )
        )
    acks = await session._send_create_orders(  # pyright: ignore[reportPrivateUsage]
        rows,
        group="position",
        expires_at=expires_at,
    )
    placed = [_expect_ok_ack(ack) for ack in acks]
    trigger_index = 0
    take_profit_order = None
    stop_loss_order = None
    if take_profit is not None:
        take_profit_order = PerpsPlacedTpSlOrder(order_id=placed[trigger_index])
        trigger_index += 1
    if stop_loss is not None:
        stop_loss_order = PerpsPlacedTpSlOrder(order_id=placed[trigger_index])
    return PerpsPlacedTpSlOrders(
        take_profit=take_profit_order,
        stop_loss=stop_loss_order,
    )


async def _place_orders_and_wait_for_update(
    session: PerpsSession,
    rows: list[RawPerpsOrder],
    *,
    client_order_id: str,
    group: PerpsTpSlScope | None,
    expires_at: datetime | int | None,
) -> tuple[list[PerpsOrderId], PerpsOrder]:
    def matches(event: PerpsSessionEvent) -> bool:
        return (
            isinstance(event, PerpsOrderEvent) and event.payload.client_order_id == client_order_id
        )

    waiter = session._create_event_waiter(matches)  # pyright: ignore[reportPrivateUsage]
    try:
        acks = await session._send_create_orders(  # pyright: ignore[reportPrivateUsage]
            rows,
            group=group,
            expires_at=expires_at,
        )
        placed = [_expect_ok_ack(ack) for ack in acks]
        event = await session._wait_for_event(  # pyright: ignore[reportPrivateUsage]
            waiter,
            timeout_s=_ORDER_PLACEMENT_UPDATE_TIMEOUT_S,
        )
        assert isinstance(event, PerpsOrderEvent)
        return placed, event.payload
    finally:
        session._remove_event_waiter(waiter)  # pyright: ignore[reportPrivateUsage]


async def _position_exit_buy(session: PerpsSession, instrument_id: int) -> bool:
    portfolio = await session.fetch_portfolio()
    position = next(
        (item for item in portfolio.positions if item.instrument_id == instrument_id),
        None,
    )
    if position is None or position.size == 0:
        raise UserInputError(f"No open Perps position for instrument {instrument_id}.")
    return position.size < 0


def _expect_ok_ack(ack: PerpsPostOrderAck) -> PerpsOrderId:
    if ack.status == "err":
        raise RequestRejectedError(ack.error or "Perps command was rejected.", status=200)
    return cast(PerpsOrderId, ack.order_id)


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


def auto_cancel_op(*, time_ms: int) -> list[Any]:
    """Build the auto-cancel op: ``time_ms`` arms the switch, ``0`` clears it."""
    if isinstance(time_ms, bool) or not isinstance(time_ms, int):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("time_ms must be an int")
    if time_ms < 0:
        raise UserInputError("time_ms must be non-negative")
    return ["autoCancel", [time_ms]]


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
    if op_type == "autoCancel":
        (time_ms,) = op[1]
        return {"type": op_type, "args": {"time": time_ms}}
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
    "auto_cancel_op",
    "cancel_all_orders_op",
    "cancel_orders_by_client_id_op",
    "cancel_orders_op",
    "create_orders_op",
    "place_order",
    "place_position_tp_sl",
    "post_orders",
    "to_command_body_op",
    "to_raw_order",
    "to_raw_tp_sl_order",
    "update_leverage_op",
    "update_margin_op",
]
