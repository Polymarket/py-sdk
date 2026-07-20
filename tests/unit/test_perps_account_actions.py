"""Perps account pagination behavior against a mocked transport."""

import asyncio
import base64
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from polymarket._internal.actions.perps import account as perps_account
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import RequestRejectedError, UserInputError
from polymarket.models.perps.notifications import (
    PerpsNotificationsPage,
    PerpsNotificationsPaginator,
    PerpsPositionChangeNotification,
)

_BASE_URL = "https://perps.test"


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> AsyncTransport:
    return AsyncTransport(
        base_url=_BASE_URL,
        client=httpx.AsyncClient(base_url=_BASE_URL, transport=httpx.MockTransport(handler)),
    )


def _cursor(state: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(state, separators=(",", ":")).encode()).decode()


def test_descending_account_paginators_reject_malformed_cursor_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch with a malformed cursor")

    async def run() -> None:
        transport = _transport(handler)
        try:
            funding = perps_account.list_funding_payments(transport)
            bad_funding_cursors: list[dict[str, Any]] = [
                {"kind": "perpsFundingPayments", "start_timestamp": 0, "end_timestamp": 1},
                {
                    "kind": "perpsFundingPayments",
                    "start_timestamp": 0,
                    "end_timestamp": 1,
                    "seen_keys": [1],
                },
            ]
            for state in bad_funding_cursors:
                with pytest.raises(UserInputError, match="cursor"):
                    await funding.from_cursor(_cursor(state)).first_page()

            deposits = perps_account.list_deposits(transport)
            with pytest.raises(UserInputError, match="cursor"):
                await deposits.from_cursor(
                    _cursor(
                        {
                            "kind": "perpsDeposits",
                            "start_timestamp": 0,
                            "end_timestamp": 1,
                            "seen_keys": [],
                            "deposit_status": "bogus",
                        }
                    )
                ).first_page()
        finally:
            await transport.close()

    asyncio.run(run())


def test_ascending_account_paginators_reject_malformed_cursor_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch with a malformed cursor")

    async def run() -> None:
        transport = _transport(handler)
        try:
            pnl = perps_account.list_pnl_history(transport, interval="1h", start=0)
            bad_pnl_cursors: list[dict[str, Any]] = [
                {"kind": "perpsPnlHistory", "interval": "1h", "start_timestamp": 0},
                {
                    "kind": "perpsPnlHistory",
                    "interval": 5,
                    "start_timestamp": 0,
                    "end_timestamp": 1,
                },
            ]
            for state in bad_pnl_cursors:
                with pytest.raises(UserInputError, match="cursor"):
                    await pnl.from_cursor(_cursor(state)).first_page()
        finally:
            await transport.close()

    asyncio.run(run())


def _fill(trade_id: int, timestamp: int) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "order_id": 100 + trade_id,
        "instrument_id": 1,
        "side": "long",
        "price": "100",
        "quantity": "1",
        "taker": True,
        "fee": "0.01",
        "fee_asset": "USDC",
        "previous_size": "0",
        "previous_entry_price": "0",
        "pnl": "0",
        "liquidation": False,
        "timestamp": timestamp,
        "hash": "0x" + "1" * 64,
    }


def test_list_fills_first_page_sends_no_pagination_params() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [_fill(2, 2000), _fill(1, 1000)], "more": False})

    async def run() -> None:
        transport = _transport(handler)
        try:
            first = await perps_account.list_fills(transport).first_page()
        finally:
            await transport.close()

        assert [fill.trade_id for fill in first.items] == [2, 1]
        assert first.has_more is False
        assert first.next_cursor is None
        assert dict(requests[0].url.params) == {}

    asyncio.run(run())


