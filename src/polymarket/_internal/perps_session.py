"""Authenticated Perps trading session over WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any, Literal, Self, cast, overload

from polymarket._internal.actions.perps import account as _account
from polymarket._internal.actions.perps.paging import to_epoch_ms
from polymarket._internal.actions.perps.signing import (
    now_ms,
    random_perps_salt,
    sign_perps_op_with_key,
)
from polymarket._internal.actions.perps.trading import (
    RawPerpsOrder,
    cancel_all_orders_op,
    cancel_orders_by_client_id_op,
    cancel_orders_op,
    create_orders_op,
    to_command_body_op,
    to_raw_order,
    to_raw_tp_sl_order,
    update_leverage_op,
)
from polymarket._internal.streams.perps.heartbeat import PerpsWebSocketHeartbeat
from polymarket._internal.streams.reconnect import ReconnectScheduler
from polymarket._internal.ws.connection import AsyncWebSocketConnection
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import (
    RequestRejectedError,
    TransportError,
    UserInputError,
)
from polymarket.errors import (
    TimeoutError as SDKTimeoutError,
)
from polymarket.models.perps.account import (
    PerpsAccountConfig,
    PerpsAccountStats,
    PerpsBalance,
    PerpsEquityPoint,
    PerpsFundingPayment,
    PerpsPnlPoint,
    PerpsPortfolio,
)
from polymarket.models.perps.credentials import PerpsCredentials
from polymarket.models.perps.events import (
    PerpsOrderEvent,
    PerpsResyncEvent,
    PerpsSessionEvent,
    parse_perps_session_event,
)
from polymarket.models.perps.funds import PerpsDeposit, PerpsWithdrawal
from polymarket.models.perps.notifications import (
    PerpsNotificationEntry,
    PerpsNotificationsPaginator,
)
from polymarket.models.perps.orders import (
    PerpsCancelAllOrdersResponse,
    PerpsCancelOrderResult,
    PerpsFill,
    PerpsOrder,
    PerpsPostOrderAck,
    PerpsUpdateLeverageResult,
)
from polymarket.models.perps.requests import (
    DecimalInput,
    PerpsOrderRequest,
    PerpsPositionTpSlTrigger,
    PerpsTpSlTrigger,
    to_decimal_string,
)
from polymarket.models.perps.results import (
    PerpsOrderPlacement,
    PerpsPlacedTpSlOrder,
    PerpsPlacedTpSlOrders,
)
from polymarket.models.perps.types import (
    PerpsDepositStatus,
    PerpsOrderId,
    PerpsPnlInterval,
    PerpsSortDirection,
    PerpsTimeInForce,
    PerpsWithdrawalStatus,
)
from polymarket.models.types import OrderSide
from polymarket.pagination import AsyncPaginator

_AUTH_TIMEOUT_S = 30.0
_ACK_TIMEOUT_S = 30.0
# Purposefully generous: backend order updates are expected in the ~100ms range.
_ORDER_PLACEMENT_UPDATE_TIMEOUT_S = 2.0
_QUEUE_SIZE = 1024

_SESSION_CHANNELS = (
    "balances",
    "portfolio",
    "orders",
    "fills",
    "funding",
    "deposits",
    "withdrawals",
    "notifications",
    "tpsl",
)

_SERVER_RESYNC_CHANNELS = frozenset({"notifications"})


class _EndSentinel:
    __slots__ = ()


_END = _EndSentinel()


@dataclass(slots=True)
class _PendingRequest:
    future: asyncio.Future[Any]
    parse: Callable[[object], Any]


@dataclass(slots=True)
class _EventWaiter:
    future: asyncio.Future[PerpsSessionEvent]
    predicate: Callable[[PerpsSessionEvent], bool]


class PerpsSession:
    """Experimental: This API may change in a breaking way in any release,
    including patch releases.

    An authenticated Perps account session.

    The session multiplexes trading commands, private account updates, and
    account reads over one connection. Iterate over the session to receive
    :class:`~polymarket.models.perps.PerpsSessionEvent` updates.
    """

    def __init__(
        self,
        *,
        chain_id: int,
        credentials: PerpsCredentials,
        rest_url: str,
        ws_url: str,
        logger: logging.Logger | None = None,
        on_close: Callable[[PerpsSession], None] | None = None,
    ) -> None:
        self._chain_id = chain_id
        self._credentials = credentials
        self._ws_url = ws_url
        self._logger = logger or logging.getLogger("polymarket.perps.session")
        self._on_session_close = on_close
        self._api = AsyncTransport(
            base_url=rest_url,
            logger=logger,
            header_resolver=self._resolve_auth_headers,
        )
        self._connection = AsyncWebSocketConnection(
            heartbeat=PerpsWebSocketHeartbeat(), logger=self._logger
        )
        self._scheduler = ReconnectScheduler(logger=self._logger)
        self._send_lock = asyncio.Lock()
        self._queue: asyncio.Queue[PerpsSessionEvent | _EndSentinel] = asyncio.Queue(
            maxsize=_QUEUE_SIZE
        )
        self._pending: dict[int, _PendingRequest] = {}
        self._event_waiters: list[_EventWaiter] = []
        # Order updates can arrive before the post acknowledgement resumes the
        # caller; keep a bounded buffer so place_order never misses its update.
        self._recent_orders: dict[PerpsOrderId, PerpsOrder] = {}
        self._sequences: dict[str, int] = {}
        self._next_request_id = 1
        self._closed = False
        self._ended = False
        self._end_error: BaseException | None = None
        self._dropped_events = 0

    @property
    def credentials(self) -> PerpsCredentials:
        """Delegated credentials backing this session."""
        return self._credentials

    @property
    def closed(self) -> bool:
        """Whether the session has been closed."""
        return self._closed

    @property
    def dropped_events(self) -> int:
        """Number of events dropped because the consumer fell behind."""
        return self._dropped_events

    async def open(self) -> Self:
        """Connect and authenticate the session WebSocket."""
        await self._connect(emit_resync=False)
        return self

    async def close(self) -> None:
        """Close the session and release its connection."""
        if self._closed:
            return
        self._closed = True
        await self._scheduler.aclose()
        self._reject_pending(TransportError("Perps session closed."))
        self._reject_event_waiters(TransportError("Perps session closed."))
        self._end()
        await self._connection.close()
        await self._api.close()
        if self._on_session_close is not None:
            self._on_session_close(self)

    def __aiter__(self) -> Self:
        """Iterate authenticated Perps account events emitted by this session."""
        return self

    async def __anext__(self) -> PerpsSessionEvent:
        item = await self._queue.get()
        if isinstance(item, _EndSentinel):
            if self._end_error is not None:
                raise self._end_error
            raise StopAsyncIteration
        return item

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    @overload
    async def place_order(
        self,
        *,
        instrument_id: int,
        side: OrderSide,
        quantity: DecimalInput,
        time_in_force: Literal["gtc"],
        price: DecimalInput,
        post_only: bool = False,
        reduce_only: bool = False,
        client_order_id: str | None = None,
        take_profit: PerpsTpSlTrigger | None = None,
        stop_loss: PerpsTpSlTrigger | None = None,
        expires_at: datetime | int | None = None,
    ) -> PerpsOrderPlacement: ...
    @overload
    async def place_order(
        self,
        *,
        instrument_id: int,
        side: OrderSide,
        quantity: DecimalInput,
        time_in_force: Literal["ioc", "fok"],
        price: DecimalInput | None = None,
        reduce_only: bool = False,
        client_order_id: str | None = None,
        take_profit: PerpsTpSlTrigger | None = None,
        stop_loss: PerpsTpSlTrigger | None = None,
        expires_at: datetime | int | None = None,
    ) -> PerpsOrderPlacement: ...
    async def place_order(
        self,
        *,
        instrument_id: int,
        side: OrderSide,
        quantity: DecimalInput,
        time_in_force: PerpsTimeInForce,
        price: DecimalInput | None = None,
        post_only: bool = False,
        reduce_only: bool = False,
        client_order_id: str | None = None,
        take_profit: PerpsTpSlTrigger | None = None,
        stop_loss: PerpsTpSlTrigger | None = None,
        expires_at: datetime | int | None = None,
    ) -> PerpsOrderPlacement:
        """Place one order and resolve with its first orders update.

        ``gtc`` orders require ``price`` and may set ``post_only``; ``ioc`` and
        ``fok`` orders may omit ``price`` for market-style execution. Set
        ``reduce_only`` to prevent the order from increasing exposure. Pass
        ``take_profit`` and/or ``stop_loss`` to place reduce-only trigger orders
        together with the entry order. ``expires_at`` is an optional command
        expiration timestamp, accepted as ``datetime`` or epoch milliseconds.
        """
        if time_in_force == "gtc":
            request = PerpsOrderRequest(
                instrument_id=instrument_id,
                side=side,
                quantity=quantity,
                time_in_force=time_in_force,
                price=cast(DecimalInput, price),
                post_only=post_only,
                reduce_only=reduce_only,
                client_order_id=client_order_id,
            )
        else:
            if post_only:
                raise UserInputError("post_only is only supported for gtc orders")
            request = PerpsOrderRequest(
                instrument_id=instrument_id,
                side=side,
                quantity=quantity,
                time_in_force=time_in_force,
                price=price,
                reduce_only=reduce_only,
                client_order_id=client_order_id,
            )
        if take_profit is None and stop_loss is None:
            acks = await self._send_create_orders(
                [to_raw_order(request)], group=None, expires_at=expires_at
            )
            entry = self._expect_ok_ack(acks[0])
            order = await self._wait_for_order_update(entry)
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
        acks = await self._send_create_orders(rows, group="order", expires_at=expires_at)
        placed = [self._expect_ok_ack(ack) for ack in acks]
        order = await self._wait_for_order_update(placed[0])
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
            tp_sl=PerpsPlacedTpSlOrders(take_profit=take_profit_order, stop_loss=stop_loss_order),
        )

    async def post_orders(
        self,
        orders: Sequence[PerpsOrderRequest],
        *,
        expires_at: datetime | int | None = None,
    ) -> tuple[PerpsPostOrderAck, ...]:
        """Post one or more orders and return queue-entry acknowledgements.

        This is a low-level method; :meth:`place_order` is the common path when
        callers want to wait for the resulting order update.
        """
        if not orders:
            raise UserInputError("orders must be non-empty")
        acks = await self._send_create_orders(
            [to_raw_order(order) for order in orders], group=None, expires_at=expires_at
        )
        return tuple(acks)

    async def place_position_tp_sl(
        self,
        *,
        instrument_id: int,
        take_profit: PerpsPositionTpSlTrigger | None = None,
        stop_loss: PerpsPositionTpSlTrigger | None = None,
        expires_at: datetime | int | None = None,
    ) -> PerpsPlacedTpSlOrders:
        """Protect the current position with take-profit/stop-loss triggers.

        The exit side is inferred from the open position; a flat position
        raises :class:`~polymarket.errors.UserInputError`. Provide
        ``take_profit``, ``stop_loss``, or both.
        """
        if take_profit is None and stop_loss is None:
            raise UserInputError("Provide take_profit, stop_loss, or both")
        exit_buy = await self._position_exit_buy(instrument_id)
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
        acks = await self._send_create_orders(rows, group="position", expires_at=expires_at)
        placed = [self._expect_ok_ack(ack) for ack in acks]
        trigger_index = 0
        take_profit_order = None
        stop_loss_order = None
        if take_profit is not None:
            take_profit_order = PerpsPlacedTpSlOrder(order_id=placed[trigger_index])
            trigger_index += 1
        if stop_loss is not None:
            stop_loss_order = PerpsPlacedTpSlOrder(order_id=placed[trigger_index])
        return PerpsPlacedTpSlOrders(take_profit=take_profit_order, stop_loss=stop_loss_order)

    @overload
    async def cancel_order(
        self,
        *,
        order_id: int,
        client_order_id: None = None,
        expires_at: datetime | int | None = None,
    ) -> PerpsCancelOrderResult: ...
    @overload
    async def cancel_order(
        self,
        *,
        client_order_id: str,
        order_id: None = None,
        expires_at: datetime | int | None = None,
    ) -> PerpsCancelOrderResult: ...
    async def cancel_order(
        self,
        *,
        order_id: int | None = None,
        client_order_id: str | None = None,
        expires_at: datetime | int | None = None,
    ) -> PerpsCancelOrderResult:
        """Cancel one order by ``order_id`` or ``client_order_id``.

        Provide exactly one identifier. The returned status reflects whether
        the cancel happened.
        """
        if (order_id is None) == (client_order_id is None):
            raise UserInputError("Provide exactly one of order_id or client_order_id")
        if order_id is not None:
            results = await self.cancel_orders(order_ids=[order_id], expires_at=expires_at)
        else:
            assert client_order_id is not None
            results = await self.cancel_orders(
                client_order_ids=[client_order_id], expires_at=expires_at
            )
        return results[0]

    @overload
    async def cancel_orders(
        self,
        *,
        order_ids: Sequence[int],
        client_order_ids: None = None,
        expires_at: datetime | int | None = None,
    ) -> tuple[PerpsCancelOrderResult, ...]: ...
    @overload
    async def cancel_orders(
        self,
        *,
        client_order_ids: Sequence[str],
        order_ids: None = None,
        expires_at: datetime | int | None = None,
    ) -> tuple[PerpsCancelOrderResult, ...]: ...
    async def cancel_orders(
        self,
        *,
        order_ids: Sequence[int] | None = None,
        client_order_ids: Sequence[str] | None = None,
        expires_at: datetime | int | None = None,
    ) -> tuple[PerpsCancelOrderResult, ...]:
        """Cancel orders and return one result per requested order.

        Provide exactly one identifier list: ``order_ids`` or
        ``client_order_ids``.
        """
        if (order_ids is None) == (client_order_ids is None):
            raise UserInputError("Provide exactly one of order_ids or client_order_ids")
        if order_ids is not None:
            op = cancel_orders_op(order_ids)
        else:
            assert client_order_ids is not None
            op = cancel_orders_by_client_id_op(client_order_ids)
        results = await self._send_signed_command(
            op,
            parse=_parse_cancel_results,
            timeout_message="Perps cancel order response timed out.",
            expires_at=expires_at,
        )
        return tuple(results)

    async def cancel_all_orders(
        self,
        *,
        instrument_id: int | None = None,
        expires_at: datetime | int | None = None,
    ) -> None:
        """Cancel all open Perps orders for the session account.

        Omit ``instrument_id`` to cancel open orders across all instruments.
        The request returns once accepted; individual orders can still race with
        fills or other cancels.
        """
        op = cancel_all_orders_op(instrument_id=instrument_id)
        response = await self._api.delete_json(
            "/v1/trade/orders/all",
            json={
                **self._create_signed_command(op, expires_at=expires_at),
                "op": to_command_body_op(op),
            },
        )
        PerpsCancelAllOrdersResponse.parse_response(response)

    async def update_leverage(
        self, *, instrument_id: int, leverage: int, cross_margin: bool
    ) -> PerpsUpdateLeverageResult:
        """Update leverage and margin mode for an instrument."""
        op = update_leverage_op(
            instrument_id=instrument_id, leverage=leverage, cross_margin=cross_margin
        )
        return await self._send_signed_command(
            op,
            parse=PerpsUpdateLeverageResult.parse_response,
            timeout_message="Perps update leverage response timed out.",
        )

    async def fetch_balances(self) -> tuple[PerpsBalance, ...]:
        """Fetch current Perps balances for the session account."""
        return await _account.fetch_balances(self._api)

    async def fetch_portfolio(self) -> PerpsPortfolio:
        """Fetch the current Perps portfolio for the session account."""
        return await _account.fetch_portfolio(self._api)

    async def fetch_stats(self) -> PerpsAccountStats:
        """Fetch account-level Perps statistics for the session account."""
        return await _account.fetch_stats(self._api)

    async def fetch_account_config(
        self, *, instrument_id: int | None = None
    ) -> tuple[PerpsAccountConfig, ...]:
        """Fetch Perps account configuration, optionally filtered by instrument."""
        return await _account.fetch_account_config(self._api, instrument_id=instrument_id)

    async def fetch_open_orders(
        self, *, instrument_id: int | None = None
    ) -> tuple[PerpsOrder, ...]:
        """Fetch currently open Perps orders, optionally filtered by instrument."""
        return await _account.fetch_open_orders(self._api, instrument_id=instrument_id)

    async def fetch_orders(
        self,
        *,
        order_id: int | None = None,
        client_order_id: str | None = None,
        instrument_id: int | None = None,
        start: datetime | int | None = None,
        end: datetime | int | None = None,
    ) -> tuple[PerpsOrder, ...]:
        """Fetch Perps orders for the session account."""
        return await _account.fetch_orders(
            self._api,
            order_id=order_id,
            client_order_id=client_order_id,
            instrument_id=instrument_id,
            start=start,
            end=end,
        )

    def list_fills(
        self,
        *,
        start: datetime | int | None = None,
        end: datetime | int | None = None,
        sort: PerpsSortDirection | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[PerpsFill]:
        """List Perps fills for the session account.

        Fills are returned newest first by default; pass ``sort="asc"`` for
        oldest first. ``cursor`` resumes from an opaque page cursor returned
        by a previous page.
        """
        return _account.list_fills(self._api, start=start, end=end, sort=sort, cursor=cursor)

    def list_funding_payments(
        self,
        *,
        instrument_id: int | None = None,
        start: datetime | int | None = None,
        end: datetime | int | None = None,
    ) -> AsyncPaginator[PerpsFundingPayment]:
        """List Perps funding payments for the session account.

        Defaults to the past 24 hours when ``start`` is omitted.
        """
        return _account.list_funding_payments(
            self._api, instrument_id=instrument_id, start=start, end=end
        )

    def list_deposits(
        self,
        *,
        deposit_status: PerpsDepositStatus | None = None,
        hash: str | None = None,
        start: datetime | int | None = None,
        end: datetime | int | None = None,
    ) -> AsyncPaginator[PerpsDeposit]:
        """List Perps deposits for the session account.

        Defaults to the past 90 days when ``start`` is omitted.
        """
        return _account.list_deposits(
            self._api, deposit_status=deposit_status, hash=hash, start=start, end=end
        )

    def list_withdrawals(
        self,
        *,
        withdrawal_status: PerpsWithdrawalStatus | None = None,
        hash: str | None = None,
        start: datetime | int | None = None,
        end: datetime | int | None = None,
    ) -> AsyncPaginator[PerpsWithdrawal]:
        """List Perps withdrawals for the session account.

        Defaults to the past 90 days when ``start`` is omitted.
        """
        return _account.list_withdrawals(
            self._api,
            withdrawal_status=withdrawal_status,
            hash=hash,
            start=start,
            end=end,
        )

    def list_notifications(
        self,
        *,
        since_seq: int | None = None,
        limit: int | None = None,
    ) -> PerpsNotificationsPaginator:
        """List notifications for the session account, newest first.

        Each page also reports the account's ``unread`` count and the
        ``durable_source_seq`` high-water mark. After a ``resync`` session
        event or a reconnect, pass ``since_seq`` to backfill missed
        notifications: anchor it at the sequence of the last notification
        event processed before the gap and retry until ``durable_source_seq``
        reaches the catch-up target, deduplicating merged results by
        notification id. Follow-up pages keep the same ``since_seq`` bound
        automatically.
        """
        return _account.list_notifications(self._api, since_seq=since_seq, limit=limit)

    async def mark_notifications_read(
        self,
        *,
        ids: Sequence[str] | None = None,
        up_to: PerpsNotificationEntry | None = None,
    ) -> None:
        """Mark notifications read, by ids or up to a notification entry.

        Provide exactly one of ``ids`` or ``up_to``. ``up_to`` marks that
        entry and every earlier notification read, inclusive. Read state is
        account-scoped: only the session account's notifications can be
        marked read.
        """
        await _account.mark_notifications_read(self._api, ids=ids, up_to=up_to)

    def list_equity_history(
        self,
        *,
        interval: PerpsPnlInterval,
        start: datetime | int,
        end: datetime | int | None = None,
    ) -> AsyncPaginator[PerpsEquityPoint]:
        """List Perps equity history at the requested interval."""
        return _account.list_equity_history(self._api, interval=interval, start=start, end=end)

    def list_pnl_history(
        self,
        *,
        interval: PerpsPnlInterval,
        start: datetime | int,
        end: datetime | int | None = None,
    ) -> AsyncPaginator[PerpsPnlPoint]:
        """List Perps profit-and-loss history at the requested interval."""
        return _account.list_pnl_history(self._api, interval=interval, start=start, end=end)

    async def _resolve_auth_headers(
        self, method: str, path: str, body: str | None
    ) -> Mapping[str, str]:
        return {
            "POLYMARKET-PROXY": self._credentials.proxy,
            "POLYMARKET-SECRET": self._credentials.secret,
        }

    async def _connect(self, *, emit_resync: bool) -> None:
        await self._connection.connect(
            url=self._ws_url,
            on_message=self._on_message,
            on_connection_lost=self._on_socket_connection_lost,
            on_error=self._on_socket_error,
        )
        await self._authenticate()
        await self._subscribe_channels()
        self._scheduler.reset()
        if emit_resync:
            self._sequences.clear()
            self._push(PerpsResyncEvent(reason="reconnect"))

    async def _authenticate(self) -> None:
        await self._send_request(
            {
                "id": self._take_request_id(),
                "req": "post",
                "op": {
                    "type": "auth",
                    "args": {
                        "proxy": self._credentials.proxy,
                        "secret": self._credentials.secret,
                    },
                },
            },
            parse=_parse_session_ack,
            timeout_s=_AUTH_TIMEOUT_S,
            timeout_message="Perps session authentication timed out.",
        )

    async def _subscribe_channels(self) -> None:
        await self._send_request(
            {
                "id": self._take_request_id(),
                "req": "sub",
                "chs": list(_SESSION_CHANNELS),
            },
            parse=_parse_session_ack,
            timeout_s=_ACK_TIMEOUT_S,
            timeout_message="Perps session subscription timed out.",
        )

    async def _send_create_orders(
        self,
        rows: list[RawPerpsOrder],
        *,
        group: Literal["order", "position"] | None,
        expires_at: datetime | int | None,
    ) -> list[PerpsPostOrderAck]:
        op = create_orders_op(rows, group=group)
        acks = await self._send_signed_command(
            op,
            parse=_parse_post_order_acks,
            timeout_message="Perps post order acknowledgement timed out.",
            expires_at=expires_at,
        )
        if not acks:
            raise TransportError("Perps session unexpected response.")
        return acks

    async def _send_signed_command(
        self,
        op: list[Any],
        *,
        parse: Callable[[object], Any],
        timeout_message: str,
        expires_at: datetime | int | None = None,
    ) -> Any:
        command = self._create_signed_command(op, expires_at=expires_at)
        frame: dict[str, Any] = {
            "id": self._take_request_id(),
            "req": "post",
            "op": to_command_body_op(op),
            **command,
        }
        return await self._send_request(
            frame, parse=parse, timeout_s=_ACK_TIMEOUT_S, timeout_message=timeout_message
        )

    def _create_signed_command(
        self, op: list[Any], *, expires_at: datetime | int | None = None
    ) -> dict[str, Any]:
        salt = random_perps_salt()
        timestamp = now_ms()
        signature = sign_perps_op_with_key(
            self._credentials.private_key,
            chain_id=self._chain_id,
            op=op,
            salt=salt,
            timestamp_ms=timestamp,
        )
        command: dict[str, Any] = {"salt": salt, "sig": signature, "ts": timestamp}
        expiry_ms = to_epoch_ms("expires_at", expires_at)
        if expiry_ms is not None:
            command["exp"] = expiry_ms
        return command

    async def _send_request(
        self,
        frame: dict[str, Any],
        *,
        parse: Callable[[object], Any],
        timeout_s: float,
        timeout_message: str,
    ) -> Any:
        if self._closed:
            raise TransportError("Perps session closed.")
        request_id = frame["id"]
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = _PendingRequest(future=future, parse=parse)
        try:
            async with self._send_lock:
                sent = await self._connection.send(frame)
            if not sent:
                raise TransportError("Perps session transport is not open.")
            return await asyncio.wait_for(future, timeout=timeout_s)
        except TimeoutError as error:
            raise TransportError(timeout_message) from error
        finally:
            self._pending.pop(request_id, None)

    def _take_request_id(self) -> int:
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id

    def _expect_ok_ack(self, ack: PerpsPostOrderAck) -> PerpsOrderId:
        if ack.status == "err":
            raise RequestRejectedError(ack.error or "Perps command was rejected.", status=200)
        return cast(PerpsOrderId, ack.order_id)

    async def _wait_for_order_update(self, order_id: PerpsOrderId) -> PerpsOrder:
        buffered = self._recent_orders.get(order_id)
        if buffered is not None:
            return buffered

        def matches(event: PerpsSessionEvent) -> bool:
            return isinstance(event, PerpsOrderEvent) and event.payload.id == order_id

        event = await self._wait_for_event(matches, timeout_s=_ORDER_PLACEMENT_UPDATE_TIMEOUT_S)
        assert isinstance(event, PerpsOrderEvent)
        return event.payload

    async def _wait_for_event(
        self,
        predicate: Callable[[PerpsSessionEvent], bool],
        *,
        timeout_s: float,
    ) -> PerpsSessionEvent:
        future: asyncio.Future[PerpsSessionEvent] = asyncio.get_running_loop().create_future()
        waiter = _EventWaiter(future=future, predicate=predicate)
        self._event_waiters.append(waiter)
        try:
            return await asyncio.wait_for(future, timeout=timeout_s)
        except TimeoutError as error:
            raise SDKTimeoutError("Perps event wait timed out.") from error
        finally:
            with contextlib.suppress(ValueError):
                self._event_waiters.remove(waiter)

    async def _position_exit_buy(self, instrument_id: int) -> bool:
        portfolio = await self.fetch_portfolio()
        position = next(
            (item for item in portfolio.positions if item.instrument_id == instrument_id),
            None,
        )
        if position is None or position.size == 0:
            raise UserInputError(f"No open Perps position for instrument {instrument_id}.")
        return position.size < 0

    def _on_message(self, raw: object) -> None:
        if isinstance(raw, list):
            for item in cast("list[object]", raw):
                self._on_message(item)
            return
        if self._handle_response(raw):
            return
        try:
            event = parse_perps_session_event(raw)
        except Exception:
            self._logger.debug("dropped malformed perps session event", exc_info=True)
            return
        if event is None:
            return
        self._push_sequence_gap_if_needed(event)
        self._emit_event(event)

    def _handle_response(self, raw: object) -> bool:
        if not isinstance(raw, dict):
            return False
        message = cast("dict[str, Any]", raw)
        request_id = message.get("id")
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            return False
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return True
        data = message.get("data")
        try:
            result = pending.parse(data)
        except RequestRejectedError as error:
            self._reject_future(pending.future, error)
            return True
        except Exception:
            error_ack = _error_ack(data if data is not None else message)
            if error_ack is not None:
                self._reject_future(pending.future, RequestRejectedError(error_ack, status=200))
            else:
                self._reject_future(
                    pending.future, TransportError("Perps session unexpected response.")
                )
            return True
        if not pending.future.done():
            pending.future.set_result(result)
        return True

    def _reject_future(self, future: asyncio.Future[Any], error: BaseException) -> None:
        if not future.done():
            future.set_exception(error)

    def _on_socket_connection_lost(self, code: int, reason: str) -> None:
        self._reject_pending(TransportError("Perps session connection closed."))
        self._reject_event_waiters(TransportError("Perps session connection closed."))
        if self._closed:
            return
        self._scheduler.schedule(
            reconnect=self._reconnect,
            should_reconnect=lambda: not self._closed,
        )

    def _on_socket_error(self, exc: BaseException) -> None:
        self._logger.warning("perps session reader error: %r", exc)

    async def _reconnect(self) -> None:
        if self._closed:
            return
        try:
            await self._connect(emit_resync=True)
        except (TransportError, RequestRejectedError) as exc:
            self._logger.info("perps session reconnect failed: %r; rescheduling", exc)
            if not self._closed:
                self._scheduler.schedule(
                    reconnect=self._reconnect,
                    should_reconnect=lambda: not self._closed,
                )

    def _push_sequence_gap_if_needed(self, event: PerpsSessionEvent) -> None:
        if isinstance(event, PerpsResyncEvent):
            return
        channel = getattr(event, "channel", None)
        sequence = getattr(event, "sequence", None)
        if not isinstance(channel, str) or not isinstance(sequence, int):
            return
        if channel in _SERVER_RESYNC_CHANNELS:
            return
        previous = self._sequences.get(channel)
        self._sequences[channel] = sequence
        if previous is None or sequence == previous + 1:
            return
        self._emit_event(
            PerpsResyncEvent(
                reason="sequence_gap",
                channel=channel,
                previous_sequence=previous,
                sequence=sequence,
            )
        )

    _RECENT_ORDERS_LIMIT = 256

    def _emit_event(self, event: PerpsSessionEvent) -> None:
        if isinstance(event, PerpsOrderEvent):
            self._recent_orders[event.payload.id] = event.payload
            while len(self._recent_orders) > self._RECENT_ORDERS_LIMIT:
                self._recent_orders.pop(next(iter(self._recent_orders)))
        for waiter in tuple(self._event_waiters):
            try:
                matched = waiter.predicate(event)
            except Exception:
                self._logger.exception("perps event waiter predicate raised")
                continue
            if matched and not waiter.future.done():
                waiter.future.set_result(event)
        self._push(event)

    def _push(self, event: PerpsSessionEvent) -> None:
        if self._ended:
            return
        try:
            self._queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass
        try:
            self._queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        else:
            self._dropped_events += 1
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped_events += 1

    def _end(self, error: BaseException | None = None) -> None:
        if self._ended:
            return
        self._ended = True
        self._end_error = error
        try:
            self._queue.put_nowait(_END)
            return
        except asyncio.QueueFull:
            pass
        with contextlib.suppress(asyncio.QueueEmpty):
            self._queue.get_nowait()
        self._queue.put_nowait(_END)

    def _reject_pending(self, error: BaseException) -> None:
        for pending in tuple(self._pending.values()):
            self._reject_future(pending.future, error)
        self._pending.clear()

    def _reject_event_waiters(self, error: BaseException) -> None:
        for waiter in tuple(self._event_waiters):
            if not waiter.future.done():
                waiter.future.set_exception(error)
        self._event_waiters.clear()


def _parse_session_ack(data: object) -> None:
    entries: list[object] = cast("list[object]", data) if isinstance(data, list) else [data]
    if not entries:
        raise ValueError("empty Perps session acknowledgement")
    for entry in entries:
        ack = cast("dict[str, Any]", entry) if isinstance(entry, dict) else None
        if ack is None or ack.get("status") not in ("ok", "err"):
            raise ValueError("invalid Perps session acknowledgement")
    for entry in entries:
        error = _error_ack(entry)
        if error is not None:
            raise RequestRejectedError(error, status=200)
    return None


def _parse_post_order_acks(data: object) -> list[PerpsPostOrderAck]:
    if not isinstance(data, list):
        raise ValueError("expected a list of Perps post order acknowledgements")
    return [PerpsPostOrderAck.parse_response(item) for item in cast("list[object]", data)]


def _parse_cancel_results(data: object) -> list[PerpsCancelOrderResult]:
    if not isinstance(data, list):
        raise ValueError("expected a list of Perps cancel order results")
    return [PerpsCancelOrderResult.parse_response(item) for item in cast("list[object]", data)]


def _error_ack(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    ack = cast("dict[str, Any]", value)
    if ack.get("status") != "err":
        return None
    error = ack.get("error")
    return str(error) if isinstance(error, str) and error else "Perps command failed."


__all__ = ["PerpsSession"]
