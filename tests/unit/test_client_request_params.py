# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from typing import Any

import httpx
import pytest
from data_v2_samples import sample

from polymarket import ApiKeyCreds, AsyncPublicClient, AsyncSecureClient, PublicClient, SecureClient
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import UserInputError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
WALLET = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
CREDS = ApiKeyCreds(key="test", passphrase="test", secret="dGVzdA==")
CONDITION = "0x" + "ab" * 32
COMBO = "0x03" + "ab" * 30


@pytest.mark.parametrize("mode", ["public", "secure", "async_public", "async_secure"])
@pytest.mark.parametrize(
    "method,kwargs,query",
    [
        (
            "list_trades",
            {"condition_id": [CONDITION], "side": "BUY", "full_history": True},
            {"condition_id": CONDITION, "side": "BUY", "start": "1"},
        ),
        (
            "list_activity",
            {"event_id": [7, 8], "activity_types": ["TRADE", "TIP"], "full_history": True},
            {
                "event_id": "7,8",
                "type": "TRADE,TIP",
                "exclude_deposits_withdrawals": "false",
                "start": "1",
            },
        ),
        ("list_combo_activity", {"condition_id": COMBO}, {"condition_id": COMBO}),
        (
            "list_positions",
            {"condition_id": CONDITION, "full_history": True},
            {"condition_id": CONDITION, "start": "1"},
        ),
        (
            "list_combo_positions",
            {"condition_id": COMBO, "status": ["RESOLVED_WIN", "RESOLVED_LOSS"]},
            {"condition_id": COMBO, "status": "RESOLVED_WIN,RESOLVED_LOSS"},
        ),
    ],
)
def test_feed_queries_cursor_replay_and_wallet_binding(
    mode: str,
    method: str,
    kwargs: dict[str, Any],
    query: dict[str, str],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, json={"data": [], "pagination": {"has_more": True, "next_cursor": "server-next"}}
        )

    async def run() -> None:
        client: Any
        if mode == "public":
            client = PublicClient()
        elif mode == "secure":
            client = SecureClient._create(
                private_key=PRIVATE_KEY,
                wallet=WALLET,
                credentials=CREDS,
                validate_credentials=False,
            )
        elif mode == "async_public":
            client = AsyncPublicClient()
        else:
            client = await AsyncSecureClient._create(
                private_key=PRIVATE_KEY,
                wallet=WALLET,
                credentials=CREDS,
                validate_credentials=False,
            )
        asynchronous = mode.startswith("async")
        http: Any = (
            httpx.AsyncClient(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            )
            if asynchronous
            else httpx.Client(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            )
        )
        transport = (
            AsyncTransport(base_url="https://example.test", client=http)
            if asynchronous
            else SyncTransport(base_url="https://example.test", client=http)
        )
        if asynchronous:
            await client._ctx.data.close()
        else:
            client._ctx.data.close()
        client._ctx = dataclasses.replace(client._ctx, data=transport)
        options = {**kwargs, **({"user": WALLET} if "secure" not in mode else {})}
        try:
            paginator = getattr(client, method)(**options, page_size=5)
            first = await paginator.first_page() if asynchronous else paginator.first_page()
            replay = paginator.from_cursor(first.next_cursor)
            if asynchronous:
                await replay.first_page()
            else:
                replay.first_page()
            other = getattr(client, method)(
                **{**options, "user": "0x" + "cd" * 20}, page_size=5
            ).from_cursor(first.next_cursor)
            with pytest.raises(UserInputError):
                if asynchronous:
                    await other.first_page()
                else:
                    other.first_page()
        finally:
            if asynchronous:
                await client.close()
                await http.aclose()
            else:
                client.close()
                http.close()

    asyncio.run(run())
    assert len(captured) == 2
    expected = {**query, "user": WALLET, "limit": "5"}
    assert dict(captured[0].url.params) == expected
    assert dict(captured[1].url.params) == {**expected, "cursor": "server-next"}
    assert captured[0].url.path.startswith("/v2/")


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "method,fixture",
    [
        ("get_portfolio_value", "value"),
        ("get_user_stats", "user-stats"),
        ("get_user_pnl", "user-pnl"),
        ("get_user_volume", "user-volume"),
        ("get_trader_leaderboard_standing", "leaderboard_standing"),
    ],
)
def test_secure_metrics_bind_wallet(mode: str, method: str, fixture: str) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": sample(fixture)})

    async def run() -> None:
        if mode == "sync":
            with (
                SecureClient._create(
                    private_key=PRIVATE_KEY,
                    wallet=WALLET,
                    credentials=CREDS,
                    validate_credentials=False,
                ) as client,
                httpx.Client(
                    base_url="https://example.test", transport=httpx.MockTransport(handler)
                ) as http,
            ):
                client._ctx.data.close()
                client._ctx = dataclasses.replace(
                    client._ctx, data=SyncTransport(base_url="https://example.test", client=http)
                )
                getattr(client, method)()
        else:
            async_client = await AsyncSecureClient._create(
                private_key=PRIVATE_KEY,
                wallet=WALLET,
                credentials=CREDS,
                validate_credentials=False,
            )
            async with (
                async_client,
                httpx.AsyncClient(
                    base_url="https://example.test", transport=httpx.MockTransport(handler)
                ) as async_http,
            ):
                await async_client._ctx.data.close()
                async_client._ctx = dataclasses.replace(
                    async_client._ctx,
                    data=AsyncTransport(base_url="https://example.test", client=async_http),
                )
                await getattr(async_client, method)()

    asyncio.run(run())
    assert dict(captured[0].url.params) == {"user": WALLET}