def test_list_fills_pages_with_native_cursor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "cursor" not in request.url.params:
            return httpx.Response(
                200, json={"data": [_fill(3, 3000), _fill(2, 2000)], "more": True}
            )
        return httpx.Response(200, json={"data": [_fill(1, 1000)], "more": False})

    async def run() -> None:
        transport = _transport(handler)
        try:
            pages = perps_account.list_fills(transport, start=0, end=3000)
            first = await pages.first_page()
            second = await pages.from_cursor(first.next_cursor).first_page()
        finally:
            await transport.close()

        assert [fill.trade_id for fill in first.items] == [3, 2]
        assert first.has_more is True
        assert first.next_cursor == "2"
        assert [fill.trade_id for fill in second.items] == [1]
        assert second.has_more is False
        assert dict(requests[0].url.params) == {"start_timestamp": "0", "end_timestamp": "3000"}
        assert dict(requests[1].url.params) == {
            "start_timestamp": "0",
            "end_timestamp": "3000",
            "cursor": "2",
        }

    asyncio.run(run())


def test_list_fills_iterates_ascending_pages_forwarding_sort_with_cursor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "cursor" not in request.url.params:
            return httpx.Response(
                200, json={"data": [_fill(1, 1000), _fill(2, 2000)], "more": True}
            )
        return httpx.Response(200, json={"data": [_fill(3, 3000)], "more": False})

    async def run() -> None:
        transport = _transport(handler)
        try:
            trade_ids = [
                fill.trade_id
                async for fill in perps_account.list_fills(transport, sort="asc").iter_items()
            ]
        finally:
            await transport.close()

        assert trade_ids == [1, 2, 3]
        assert dict(requests[0].url.params) == {"sort": "asc"}
        assert dict(requests[1].url.params) == {"sort": "asc", "cursor": "2"}

    asyncio.run(run())


def test_list_fills_forwards_caller_cursor_unchanged_with_filters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [_fill(41, 1000)], "more": False})

    async def run() -> None:
        transport = _transport(handler)
        try:
            first = await perps_account.list_fills(
                transport, end=5000, sort="desc", cursor="42"
            ).first_page()
        finally:
            await transport.close()

        assert [fill.trade_id for fill in first.items] == [41]
        assert dict(requests[0].url.params) == {
            "end_timestamp": "5000",
            "sort": "desc",
            "cursor": "42",
        }

    asyncio.run(run())


def test_list_fills_rejects_invalid_sort() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch with invalid input")

    async def run() -> None:
        transport = _transport(handler)
        try:
            with pytest.raises(UserInputError, match="sort"):
                perps_account.list_fills(transport, sort="newest")  # type: ignore[arg-type]
        finally:
            await transport.close()

    asyncio.run(run())


def _notification_entry(notification_id: str, *, sequence_hint: int = 0) -> dict[str, Any]:
    return {
        "notification": {
            "id": notification_id,
            "type": "position_opened",
            "instrument_id": 1,
            "side": "long",
            "size": "0.5",
            "avg_price": "100",
            "leverage": 2,
        },
        "read_at": None,
        "ts": 1751500000000 + sequence_hint,
    }


def test_list_notifications_pins_since_seq_across_pages() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "items": [_notification_entry("5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0")],
                    "unread": 3,
                    "durable_source_seq": 90,
                    "has_more": True,
                    "next_cursor": "server-cursor-2",
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [_notification_entry("6a5b4c3d-2e1f-40a9-b8c7-d6e5f4a3b2c1")],
                "unread": 3,
                "durable_source_seq": 91,
                "has_more": False,
                "next_cursor": None,
            },
        )

    async def run() -> None:
        transport = _transport(handler)
        try:
            pages = perps_account.list_notifications(transport, since_seq=42, limit=25)
            first = await pages.first_page()
            assert first.unread == 3
            assert first.durable_source_seq == 90
            assert first.has_more is True
            assert first.next_cursor is not None
            notification = first.items[0].notification
            assert isinstance(notification, PerpsPositionChangeNotification)
            assert notification.size == Decimal("0.5")
            assert first.items[0].read_at is None

            second = await pages.from_cursor(first.next_cursor).first_page()
            assert second.has_more is False
            assert second.next_cursor is None
            assert second.durable_source_seq == 91
        finally:
            await transport.close()

        first_params = dict(requests[0].url.params)
        assert first_params == {"since_seq": "42", "limit": "25"}
        second_params = dict(requests[1].url.params)
        assert second_params == {"cursor": "server-cursor-2", "since_seq": "42", "limit": "25"}

    asyncio.run(run())


