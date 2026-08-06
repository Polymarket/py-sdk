"""Perps authenticated account reads."""

import base64
import json
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, TypeVar, cast

from pydantic import Field

from polymarket._internal.actions.perps.paging import (
    NINETY_DAYS_MS,
    ONE_DAY_MS,
    as_json_dict,
    decode_perps_ascending_account_cursor,
    decode_perps_descending_account_cursor,
    decode_perps_notifications_cursor,
    encode_perps_cursor,
    interval_ms,
    parse_data_envelope,
    to_epoch_ms,
)
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import RequestRejectedError, UnexpectedResponseError, UserInputError
from polymarket.models.base import BaseModel
from polymarket.models.perps.account import (
    PerpsAccountConfig,
    PerpsAccountStats,
    PerpsAutoCancelStatus,
    PerpsBalance,
    PerpsEquityPoint,
    PerpsFundingPayment,
    PerpsPnlPoint,
    PerpsPortfolio,
)
from polymarket.models.perps.funds import PerpsDeposit, PerpsWithdrawal
from polymarket.models.perps.notifications import (
    PerpsNotificationEntry,
    PerpsNotificationsPage,
    PerpsNotificationsPaginator,
)
from polymarket.models.perps.orders import PerpsFill, PerpsOrder
from polymarket.models.perps.requests import validate_client_order_id
from polymarket.models.perps.types import (
    PerpsDepositStatus,
    PerpsPnlInterval,
    PerpsSortDirection,
    PerpsWithdrawalStatus,
)
from polymarket.pagination import AsyncPaginator, Page

_M = TypeVar("_M", bound=BaseModel)

_PNL_INTERVALS = ("1h", "4h", "1d", "1w")
_FUND_STATUSES = ("pending", "confirmed", "removed")
_SORT_DIRECTIONS = ("desc", "asc")
_WITHDRAWAL_STATUSES = ("pending", "confirmed", "removed", "failed")


async def fetch_balances(api: AsyncTransport) -> tuple[PerpsBalance, ...]:
    return PerpsBalance.parse_response_list(await api.get_json("/v1/account/balances"))


async def fetch_portfolio(api: AsyncTransport) -> PerpsPortfolio:
    return PerpsPortfolio.parse_response(await api.get_json("/v1/account/portfolio"))


async def fetch_stats(api: AsyncTransport) -> PerpsAccountStats:
    return PerpsAccountStats.parse_response(await api.get_json("/v1/account/stats"))


async def fetch_auto_cancel_status(api: AsyncTransport) -> PerpsAutoCancelStatus:
    return PerpsAutoCancelStatus.parse_response(await api.get_json("/v1/account/auto-cancel"))


async def fetch_account_config(
    api: AsyncTransport, *, instrument_id: int | None = None
) -> tuple[PerpsAccountConfig, ...]:
    return PerpsAccountConfig.parse_response_list(
        await api.get_json("/v1/account/config", params={"instrument_id": instrument_id})
    )


async def fetch_open_orders(
    api: AsyncTransport, *, instrument_id: int | None = None
) -> tuple[PerpsOrder, ...]:
    return PerpsOrder.parse_response_list(
        await api.get_json("/v1/account/open-orders", params={"instrument_id": instrument_id})
    )


async def fetch_orders(
    api: AsyncTransport,
    *,
    order_id: int | None = None,
    client_order_id: str | None = None,
    instrument_id: int | None = None,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
) -> tuple[PerpsOrder, ...]:
    if client_order_id is not None:
        validate_client_order_id(client_order_id)
    return PerpsOrder.parse_response_list(
        await api.get_json(
            "/v1/account/orders",
            params={
                "order_id": order_id,
                "client_order_id": client_order_id,
                "instrument_id": instrument_id,
                "start_timestamp": to_epoch_ms("start", start),
                "end_timestamp": to_epoch_ms("end", end),
            },
        )
    )


