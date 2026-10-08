# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from typing import Any, Literal

import httpx
import pytest
from data_v2_samples import position_payload, sample

from polymarket import (
    ApiKeyCreds,
    AsyncPublicClient,
    AsyncSecureClient,
    ProtocolVersion,
    PublicClient,
    SecureClient,
)
from polymarket._internal.pagination import encode_keyset_cursor
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import UserInputError
from polymarket.pagination import AsyncPaginator

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
WALLET = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
CREDS = ApiKeyCreds(key="test", passphrase="test", secret="dGVzdA==")
CONDITION = "0x" + "ab" * 32
COMBO = "0x03" + "ab" * 30


@pytest.mark.parametrize("mode", ["public", "secure", "async_public", "async_secure"])
@pytest.mark.parametrize("version", [None, "v1", "v2", ProtocolVersion.V1, ProtocolVersion.V2])
def test_event_protocol_filter_and_cursor_binding(
    mode: str, version: ProtocolVersion | Literal["v1", "v2"] | None
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "events": [{"id": "event-1", "title": "Protocol-filtered event"}],
                "next_cursor": None if "after_cursor" in request.url.params else "server-next",
            },
        )

    async def run() -> None:
        client: PublicClient | SecureClient | AsyncPublicClient | AsyncSecureClient
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
        asynchronous = isinstance(client, AsyncPublicClient | AsyncSecureClient)
        http: Any = (
            httpx.AsyncClient(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            )
            if asynchronous
            else httpx.Client(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            )
        )
        if isinstance(client, AsyncSecureClient):
            await client._ctx.gamma.close()
            client._ctx = dataclasses.replace(
                client._ctx, gamma=AsyncTransport(base_url="https://example.test", client=http)
            )
        elif isinstance(client, AsyncPublicClient):
            await client._ctx.gamma.close()
            client._ctx = dataclasses.replace(
                client._ctx, gamma=AsyncTransport(base_url="https://example.test", client=http)
            )
        elif isinstance(client, SecureClient):
            client._ctx.gamma.close()
            client._ctx = dataclasses.replace(
                client._ctx, gamma=SyncTransport(base_url="https://example.test", client=http)
            )
        else:
            client._ctx.gamma.close()
            client._ctx = dataclasses.replace(
                client._ctx, gamma=SyncTransport(base_url="https://example.test", client=http)
            )
        try:
            if version is None:
                for invalid in ("v3", "V2", "", 2, True, ["v2"], ("v1", "v2")):
                    with pytest.raises(UserInputError, match="version must be one of: v1, v2"):
                        client.list_events(version=invalid)  # type: ignore[arg-type]
                assert not captured

            paginator = client.list_events(version=version, page_size=5)
            first = (
                await paginator.first_page()
                if isinstance(paginator, AsyncPaginator)
                else paginator.first_page()
            )
            assert first.next_cursor is not None
            # An omitted filter must still resume a cursor created with the old query.
            cursor = (
                encode_keyset_cursor(
                    service="gamma",
                    path="/events/keyset",
                    base_params={"closed": False},
                    server_cursor="server-next",
                )
                if version is None
                else first.next_cursor
            )
            same_version = (
                None
                if version is None
                else (ProtocolVersion.V1 if version == "v1" else ProtocolVersion.V2)
            )
            replay = client.list_events(version=same_version, page_size=5).from_cursor(cursor)
            second = (
                await replay.first_page()
                if isinstance(replay, AsyncPaginator)
                else replay.first_page()
            )
            assert first.items[0].id == second.items[0].id == "event-1"
            assert not second.has_more

            for changed in (None, ProtocolVersion.V1, ProtocolVersion.V2):
                if changed == same_version:
                    continue
                other = client.list_events(version=changed, page_size=5).from_cursor(cursor)
                with pytest.raises(UserInputError, match="different query parameters"):
                    if isinstance(other, AsyncPaginator):
                        await other.first_page()
                    else:
                        other.first_page()
            assert len(captured) == 2

            if isinstance(paginator, AsyncPaginator):
                pages = [page async for page in paginator]
            else:
                pages = list(paginator)
            assert len(pages) == 2
        finally:
            if isinstance(client, AsyncPublicClient | AsyncSecureClient):
                await client.close()
                await http.aclose()
            else:
                client.close()
                http.close()

    asyncio.run(run())
    assert len(captured) == 4
    expected = {"closed": "false", "limit": "5"}
    if version is not None:
        expected["version"] = version
    assert [dict(request.url.params) for request in captured] == [
        expected,
        {**expected, "after_cursor": "server-next"},
        expected,
        {**expected, "after_cursor": "server-next"},
    ]
    assert all(request.url.path == "/events/keyset" for request in captured)


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
            {"condition_id": CONDITION},
        ),
        ("list_positions", {}, {}),
        ("list_positions", {"title": " BiTcOiN%_ "}, {"title": " BiTcOiN%_ "}),
        ("list_positions", {"title": " " * 201}, {}),
        (
            "list_combo_positions",
            {"condition_id": COMBO, "status": ["RESOLVED_WIN", "RESOLVED_LOSS"]},
            {"condition_id": COMBO, "status": "RESOLVED_WIN,RESOLVED_LOSS"},
        ),
        ("list_combo_positions", {"updated_after": 0}, {"updated_after": "0"}),
        ("list_combo_positions", {"updated_before": 0}, {"updated_before": "0"}),
        (
            "list_combo_positions",
            {"updated_after": 0, "updated_before": 0},
            {"updated_after": "0", "updated_before": "0"},
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
        rows = []
        # Positions without native activity have SQL NULL timestamps and wire value 0.
        # The backend excludes them whenever a time bound is supplied.
        if (
            method == "list_positions"
            and "start" not in request.url.params
            and "end" not in request.url.params
        ):
            rows = [position_payload(last_event_at=0)]
        return httpx.Response(
            200, json={"data": rows, "pagination": {"has_more": True, "next_cursor": "server-next"}}
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
            second = await replay.first_page() if asynchronous else replay.first_page()
            if method == "list_positions":
                for page in (first, second):
                    assert len(page.items) == 1
                    assert page.items[0].last_event_at is None
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