def test_list_notifications_rejects_invalid_inputs_and_cursors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch with invalid input")

    async def run() -> None:
        transport = _transport(handler)
        try:
            with pytest.raises(UserInputError, match="since_seq"):
                perps_account.list_notifications(transport, since_seq=-1)
            with pytest.raises(UserInputError, match="limit"):
                perps_account.list_notifications(transport, limit=0)

            pages = perps_account.list_notifications(transport)
            bad_cursors: list[dict[str, Any]] = [
                {"kind": "perpsNotifications"},
                {"kind": "perpsNotifications", "cursor": ""},
                {"kind": "perpsNotifications", "cursor": "ok", "since_seq": -1},
                {"kind": "perpsNotifications", "cursor": "ok", "limit": 0},
                {"kind": "perpsFills", "cursor": "ok"},
            ]
            for state in bad_cursors:
                with pytest.raises(UserInputError, match="cursor"):
                    await pages.from_cursor(_cursor(state)).first_page()
        finally:
            await transport.close()

    asyncio.run(run())


def test_notifications_paginator_from_cursor_none_yields_no_pages() -> None:
    fetch_count = [0]

    async def fetch(_cursor: str | None) -> PerpsNotificationsPage:
        fetch_count[0] += 1
        return PerpsNotificationsPage(items=(), has_more=False, unread=3, durable_source_seq=7)

    async def run() -> None:
        empty = PerpsNotificationsPaginator(fetch=fetch).from_cursor(None)
        assert [page async for page in empty] == []
        first = await empty.first_page()
        assert first.items == ()
        assert first.has_more is False
        assert first.unread == 0
        assert first.durable_source_seq == 0
        assert fetch_count[0] == 0

    asyncio.run(run())


def test_mark_notifications_read_by_ids_posts_id_list() -> None:
    bodies: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "ok"})

    async def run() -> None:
        transport = _transport(handler)
        try:
            await perps_account.mark_notifications_read(
                transport, ids=["5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0"]
            )
        finally:
            await transport.close()
        assert bodies == [{"ids": ["5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0"]}]

    asyncio.run(run())


def test_mark_notifications_read_up_to_encodes_before_cursor() -> None:
    bodies: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "ok"})

    async def run() -> None:
        from polymarket.models.perps.notifications import PerpsNotificationEntry

        raw = _notification_entry("5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0")
        # A ts whose float-seconds round trip lands just below the integer,
        # so truncating instead of rounding would encode it off by 1ms.
        raw["ts"] = 2171146883240
        entry = PerpsNotificationEntry.parse_response(raw)
        transport = _transport(handler)
        try:
            await perps_account.mark_notifications_read(transport, up_to=entry)
        finally:
            await transport.close()

        (body,) = bodies
        before = body["before"]
        padding = "=" * (-len(before) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(before + padding))
        assert decoded == {"ts": 2171146883240, "id": "5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0"}

    asyncio.run(run())


def test_mark_notifications_read_rejects_err_status_and_bad_arguments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "err", "error": "unknown ids"})

    async def run() -> None:
        transport = _transport(handler)
        try:
            with pytest.raises(RequestRejectedError, match="unknown ids"):
                await perps_account.mark_notifications_read(
                    transport, ids=["5f4a3c2b-1d0e-49f8-a7b6-c5d4e3f2a1b0"]
                )
            with pytest.raises(UserInputError, match="exactly one"):
                await perps_account.mark_notifications_read(transport)
            with pytest.raises(UserInputError, match="ids"):
                await perps_account.mark_notifications_read(transport, ids=[])
        finally:
            await transport.close()

    asyncio.run(run())