def list_fills(
    api: AsyncTransport,
    *,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
    sort: PerpsSortDirection | None = None,
    cursor: str | None = None,
) -> AsyncPaginator[PerpsFill]:
    if sort is not None and sort not in _SORT_DIRECTIONS:
        raise UserInputError(f"sort must be one of {list(_SORT_DIRECTIONS)}, got {sort!r}")
    start_ms = to_epoch_ms("start", start)
    end_ms = to_epoch_ms("end", end)

    async def fetch(page_cursor: str | None) -> Page[PerpsFill]:
        data, more = parse_data_envelope(
            await api.get_json(
                "/v1/account/fills",
                params={
                    "start_timestamp": start_ms,
                    "end_timestamp": end_ms,
                    "sort": sort,
                    "cursor": page_cursor,
                },
            )
        )
        items = tuple(PerpsFill.parse_response(item) for item in data)
        if not more or not items:
            return Page(items=items, has_more=False)
        return Page(items=items, has_more=True, next_cursor=str(items[-1].trade_id))

    return AsyncPaginator(fetch=fetch, initial_cursor=cursor)


def list_funding_payments(
    api: AsyncTransport,
    *,
    instrument_id: int | None = None,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
) -> AsyncPaginator[PerpsFundingPayment]:
    return _descending_history(
        api,
        path="/v1/account/funding",
        kind="perpsFundingPayments",
        model=PerpsFundingPayment,
        default_window_ms=ONE_DAY_MS,
        start=start,
        end=end,
        get_key=lambda item: (
            f"{item.get('instrument_id')}:{item.get('timestamp')}:{item.get('funding')}"
        ),
        get_timestamp=lambda item: item.get("timestamp"),
        extra_params={"instrument_id": instrument_id},
    )


def list_deposits(
    api: AsyncTransport,
    *,
    deposit_status: PerpsDepositStatus | None = None,
    hash: str | None = None,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
) -> AsyncPaginator[PerpsDeposit]:
    if deposit_status is not None and deposit_status not in _FUND_STATUSES:
        raise UserInputError(
            f"deposit_status must be one of {list(_FUND_STATUSES)}, got {deposit_status!r}"
        )
    return _descending_history(
        api,
        path="/v1/account/deposits",
        kind="perpsDeposits",
        model=PerpsDeposit,
        default_window_ms=NINETY_DAYS_MS,
        start=start,
        end=end,
        get_key=lambda item: str(item.get("hash")),
        get_timestamp=lambda item: item.get("confirmed_timestamp") or item.get("created_timestamp"),
        extra_params={"deposit_status": deposit_status, "hash": hash},
    )


def list_withdrawals(
    api: AsyncTransport,
    *,
    withdrawal_status: PerpsWithdrawalStatus | None = None,
    hash: str | None = None,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
) -> AsyncPaginator[PerpsWithdrawal]:
    if withdrawal_status is not None and withdrawal_status not in _WITHDRAWAL_STATUSES:
        raise UserInputError(
            f"withdrawal_status must be one of {list(_WITHDRAWAL_STATUSES)},"
            f" got {withdrawal_status!r}"
        )
    return _descending_history(
        api,
        path="/v1/account/withdrawals",
        kind="perpsWithdrawals",
        model=PerpsWithdrawal,
        default_window_ms=NINETY_DAYS_MS,
        start=start,
        end=end,
        get_key=lambda item: str(item.get("withdraw_id")),
        get_timestamp=lambda item: item.get("confirmed_timestamp") or item.get("created_timestamp"),
        extra_params={"withdrawal_status": withdrawal_status, "hash": hash},
    )


class _PerpsNotificationsResponse(BaseModel):
    items: tuple[PerpsNotificationEntry, ...]
    unread: int = Field(ge=0)
    durable_source_seq: int = Field(ge=0)
    has_more: bool
    next_cursor: str | None


