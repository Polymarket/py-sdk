# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncPublicClient, AsyncSecureClient
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UserInputError
from polymarket.models.clob.rewards import (
    CurrentReward,
    MarketReward,
    RewardsPercentages,
    TotalUserEarning,
    UserEarning,
    UserRewardsEarning,
)

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"


def _routed_handler(
    captured: list[httpx.Request],
    routes: dict[tuple[str, str], Any],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        key = (request.method, path)
        if key in routes:
            return httpx.Response(200, json=routes[key], request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return httpx.MockTransport(handler)


def _install_public_clob(client: AsyncPublicClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, clob=transport)


def _install_secure_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)


def _install_secure_public_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, clob=transport)


async def _make_secure_client() -> AsyncSecureClient:
    return await AsyncSecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


_CURRENT_REWARDS_PAGE: dict[str, Any] = {
    "limit": 100,
    "count": 1,
    "next_cursor": "LTE=",
    "data": [
        {
            "condition_id": _CONDITION_ID,
            "rewards_max_spread": 3.0,
            "tokens": [],
        }
    ],
}

_MARKET_REWARDS_PAGE: dict[str, Any] = {
    "limit": 100,
    "count": 1,
    "next_cursor": "LTE=",
    "data": [
        {
            "condition_id": _CONDITION_ID,
            "question": "Q?",
            "tokens": [{"token_id": "8501497", "outcome": "Yes", "price": "0.5"}],
        }
    ],
}

_USER_EARNINGS_PAGE: dict[str, Any] = {
    "limit": 100,
    "count": 1,
    "next_cursor": "LTE=",
    "data": [
        {
            "asset_address": "0xUSDC",
            "asset_rate": 0.0001,
            "condition_id": _CONDITION_ID,
            "date": 1700000000000,
            "earnings": "5.5",
            "maker_address": "0xMAKER",
        }
    ],
}

_USER_REWARDS_EARNINGS_PAGE: dict[str, Any] = {
    "limit": 100,
    "count": 1,
    "next_cursor": "LTE=",
    "data": [
        {
            "condition_id": _CONDITION_ID,
            "earning_percentage": 0.5,
            "earnings": [{"asset_address": "0xUSDC", "asset_rate": "0.001", "earnings": "5"}],
            "event_slug": "evt",
            "image": "img",
            "maker_address": "0xMAKER",
            "market_competitiveness": 0.75,
            "market_slug": "mkt",
            "question": "Q?",
            "rewards_config": [
                {
                    "asset_address": "0xUSDC",
                    "end_date": 1800000000000,
                    "rate_per_day": "100",
                    "start_date": 1700000000000,
                    "total_rewards": "10000",
                }
            ],
            "rewards_max_spread": 3.0,
            "rewards_min_size": "100",
            "tokens": [{"token_id": "8501497", "outcome": "Yes", "price": "0.5"}],
        }
    ],
}


def test_async_public_list_current_rewards_routes_to_public_clob() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[CurrentReward, ...]:
        client = AsyncPublicClient()
        try:
            _install_public_clob(
                client,
                _routed_handler(
                    captured, {("GET", "/rewards/markets/current"): _CURRENT_REWARDS_PAGE}
                ),
            )
            page = await client.list_current_rewards().first_page()
            return page.items
        finally:
            await client.close()

    items = asyncio.run(run())
    assert len(items) == 1
    assert captured[0].method == "GET"
    assert urlparse(str(captured[0].url)).path == "/rewards/markets/current"
    assert captured[0].headers.get("POLY_SIGNATURE") is None


def test_async_public_list_current_rewards_passes_sponsored_filter() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = AsyncPublicClient()
        try:
            _install_public_clob(
                client,
                _routed_handler(
                    captured, {("GET", "/rewards/markets/current"): _CURRENT_REWARDS_PAGE}
                ),
            )
            await client.list_current_rewards(sponsored=True).first_page()
        finally:
            await client.close()

    asyncio.run(run())
    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs.get("sponsored") == ["true"]


