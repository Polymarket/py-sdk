"""Perps public read and pagination behavior against a mocked transport."""

import asyncio
import base64
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from polymarket._internal.actions.perps import public as perps_public
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UnexpectedResponseError, UserInputError

_BASE_URL = "https://perps.test"


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> AsyncTransport:
    return AsyncTransport(
        base_url=_BASE_URL,
        client=httpx.AsyncClient(base_url=_BASE_URL, transport=httpx.MockTransport(handler)),
    )


def _query(request: httpx.Request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(str(request.url)).query).items()}


def _cursor(state: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(state, separators=(",", ":")).encode()).decode()


@pytest.mark.parametrize("time", [1_786_697_208_022, True, "1786697208022", None])
def test_get_server_time_parses_only_epoch_milliseconds(time: object) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"time": time})

    async def run() -> None:
        transport = _transport(handler)
        try:
            if isinstance(time, int) and not isinstance(time, bool):
                server_time = await perps_public.get_server_time(transport)
                assert server_time.tzinfo is not None
                assert int(server_time.timestamp() * 1000) == time
            else:
                with pytest.raises(UnexpectedResponseError):
                    await perps_public.get_server_time(transport)
        finally:
            await transport.close()

    asyncio.run(run())
    assert [request.url.path for request in requests] == ["/v1/info/time"]


def test_list_candles_steps_forward_by_interval() -> None:
    requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = _query(request)
        requests.append(query)
        start = int(query["start_timestamp"])
        if len(requests) == 1:
            candles = [
                [start, "1", "2", "0.5", "1.5", "10", 1],
                [start + 60_000, "1", "2", "0.5", "1.5", "10", 1],
            ]
            return httpx.Response(200, json={"data": candles, "more": True})
        return httpx.Response(
            200, json={"data": [[start, "1", "2", "0.5", "1.5", "10", 1]], "more": False}
        )

    async def run() -> None:
        transport = _transport(handler)
        try:
            paginator = perps_public.list_candles(
                transport,
                instrument_id=1,
                interval="1m",
                start=1_000_000,
                end=2_000_000,
            )
            items = [item async for item in paginator.iter_items()]
            assert len(items) == 3
        finally:
            await transport.close()

    asyncio.run(run())
    assert requests[0]["start_timestamp"] == "1000000"
    # The next window starts one interval after the last returned candle.
    assert requests[1]["start_timestamp"] == str(1_000_000 + 60_000 + 60_000)
    assert all(request["interval"] == "1m" for request in requests)


def test_list_funding_history_pages_backward() -> None:
    requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = _query(request)
        requests.append(query)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"funding_rate": "0.001", "timestamp": 1_900_000},
                        {"funding_rate": "0.002", "timestamp": 1_500_000},
                    ],
                    "more": True,
                },
            )
        return httpx.Response(
            200,
            json={"data": [{"funding_rate": "0.003", "timestamp": 1_200_000}], "more": False},
        )

    async def run() -> None:
        transport = _transport(handler)
        try:
            paginator = perps_public.list_funding_history(
                transport, instrument_id=1, start=1_000_000, end=2_000_000
            )
            items = [item async for item in paginator.iter_items()]
            assert [item.funding_rate for item in items] == [
                Decimal("0.001"),
                Decimal("0.002"),
                Decimal("0.003"),
            ]
        finally:
            await transport.close()

    asyncio.run(run())
    assert requests[0]["end_timestamp"] == "2000000"
    # The next window ends just before the oldest returned observation.
    assert requests[1]["end_timestamp"] == str(1_500_000 - 1)