def list_notifications(
    api: AsyncTransport,
    *,
    since_seq: int | None = None,
    limit: int | None = None,
) -> PerpsNotificationsPaginator:
    if since_seq is not None and since_seq < 0:
        raise UserInputError("since_seq must be a non-negative int")
    if limit is not None and limit <= 0:
        raise UserInputError("limit must be a positive int")

    async def fetch(cursor: str | None) -> PerpsNotificationsPage:
        if cursor is None:
            state: dict[str, Any] = {"since_seq": since_seq, "limit": limit}
        else:
            state = decode_perps_notifications_cursor(cursor)
        response = _PerpsNotificationsResponse.parse_response(
            await api.get_json(
                "/v1/account/notifications",
                params={
                    "cursor": state.get("cursor"),
                    "since_seq": state.get("since_seq"),
                    "limit": state.get("limit"),
                },
            )
        )
        has_more = response.has_more and response.next_cursor is not None
        next_cursor = None
        if has_more:
            next_state: dict[str, Any] = {
                "kind": "perpsNotifications",
                "cursor": response.next_cursor,
            }
            if state.get("since_seq") is not None:
                next_state["since_seq"] = state["since_seq"]
            if state.get("limit") is not None:
                next_state["limit"] = state["limit"]
            next_cursor = encode_perps_cursor(next_state)
        return PerpsNotificationsPage(
            items=response.items,
            has_more=has_more,
            next_cursor=next_cursor,
            unread=response.unread,
            durable_source_seq=response.durable_source_seq,
        )

    return PerpsNotificationsPaginator(fetch=fetch)