def test_async_public_list_market_rewards_routes_with_condition_id_in_path() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[MarketReward, ...]:
        client = AsyncPublicClient()
        try:
            _install_public_clob(
                client,
                _routed_handler(
                    captured,
                    {("GET", f"/rewards/markets/{_CONDITION_ID}"): _MARKET_REWARDS_PAGE},
                ),
            )
            page = await client.list_market_rewards(condition_id=_CONDITION_ID).first_page()
            return page.items
        finally:
            await client.close()

    items = asyncio.run(run())
    assert len(items) == 1
    assert urlparse(str(captured[0].url)).path == f"/rewards/markets/{_CONDITION_ID}"


def test_async_secure_get_order_scoring_sends_hmac_headers() -> None:
    captured: list[httpx.Request] = []

    async def run() -> bool:
        client = await _make_secure_client()
        try:
            _install_secure_clob(
                client,
                _routed_handler(captured, {("GET", "/order-scoring"): {"scoring": True}}),
            )
            return await client.get_order_scoring(order_id="0xORDER")
        finally:
            await client.close()

    assert asyncio.run(run()) is True
    request = captured[0]
    assert urlparse(str(request.url)).path == "/order-scoring"
    qs = parse_qs(urlparse(str(request.url)).query)
    assert qs.get("order_id") == ["0xORDER"]
    assert request.headers.get("POLY_SIGNATURE")


def test_async_secure_get_orders_scoring_posts_id_array() -> None:
    captured: list[httpx.Request] = []

    async def run() -> dict[str, bool]:
        client = await _make_secure_client()
        try:
            _install_secure_clob(
                client,
                _routed_handler(captured, {("POST", "/orders-scoring"): {"a": True, "b": False}}),
            )
            return await client.get_orders_scoring(order_ids=["a", "b"])
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result == {"a": True, "b": False}
    request = captured[0]
    assert request.method == "POST"
    assert urlparse(str(request.url)).path == "/orders-scoring"
    assert request.content == b'["a","b"]'


def test_async_secure_list_user_earnings_for_day_includes_signature_type() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[UserEarning, ...]:
        client = await _make_secure_client()
        try:
            _install_secure_clob(
                client,
                _routed_handler(captured, {("GET", "/rewards/user"): _USER_EARNINGS_PAGE}),
            )
            page = await client.list_user_earnings_for_day(date="2026-04-16").first_page()
            return page.items
        finally:
            await client.close()

    items = asyncio.run(run())
    assert len(items) == 1
    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs.get("date") == ["2026-04-16"]
    assert qs.get("signature_type") == ["0"]


def test_async_secure_get_total_earnings_for_user_for_day() -> None:
    captured: list[httpx.Request] = []
    response_body = [
        {
            "asset_address": "0xUSDC",
            "asset_rate": "0.01",
            "date": 1700000000000,
            "earnings": "100",
            "maker_address": "0xMAKER",
        }
    ]

    async def run() -> tuple[TotalUserEarning, ...]:
        client = await _make_secure_client()
        try:
            _install_secure_clob(
                client,
                _routed_handler(captured, {("GET", "/rewards/user/total"): response_body}),
            )
            return await client.get_total_earnings_for_user_for_day(date="2026-04-16")
        finally:
            await client.close()

    items = asyncio.run(run())
    assert len(items) == 1
    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs.get("date") == ["2026-04-16"]
    assert qs.get("signature_type") == ["0"]


def test_async_secure_list_user_earnings_and_markets_config_passes_filters() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[UserRewardsEarning, ...]:
        client = await _make_secure_client()
        try:
            _install_secure_clob(
                client,
                _routed_handler(
                    captured,
                    {("GET", "/rewards/user/markets"): _USER_REWARDS_EARNINGS_PAGE},
                ),
            )
            page = await client.list_user_earnings_and_markets_config(
                date="2026-04-16",
                no_competition=True,
                order_by="earnings",
                position="maker",
                page_size=50,
            ).first_page()
            return page.items
        finally:
            await client.close()

    items = asyncio.run(run())
    assert len(items) == 1
    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs.get("date") == ["2026-04-16"]
    assert qs.get("no_competition") == ["true"]
    assert qs.get("order_by") == ["earnings"]
    assert qs.get("position") == ["maker"]
    assert qs.get("page_size") == ["50"]