def test_list_trades_deduplicates_boundary_trades_across_pages() -> None:
    requests: list[dict[str, str]] = []

    def _trade(trade_id: int, timestamp: int) -> dict[str, Any]:
        return {
            "trade_id": trade_id,
            "instrument_id": 1,
            "side": "long",
            "price": "1",
            "quantity": "1",
            "timestamp": timestamp,
        }

    def handler(request: httpx.Request) -> httpx.Response:
        query = _query(request)
        requests.append(query)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"data": [_trade(3, 1_900_000), _trade(2, 1_500_000)], "more": True},
            )
        # The server repeats the boundary trade in the next window.
        return httpx.Response(
            200,
            json={"data": [_trade(2, 1_500_000), _trade(1, 1_200_000)], "more": False},
        )

    async def run() -> None:
        transport = _transport(handler)
        try:
            paginator = perps_public.list_trades(
                transport, instrument_id=1, start=1_000_000, end=2_000_000
            )
            items = [item async for item in paginator.iter_items()]
            assert [item.trade_id for item in items] == [3, 2, 1]
        finally:
            await transport.close()

    asyncio.run(run())
    # The follow-up window re-requests the boundary timestamp inclusively.
    assert requests[1]["end_timestamp"] == "1500000"


def test_trades_cursor_is_bound_to_its_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch with an invalid cursor")

    async def run() -> None:
        transport = _transport(handler)
        try:
            paginator = perps_public.list_trades(transport, instrument_id=1)
            bogus = _cursor({"kind": "perpsCandles"})
            with pytest.raises(UserInputError, match="cursor"):
                await paginator.from_cursor(bogus).first_page()
        finally:
            await transport.close()

    asyncio.run(run())


def test_public_paginators_reject_malformed_cursor_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch with a malformed cursor")

    async def run() -> None:
        transport = _transport(handler)
        try:
            trades = perps_public.list_trades(transport, instrument_id=1)
            bad_trade_cursors: list[dict[str, Any]] = [
                {
                    "kind": "perpsTrades",
                    "start_timestamp": 0,
                    "end_timestamp": 1,
                    "seen_trade_ids": [],
                },
                {
                    "kind": "perpsTrades",
                    "instrument_id": 1,
                    "start_timestamp": 0,
                    "end_timestamp": 1,
                    "seen_trade_ids": ["bad"],
                },
            ]
            for state in bad_trade_cursors:
                with pytest.raises(UserInputError, match="cursor"):
                    await trades.from_cursor(_cursor(state)).first_page()

            candles = perps_public.list_candles(transport, instrument_id=1, interval="1m")
            with pytest.raises(UserInputError, match="cursor"):
                await candles.from_cursor(
                    _cursor(
                        {
                            "kind": "perpsCandles",
                            "instrument_id": 1,
                            "interval": "30m",
                            "start_timestamp": 0,
                            "end_timestamp": 1,
                        }
                    )
                ).first_page()
        finally:
            await transport.close()

    asyncio.run(run())


def test_fetch_tickers_merges_statistics_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        if path == "/v1/info/tickers":
            return httpx.Response(
                200,
                json=[
                    {
                        "instrument_id": 1,
                        "symbol": "XYZ-PERP",
                        "index_price": "100",
                        "mark_price": "101",
                        "last_price": "100.5",
                        "mid_price": "100.6",
                        "open_interest": "5000",
                        "funding_rate": "0.0001",
                        "next_funding": 1751503600000,
                    }
                ],
            )
        assert path == "/v1/info/statistics"
        return httpx.Response(
            200,
            json=[{"instrument_id": 1, "volume": "12345", "open_price": "99", "klines": []}],
        )

    async def run() -> None:
        transport = _transport(handler)
        try:
            tickers = await perps_public.fetch_tickers(transport)
            assert tickers[0].volume_24h == Decimal("12345")
            assert tickers[0].open_price == Decimal("99")
            assert tickers[0].mark_price == Decimal("101")
        finally:
            await transport.close()

    asyncio.run(run())


def test_fetch_book_rejects_unsupported_depth() -> None:
    async def run() -> None:
        transport = _transport(lambda request: httpx.Response(200, json={}))
        try:
            with pytest.raises(UserInputError, match="depth"):
                await perps_public.fetch_book(transport, instrument_id=1, depth=42)  # type: ignore[arg-type]
        finally:
            await transport.close()

    asyncio.run(run())
