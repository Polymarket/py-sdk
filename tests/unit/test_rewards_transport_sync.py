# pyright: reportPrivateUsage=false
import dataclasses
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx

from polymarket import (
    ApiKeyCreds,
    PublicClient,
    SecureClient,
)
from polymarket._internal.context import SyncSecureClientContext
from polymarket.clients._transport import SyncTransport
from polymarket.models.clob.rewards import (
    CurrentReward,
    MarketReward,
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


def _install_sync_clob(client: PublicClient | SecureClient, handler: httpx.MockTransport) -> None:
    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=handler),
    )
    client._ctx = cast(SyncSecureClientContext, dataclasses.replace(client._ctx, clob=transport))


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


class TestListCurrentRewards:
    def test_public_routes_to_clob(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(
                client,
                _routed_handler(
                    captured, {("GET", "/rewards/markets/current"): _CURRENT_REWARDS_PAGE}
                ),
            )
            page = client.list_current_rewards().first_page()

        assert len(page.items) == 1
        assert isinstance(page.items[0], CurrentReward)
        assert captured[0].method == "GET"
        assert urlparse(str(captured[0].url)).path == "/rewards/markets/current"
        assert captured[0].headers.get("POLY_SIGNATURE") is None

    def test_public_passes_sponsored_filter(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(
                client,
                _routed_handler(
                    captured, {("GET", "/rewards/markets/current"): _CURRENT_REWARDS_PAGE}
                ),
            )
            client.list_current_rewards(sponsored=True).first_page()

        qs = parse_qs(urlparse(str(captured[0].url)).query)
        assert qs.get("sponsored") == ["true"]

    def test_secure_uses_unsigned_clob_not_secure_clob(self) -> None:
        captured: list[httpx.Request] = []
        with SecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        ) as client:
            _install_sync_clob(
                client,
                _routed_handler(
                    captured, {("GET", "/rewards/markets/current"): _CURRENT_REWARDS_PAGE}
                ),
            )
            page = client.list_current_rewards().first_page()

        assert len(page.items) == 1
        assert captured[0].headers.get("POLY_SIGNATURE") is None


class TestListMarketRewards:
    def test_public_routes_with_condition_id_in_path(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            _install_sync_clob(
                client,
                _routed_handler(
                    captured,
                    {("GET", f"/rewards/markets/{_CONDITION_ID}"): _MARKET_REWARDS_PAGE},
                ),
            )
            page = client.list_market_rewards(condition_id=_CONDITION_ID).first_page()

        assert len(page.items) == 1
        assert isinstance(page.items[0], MarketReward)
        assert urlparse(str(captured[0].url)).path == f"/rewards/markets/{_CONDITION_ID}"

    def test_secure_uses_unsigned_clob_not_secure_clob(self) -> None:
        captured: list[httpx.Request] = []
        with SecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        ) as client:
            _install_sync_clob(
                client,
                _routed_handler(
                    captured,
                    {("GET", f"/rewards/markets/{_CONDITION_ID}"): _MARKET_REWARDS_PAGE},
                ),
            )
            page = client.list_market_rewards(condition_id=_CONDITION_ID).first_page()

        assert len(page.items) == 1
        assert captured[0].headers.get("POLY_SIGNATURE") is None


_DISCOVERY_MARKET: dict[str, Any] = {
    "condition_id": _CONDITION_ID,
    "market_id": "12",
    "event_id": "1",
    "market_slug": "market",
    "event_slug": "event",
    "question": "Question?",
    "image": "",
    "market_competitiveness": 0.4,
    "rewards_config": [],
    "rewards_max_spread": 3,
    "rewards_min_size": 10,
    "spread": 0.1,
    "tokens": [],
    "group_item_title": "",
    "volume_24hr": 100,
    "created_at": "2026-10-07T00:00:00Z",
    "one_day_price_change": -0.2,
    "end_date": "",
}


def test_sync_reward_market_pagination_retains_filters() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "data": [_DISCOVERY_MARKET],
                "next_cursor": "MQ==" if len(captured) == 1 else "LTE=",
            },
            request=request,
        )

    with PublicClient() as client:
        _install_sync_clob(client, httpx.MockTransport(handler))
        pages = list(
            client.list_reward_markets(
                query="sports",
                tag_slugs=("sports", "politics"),
                exclude_tag_slugs=("5m",),
                event_ids=(1, 2),
                order_by="volume_24hr",
                sort_direction="DESC",
                page_size=1,
            )
        )
    assert len(pages) == 2
    assert len(captured) == 2
    for request in captured:
        params = parse_qs(urlparse(str(request.url)).query)
        assert params["tag_slug"] == ["sports", "politics"]
        assert params["exclude_tag_slug"] == ["5m"]
        assert params["event_id"] == ["1", "2"]
        assert params["position"] == ["DESC"]
        assert params["q"] == ["sports"]
        assert request.headers.get("POLY_SIGNATURE") is None
    assert parse_qs(urlparse(str(captured[1].url)).query)["next_cursor"] == ["MQ=="]