def test_async_secure_get_reward_percentages() -> None:
    captured: list[httpx.Request] = []

    async def run() -> RewardsPercentages:
        client = await _make_secure_client()
        try:
            _install_secure_clob(
                client,
                _routed_handler(
                    captured,
                    {("GET", "/rewards/user/percentages"): {"0xCOND1": 0.5}},
                ),
            )
            return await client.get_reward_percentages()
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result == {"0xCOND1": 0.5}
    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs.get("signature_type") == ["0"]


def test_async_secure_get_orders_scoring_rejects_empty_list() -> None:
    async def run() -> None:
        client = await _make_secure_client()
        try:
            await client.get_orders_scoring(order_ids=[])
        finally:
            await client.close()

    with pytest.raises(UserInputError):
        asyncio.run(run())


def test_async_secure_list_current_rewards_uses_unsigned_clob_not_secure_clob() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[CurrentReward, ...]:
        client = await _make_secure_client()
        try:
            _install_secure_public_clob(
                client,
                _routed_handler(
                    captured, {("GET", "/rewards/markets/current"): _CURRENT_REWARDS_PAGE}
                ),
            )
            page = await client.list_current_rewards().first_page()
            return page.items
        finally:
            await client.close()

    items = asyncio.run(run())
    assert len(items) == 1
    request = captured[0]
    assert request.headers.get("POLY_SIGNATURE") is None
    assert request.headers.get("POLY_API_KEY") is None
    assert request.headers.get("POLY_ADDRESS") is None
    assert request.headers.get("POLY_TIMESTAMP") is None


def test_async_secure_list_market_rewards_uses_unsigned_clob_not_secure_clob() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[MarketReward, ...]:
        client = await _make_secure_client()
        try:
            _install_secure_public_clob(
                client,
                _routed_handler(
                    captured,
                    {("GET", f"/rewards/markets/{_CONDITION_ID}"): _MARKET_REWARDS_PAGE},
                ),
            )
            page = await client.list_market_rewards(condition_id=_CONDITION_ID).first_page()
            return page.items
        finally:
            await client.close()

    items = asyncio.run(run())
    assert len(items) == 1
    request = captured[0]
    assert request.headers.get("POLY_SIGNATURE") is None
    assert request.headers.get("POLY_API_KEY") is None


def test_async_secure_list_user_earnings_for_day_rejects_bad_date() -> None:
    async def run() -> None:
        client = await _make_secure_client()
        try:
            await client.list_user_earnings_for_day(date="2026/04/16").first_page()
        finally:
            await client.close()

    with pytest.raises(UserInputError):
        asyncio.run(run())


def test_async_order_heartbeat_rotation_and_explicit_mismatch_recovery() -> None:
    from polymarket import OrderHeartbeatMismatchError

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if len(captured) == 2:
            return httpx.Response(
                400,
                json={"error_msg": "Invalid Heartbeat ID", "heartbeat_id": "expected-id"},
                request=request,
            )
        return httpx.Response(200, json={"heartbeat_id": "next-id"}, request=request)

    async def run() -> None:
        client = await _make_secure_client()
        try:
            _install_secure_clob(client, httpx.MockTransport(handler))
            assert (await client.send_order_heartbeat()).heartbeat_id == "next-id"
            with pytest.raises(OrderHeartbeatMismatchError) as error:
                await client.send_order_heartbeat(heartbeat_id="stale-id")
            assert len(captured) == 2
            assert (
                await client.send_order_heartbeat(heartbeat_id=error.value.heartbeat_id)
            ).heartbeat_id == "next-id"
        finally:
            await client.close()

    asyncio.run(run())
    assert [request.content for request in captured] == [
        b'{"heartbeat_id":""}',
        b'{"heartbeat_id":"stale-id"}',
        b'{"heartbeat_id":"expected-id"}',
    ]
    assert all(request.headers.get("POLY_SIGNATURE") for request in captured)
