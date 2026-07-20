"""Perps account pagination behavior against a mocked transport."""

import asyncio
import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from polymarket._internal.actions.perps import account as perps_account
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UserInputError

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