def _encode_notifications_read_cursor(entry: PerpsNotificationEntry) -> str:
    # The upstream read cursor is base64url-encoded JSON keyed as {ts, id}.
    payload = json.dumps(
        {"ts": round(entry.timestamp.timestamp() * 1000), "id": entry.notification.id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


async def mark_notifications_read(
    api: AsyncTransport,
    *,
    ids: Sequence[str] | None = None,
    up_to: PerpsNotificationEntry | None = None,
) -> None:
    if (ids is None) == (up_to is None):
        raise UserInputError("Provide exactly one of ids or up_to")
    if ids is not None:
        if isinstance(ids, str | bytes):
            raise UserInputError("ids must be a sequence of notification ids, not a single string.")
        id_list = list(ids)
        if not id_list or any(not item for item in id_list):
            raise UserInputError("ids must be a non-empty sequence of notification ids")
        body: dict[str, Any] = {"ids": id_list}
    else:
        assert up_to is not None
        body = {"before": _encode_notifications_read_cursor(up_to)}
    ack = as_json_dict(await api.post_json("/v1/account/notifications/read", json=body))
    status = None if ack is None else ack.get("status")
    if status not in ("ok", "err"):
        raise UnexpectedResponseError(
            "Perps notifications read response did not match expected shape"
        )
    if status == "err":
        error = ack.get("error") if ack is not None else None
        raise RequestRejectedError(
            error
            if isinstance(error, str) and error
            else "Perps notifications read request was rejected.",
            status=200,
        )


def list_equity_history(
    api: AsyncTransport,
    *,
    interval: PerpsPnlInterval,
    start: datetime | int,
    end: datetime | int | None = None,
) -> AsyncPaginator[PerpsEquityPoint]:
    return _ascending_history(
        api,
        path="/v1/account/equity",
        kind="perpsEquityHistory",
        model=PerpsEquityPoint,
        interval=interval,
        start=start,
        end=end,
    )


def list_pnl_history(
    api: AsyncTransport,
    *,
    interval: PerpsPnlInterval,
    start: datetime | int,
    end: datetime | int | None = None,
) -> AsyncPaginator[PerpsPnlPoint]:
    return _ascending_history(
        api,
        path="/v1/account/pnl",
        kind="perpsPnlHistory",
        model=PerpsPnlPoint,
        interval=interval,
        start=start,
        end=end,
    )


def _descending_history(
    api: AsyncTransport,
    *,
    path: str,
    kind: str,
    model: type[_M],
    default_window_ms: int,
    start: datetime | int | None,
    end: datetime | int | None,
    get_key: Callable[[dict[str, Any]], str],
    get_timestamp: Callable[[dict[str, Any]], Any],
    extra_params: dict[str, Any] | None = None,
) -> AsyncPaginator[_M]:
    start_ms = to_epoch_ms("start", start)
    end_ms = to_epoch_ms("end", end)
    initial_extra = {key: value for key, value in (extra_params or {}).items() if value is not None}

    async def fetch(cursor: str | None) -> Page[_M]:
        if cursor is None:
            now = int(time.time() * 1000)
            state: dict[str, Any] = {
                "kind": kind,
                "start_timestamp": start_ms if start_ms is not None else now - default_window_ms,
                "end_timestamp": end_ms if end_ms is not None else now,
                "seen_keys": [],
                **initial_extra,
            }
        else:
            statuses = _WITHDRAWAL_STATUSES if kind == "perpsWithdrawals" else _FUND_STATUSES
            state = decode_perps_descending_account_cursor(
                cursor, kind=kind, fund_statuses=statuses
            )
        params = {
            key: value
            for key, value in state.items()
            if key not in ("kind", "seen_keys") and value is not None
        }
        data, more = parse_data_envelope(await api.get_json(path, params=params))
        seen: set[str] = set(cast("list[str]", state.get("seen_keys", [])))
        fresh: list[dict[str, Any]] = []
        for raw_item in data:
            item = as_json_dict(raw_item)
            if item is not None and get_key(item) not in seen:
                fresh.append(item)
        items = tuple(model.parse_response(item) for item in fresh)
        raw_last = as_json_dict(data[-1]) if data else None
        last = fresh[-1] if fresh else None
        cursor_ts = (
            get_timestamp(last)
            if last is not None
            else get_timestamp(raw_last)
            if raw_last is not None
            else None
        )
        has_more = more and isinstance(cursor_ts, int) and cursor_ts > int(state["start_timestamp"])
        if not has_more or not isinstance(cursor_ts, int):
            return Page(items=items, has_more=False)
        next_state: dict[str, Any]
        if last is None:
            next_state = {**state, "end_timestamp": cursor_ts - 1, "seen_keys": []}
        else:
            boundary: set[str] = (
                set(cast("list[str]", state.get("seen_keys", [])))
                if state["end_timestamp"] == cursor_ts
                else set()
            )
            for item in fresh:
                if get_timestamp(item) == cursor_ts:
                    boundary.add(get_key(item))
            next_state = {**state, "end_timestamp": cursor_ts, "seen_keys": sorted(boundary)}
        return Page(items=items, has_more=True, next_cursor=encode_perps_cursor(next_state))

    return AsyncPaginator(fetch=fetch)


def _ascending_history(
    api: AsyncTransport,
    *,
    path: str,
    kind: str,
    model: type[_M],
    interval: PerpsPnlInterval,
    start: datetime | int,
    end: datetime | int | None,
) -> AsyncPaginator[_M]:
    if interval not in _PNL_INTERVALS:
        raise UserInputError(f"interval must be one of {list(_PNL_INTERVALS)}, got {interval!r}")
    start_ms = to_epoch_ms("start", start)
    end_ms = to_epoch_ms("end", end)

    async def fetch(cursor: str | None) -> Page[_M]:
        if cursor is None:
            state: dict[str, Any] = {
                "kind": kind,
                "interval": interval,
                "start_timestamp": start_ms,
                "end_timestamp": end_ms if end_ms is not None else int(time.time() * 1000),
            }
        else:
            state = decode_perps_ascending_account_cursor(
                cursor, kind=kind, intervals=_PNL_INTERVALS
            )
        data, more = parse_data_envelope(
            await api.get_json(
                path,
                params={
                    "interval": state["interval"],
                    "start_timestamp": state["start_timestamp"],
                    "end_timestamp": state["end_timestamp"],
                },
            )
        )
        items = tuple(model.parse_response(item) for item in data)
        last_ts = _point_timestamp(data[-1]) if data else None
        has_more = more and isinstance(last_ts, int) and last_ts < int(state["end_timestamp"])
        next_cursor = None
        if has_more and isinstance(last_ts, int):
            next_cursor = encode_perps_cursor(
                {**state, "start_timestamp": last_ts + interval_ms(state["interval"])}
            )
        return Page(items=items, has_more=has_more, next_cursor=next_cursor)

    return AsyncPaginator(fetch=fetch)


def _point_timestamp(item: object) -> int | None:
    if isinstance(item, list):
        entries = cast("list[object]", item)
        if entries and isinstance(entries[0], int):
            return entries[0]
    return None


__all__ = [
    "fetch_account_config",
    "fetch_auto_cancel_status",
    "fetch_balances",
    "fetch_open_orders",
    "fetch_orders",
    "fetch_portfolio",
    "fetch_stats",
    "list_deposits",
    "list_equity_history",
    "list_fills",
    "list_funding_payments",
    "list_notifications",
    "list_pnl_history",
    "list_withdrawals",
    "mark_notifications_read",
]
