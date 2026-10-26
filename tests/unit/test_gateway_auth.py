"""Synthetic protocol tests: no live wallet, credentials, or upstream dependency."""

# pyright: reportPrivateUsage=false
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from unittest.mock import Mock

import httpx
import pytest
import respx
from _gateway_auth_helpers import (
    CHALLENGE,
    GATEWAY,
    LEGACY,
    PRIVATE_KEY,
    SIGNER,
    credentials,
    response,
)
from respx.models import Call

from polymarket import (
    AsyncPublicClient,
    AsyncSecureClient,
    BearerCredentials,
    PublicClient,
    SecureClient,
)
from polymarket._internal.gateway_session import AsyncGatewaySession, SyncGatewaySession
from polymarket._internal.socket_auth import SocketAuthentication
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import RequestRejectedError, TransportError, UserInputError


@pytest.mark.parametrize("async_client", [False, True])
def test_public_login_and_migration_wire_contract(
    async_client: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    pair = credentials()
    monkeypatch.setattr("polymarket._internal.gateway_auth.time.time", lambda: 1234567890)
    with respx.mock as router:
        challenge = router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        login = router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(pair))
        migration = router.post(GATEWAY + "/v1/auth/migrate").respond(200, json=response(pair))

        async def run() -> None:
            async with AsyncPublicClient() as client:
                assert (
                    await client.login(
                        signer=SIGNER,
                        wallet=SIGNER.address,
                        verification_token="synthetic-verification",
                    )
                    == pair
                )
                assert (
                    await client.migrate_credentials(
                        credentials=LEGACY, signer=SIGNER.address, wallet=SIGNER.address
                    )
                    == pair
                )

        if async_client:
            asyncio.run(run())
        else:
            with PublicClient() as client:
                assert (
                    client.login(
                        signer=SIGNER,
                        wallet=SIGNER.address,
                        verification_token="synthetic-verification",
                    )
                    == pair
                )
                assert (
                    client.migrate_credentials(
                        credentials=LEGACY, signer=SIGNER.address, wallet=SIGNER.address
                    )
                    == pair
                )
        assert json.loads(cast(Call, challenge.calls[0]).request.content) == {
            "signer": SIGNER.address,
            "wallet": SIGNER.address,
            "verification_token": "synthetic-verification",
        }
        login_body = json.loads(cast(Call, login.calls[0]).request.content)
        assert set(login_body) == {"ownership"}
        assert set(login_body["ownership"]) == {"challenge_id", "signature"}
        proof = base64.urlsafe_b64encode(
            hmac.new(
                base64.b64decode(LEGACY.secret), b"1234567890GET/auth/api-keys", hashlib.sha256
            ).digest()
        ).decode()
        assert json.loads(cast(Call, migration.calls[0]).request.content) == {
            "signer": SIGNER.address,
            "wallet": SIGNER.address,
            "timestamp": "1234567890",
            "clob_api_key": LEGACY.key,
            "clob_passphrase": LEGACY.passphrase,
            "clob_signature": proof,
        }
        assert LEGACY.secret.encode() not in cast(Call, migration.calls[0]).request.content


@pytest.mark.parametrize("async_client", [False, True])
@pytest.mark.parametrize("kind", ["login", "restore", "migrate"])
def test_secure_client_creation_and_logout(async_client: bool, kind: str) -> None:
    pair = credentials()
    supplied = (
        None
        if kind == "login"
        else (
            LEGACY
            if kind == "migrate"
            else {"access_token": pair.access_token, "refresh_token": pair.refresh_token}
        )
    )
    callback = Mock()
    with respx.mock as router:
        challenge = router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        login = router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(pair))
        migration = router.post(GATEWAY + "/v1/auth/migrate").respond(200, json=response(pair))
        router.post(GATEWAY + "/v1/auth/refresh").respond(200, json=response(pair))
        logout = router.post(GATEWAY + "/v1/auth/logout").respond(204)
        keys = router.get(GATEWAY + "/auth/api-keys").respond(
            200, json={"apiKeys": ["synthetic-key"]}
        )

        async def run() -> None:
            client = await AsyncSecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                credentials=supplied,
                on_credentials_changed=callback,
            )
            session = client._ctx.session
            assert client.credentials == pair
            assert await client.fetch_api_keys() == ("synthetic-key",)
            public = await client.end_authentication()
            assert session is not None and session._closed and session._timer is None
            await public.close()
            with pytest.raises(RuntimeError):
                await client.fetch_api_keys()

        if async_client:
            asyncio.run(run())
        else:
            client = SecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                credentials=supplied,
                on_credentials_changed=callback,
            )
            session = client._ctx.session
            assert client.credentials == pair
            assert client.fetch_api_keys() == ("synthetic-key",)
            client.end_authentication().close()
            assert (
                session is not None
                and session._worker is not None
                and not session._worker.is_alive()
            )
            with pytest.raises(RuntimeError):
                client.fetch_api_keys()
        assert challenge.call_count == login.call_count == (1 if kind == "login" else 0)
        assert migration.call_count == (1 if kind == "migrate" else 0)
        assert cast(Call, logout.calls[0]).request.content == b""
        assert (
            cast(Call, logout.calls[0]).request.headers["Authorization"]
            == "Bearer " + pair.access_token
        )
        assert (
            cast(Call, keys.calls[0]).request.headers["Authorization"]
            == "Bearer " + pair.access_token
        )
        assert not any(
            name.startswith("poly_") for name in cast(Call, keys.calls[0]).request.headers
        )
        if kind == "restore":
            callback.assert_called_once_with(pair)
        else:
            callback.assert_not_called()


@pytest.mark.parametrize("async_client", [False, True])
def test_rejected_migration_does_not_callback_or_replace_credentials(
    async_client: bool, caplog: pytest.LogCaptureFixture
) -> None:
    callback = Mock()
    saved = LEGACY.model_dump()
    with respx.mock as router:
        router.post(GATEWAY + "/v1/auth/migrate").respond(
            401, json={"code": "invalid_credentials", "error": LEGACY.secret}
        )

        async def run() -> None:
            await AsyncSecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                credentials=LEGACY,
                on_credentials_changed=callback,
            )

        with caplog.at_level(logging.DEBUG), pytest.raises(RequestRejectedError) as rejected:
            if async_client:
                asyncio.run(run())
            else:
                SecureClient.create(
                    private_key=PRIVATE_KEY,
                    wallet=SIGNER.address,
                    credentials=LEGACY,
                    on_credentials_changed=callback,
                )
        assert rejected.value.code == "invalid_credentials"
        assert LEGACY.secret not in str(rejected.value) + caplog.text
        assert LEGACY.model_dump() == saved
        callback.assert_not_called()


@pytest.mark.parametrize("async_client", [False, True])
@pytest.mark.parametrize(
    "code,expected_refresh", [("expired_access_token", 1), ("invalid_access_token", 0)]
)
def test_http_retry_is_once_and_preserves_operation(
    async_client: bool, code: str, expected_refresh: int
) -> None:
    before, after = credentials(), credentials(tag="two", refresh="rotated-refresh")
    bodies: list[httpx.Request] = []
    refreshes: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/refresh":
            refreshes.append(request)
            return httpx.Response(200, json=response(after))
        bodies.append(request)
        return httpx.Response(401, json={"code": code})

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), base_url=GATEWAY
        ) as http:
            auth = AsyncGatewaySession(before, AsyncTransport(base_url=GATEWAY, client=http))
            transport = AsyncTransport(base_url=GATEWAY, client=http, session=auth)
            try:
                with pytest.raises(RequestRejectedError):
                    await transport.post_json(
                        "/order", json={"signed": "synthetic-order"}, params={"mode": "test"}
                    )
            finally:
                await auth.close()

    if async_client:
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handle), base_url=GATEWAY) as http:
            auth = SyncGatewaySession(before, SyncTransport(base_url=GATEWAY, client=http))
            transport = SyncTransport(base_url=GATEWAY, client=http, session=auth)
            try:
                with pytest.raises(RequestRejectedError):
                    transport.post_json(
                        "/order", json={"signed": "synthetic-order"}, params={"mode": "test"}
                    )
            finally:
                auth.close()
    assert len(refreshes) == expected_refresh
    assert len(bodies) == expected_refresh + 1
    assert all(
        request.method == "POST"
        and request.url.query == b"mode=test"
        and request.content == b'{"signed":"synthetic-order"}'
        for request in bodies
    )
    if expected_refresh:
        assert bodies[-1].headers["Authorization"] == "Bearer " + after.access_token
        assert json.loads(refreshes[0].content) == {"refresh_token": before.refresh_token}


def test_async_timer_http_socket_single_flight_and_waiter_cancellation() -> None:
    async def run() -> None:
        before, after = credentials(), credentials(tag="two", refresh="rotated-refresh")
        entered, release = asyncio.Event(), asyncio.Event()
        refresh_count = 0

        async def handle(request: httpx.Request) -> httpx.Response:
            nonlocal refresh_count
            refresh_count += 1
            entered.set()
            await release.wait()
            return httpx.Response(200, json=response(after))

        callbacks: list[BearerCredentials] = []

        async def callback(value: BearerCredentials) -> None:
            callbacks.append(value)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), base_url=GATEWAY
        ) as http:
            auth = AsyncGatewaySession(
                before, AsyncTransport(base_url=GATEWAY, client=http), callback
            )
            sent: list[dict[str, object]] = []
            socket: SocketAuthentication

            async def send(frame: dict[str, object]) -> bool:
                sent.append(frame)
                socket.message({"op": "authed", "rid": frame["rid"]})
                return True

            async def expire() -> None:
                raise AssertionError("Unexpected expiry")

            socket = SocketAuthentication(
                session=auth, protocol="polybolt", send=send, expire=expire
            )
            await socket.initial()
            cancelled = asyncio.create_task(auth.refresh(before.access_token))
            await entered.wait()
            consumers = [asyncio.create_task(auth.refresh(before.access_token)) for _ in range(3)]
            auth._scheduled()
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            release.set()
            assert all(value == after for value in await asyncio.gather(*consumers))
            await asyncio.gather(*tuple(socket._tasks))
            assert refresh_count == 1 and callbacks == [after]
            assert len(sent) == 2 and sent[0]["rid"] != sent[1]["rid"]
            assert sent[-1]["auth"] == {"accessToken": after.access_token}
            assert "refresh" not in json.dumps(sent)
            await socket.close()
            await auth.close()
            assert not socket._tasks and socket._deadline is None and auth._timer is None

    asyncio.run(run())


def test_sync_concurrent_refresh_and_close_waits_for_inflight() -> None:
    before, after = credentials(), credentials(tag="two")
    entered, release = threading.Event(), threading.Event()
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, json=response(after))

    callback = Mock()
    with httpx.Client(transport=httpx.MockTransport(handle), base_url=GATEWAY) as http:
        session = SyncGatewaySession(before, SyncTransport(base_url=GATEWAY, client=http), callback)
        with ThreadPoolExecutor(max_workers=3) as executor:
            first = executor.submit(session.refresh, before.access_token)
            assert entered.wait(5)
            second = executor.submit(session.refresh, before.access_token)
            closing = executor.submit(session.close)
            assert session._stop.wait(5)
            release.set()
            for future in (first, second):
                with pytest.raises(RuntimeError, match="closed"):
                    future.result(timeout=5)
            closing.result(timeout=5)
        assert calls == 1 and session.credentials == before
        callback.assert_not_called()


@pytest.mark.parametrize("async_callback", [False, True])
@pytest.mark.parametrize("async_client", [False, True])
def test_restore_refreshes_pair_and_callback_failure_is_redacted(
    async_callback: bool, async_client: bool, caplog: pytest.LogCaptureFixture
) -> None:
    before, after = (
        credentials(expiry=time.time() - 10),
        credentials(tag="two", refresh="rotated-refresh"),
    )
    observed: list[BearerCredentials] = []

    def callback(value: BearerCredentials) -> None:
        observed.append(value)
        raise ValueError(value.refresh_token)

    async def async_cb(value: BearerCredentials) -> None:
        callback(value)

    with respx.mock as router, caplog.at_level(logging.WARNING):
        route = router.post(GATEWAY + "/v1/auth/refresh").respond(200, json=response(after))

        async def run() -> None:
            async with await AsyncSecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                credentials=before,
                on_credentials_changed=async_cb if async_callback else callback,
            ) as client:
                assert client.credentials == after

        if async_client:
            asyncio.run(run())
        else:
            with SecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                credentials=before,
                on_credentials_changed=async_cb if async_callback else callback,
            ) as client:
                assert client.credentials == after
        assert route.call_count == 1 and observed == [after]
        assert after.refresh_token not in caplog.text


@pytest.mark.parametrize("protocol", ["clob", "combos", "polybolt"])
def test_socket_rejected_renewal_preserves_deadline_and_requires_matching_ack(
    protocol: Any,
) -> None:
    async def run() -> None:
        before, after = credentials(), credentials(tag="two")
        auth = AsyncGatewaySession(before, AsyncTransport(base_url=GATEWAY))
        sent: list[dict[str, object]] = []
        expired: list[bool] = []
        reject = False
        socket: SocketAuthentication

        async def send(frame: dict[str, object]) -> bool:
            sent.append(frame)
            if frame.get("type") == "user":
                return True
            if protocol == "polybolt":
                socket.message({"op": "authed", "rid": "wrong"})
                assert socket._pending is not None and not socket._pending.done()
                socket.message(
                    {
                        "op": "error" if reject else "authed",
                        "code": "auth_invalid",
                        "rid": frame["rid"],
                    }
                )
            else:
                socket.message({"type": "auth", "success": not reject, "error": after.access_token})
            return True

        async def expire() -> None:
            expired.append(True)

        socket = SocketAuthentication(session=auth, protocol=protocol, send=send, expire=expire)
        await socket.initial(
            {"type": "user", "markets": ["synthetic-market"]} if protocol == "clob" else None
        )
        deadline = socket._deadline
        reject = True
        with pytest.raises(RequestRejectedError) as error:
            await socket._renew(after)
        assert after.access_token not in str(error.value)
        assert socket._deadline is deadline and socket._accepted == before
        with pytest.raises(RequestRejectedError, match="identity"):
            await socket._renew(credentials(client_id="another-client"))
        socket._expired()
        await asyncio.gather(*tuple(socket._tasks))
        assert expired == [True]
        assert all(
            "secret" not in json.dumps(frame) and "refreshToken" not in json.dumps(frame)
            for frame in sent
        )
        await socket.close()
        await auth.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad",
    [
        {"accessToken": "x", "refreshToken": "r", "secret": "bad"},
        {"key": "k"},
        {"access_token": 3, "refresh_token": "r"},
    ],
)
def test_invalid_credentials_are_rejected_without_network(bad: object) -> None:
    with respx.mock, pytest.raises(UserInputError):
        SecureClient.create(private_key=PRIVATE_KEY, wallet=SIGNER.address, credentials=bad)


@pytest.mark.parametrize("async_client", [False, True])
def test_transient_refresh_retries_are_bounded(async_client: bool) -> None:
    before, after = credentials(), credentials(tag="two")
    attempts: list[httpx.Request] = []
    callback = Mock()

    def handle(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(503, json={"code": "identity_provider_unavailable"})

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), base_url=GATEWAY
        ) as http:
            session = AsyncGatewaySession(
                before, AsyncTransport(base_url=GATEWAY, client=http), callback
            )
            with pytest.raises(RequestRejectedError):
                await session.refresh(before.access_token)
            with pytest.raises(RequestRejectedError):
                await session.ensure_valid()
            assert session.credentials == before and session._timer is None
            await session.close()

    if async_client:
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handle), base_url=GATEWAY) as http:
            session = SyncGatewaySession(
                before, SyncTransport(base_url=GATEWAY, client=http), callback
            )
            with pytest.raises(RequestRejectedError):
                session.refresh(before.access_token)
            with pytest.raises(RequestRejectedError):
                session.ensure_valid()
            assert session.credentials != after and session.credentials == before
            session.close()
    assert len(attempts) == 3
    callback.assert_not_called()


@pytest.mark.parametrize("async_client", [False, True])
def test_http_expiry_uses_an_already_newer_pair(async_client: bool) -> None:
    before, after = credentials(), credentials(tag="two")
    attempts, refreshes = 0, 0

    async def run() -> None:
        session: AsyncGatewaySession

        async def handle(request: httpx.Request) -> httpx.Response:
            nonlocal attempts, refreshes
            if request.url.path == "/v1/auth/refresh":
                refreshes += 1
                return httpx.Response(200, json=response(after))
            attempts += 1
            if attempts == 1:
                await session.refresh(before.access_token)
                return httpx.Response(401, json={"code": "expired_access_token"})
            assert request.headers["Authorization"] == "Bearer " + after.access_token
            return httpx.Response(200, json={"ok": True})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), base_url=GATEWAY
        ) as http:
            session = AsyncGatewaySession(before, AsyncTransport(base_url=GATEWAY, client=http))
            transport = AsyncTransport(base_url=GATEWAY, client=http, session=session)
            assert await transport.get_json("/private") == {"ok": True}
            await session.close()

    if async_client:
        asyncio.run(run())
    else:
        session: SyncGatewaySession

        def handle(request: httpx.Request) -> httpx.Response:
            nonlocal attempts, refreshes
            if request.url.path == "/v1/auth/refresh":
                refreshes += 1
                return httpx.Response(200, json=response(after))
            attempts += 1
            if attempts == 1:
                session.refresh(before.access_token)
                return httpx.Response(401, json={"code": "expired_access_token"})
            assert request.headers["Authorization"] == "Bearer " + after.access_token
            return httpx.Response(200, json={"ok": True})

        with httpx.Client(transport=httpx.MockTransport(handle), base_url=GATEWAY) as http:
            session = SyncGatewaySession(before, SyncTransport(base_url=GATEWAY, client=http))
            transport = SyncTransport(base_url=GATEWAY, client=http, session=session)
            assert transport.get_json("/private") == {"ok": True}
            session.close()
    assert attempts == 2 and refreshes == 1


def test_async_late_refresh_cannot_revive_closed_session() -> None:
    async def run() -> None:
        before, after = credentials(), credentials(tag="two")
        entered = asyncio.Event()

        async def handle(request: httpx.Request) -> httpx.Response:
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                # A dependency can finish despite cancellation. Adoption must still fail.
                return httpx.Response(200, json=response(after))
            raise AssertionError("The synthetic operation must be cancelled")

        callback = Mock()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), base_url=GATEWAY
        ) as http:
            session = AsyncGatewaySession(
                before, AsyncTransport(base_url=GATEWAY, client=http), callback
            )
            task = asyncio.create_task(session.refresh(before.access_token))
            await entered.wait()
            await session.close()
            with pytest.raises(RuntimeError, match="closed"):
                await task
            assert session.credentials == before and session._timer is None
            callback.assert_not_called()

    asyncio.run(run())


def test_sync_proactive_timer_and_async_callback_can_close_session() -> None:
    before, after = credentials(), credentials(tag="two")
    done = threading.Event()
    session: SyncGatewaySession

    async def callback(value: BearerCredentials) -> None:
        assert value == after
        session.close()
        done.set()

    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response(after))),
        base_url=GATEWAY,
    ) as http:
        session = SyncGatewaySession(before, SyncTransport(base_url=GATEWAY, client=http), callback)
        session._deadline = time.monotonic()
        session.start()
        assert done.wait(5)
        session.close()
        assert session._worker is not None and not session._worker.is_alive()
        assert session.credentials == after and session._stop.is_set()


def test_public_user_subscription_renews_and_reconnects_without_l2_or_wire_leaks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from dataclasses import replace

    from websockets.asyncio.server import ServerConnection, serve

    from polymarket._internal.environment import PRODUCTION_CONFIG, create_environment
    from polymarket.streams import UserSpec

    async def run() -> None:
        before, after = credentials(), credentials(tag="two")
        frames: list[dict[str, Any]] = []
        subscribed, renewed, reconnected = asyncio.Event(), asyncio.Event(), asyncio.Event()
        connections = 0

        async def handler(ws: ServerConnection) -> None:
            nonlocal connections
            connections += 1
            connection = connections
            async for raw in ws:
                if raw == "PING":
                    await ws.send("PONG")
                    continue
                frame = json.loads(raw)
                frames.append(frame)
                if frame.get("type") == "user":
                    if connection == 1:
                        subscribed.set()
                    else:
                        reconnected.set()
                elif frame.get("type") == "auth":
                    await ws.send(json.dumps({"type": "auth", "success": True}))
                    renewed.set()
                    await ws.close(code=1013, reason="authentication unavailable, please retry")

        server = await serve(
            handler, host="127.0.0.1", port=0, logger=logging.Logger("synthetic-server", level=100)
        )
        port = next(iter(server.sockets)).getsockname()[1]
        environment = create_environment(
            name="synthetic",
            config=replace(PRODUCTION_CONFIG, clob_user_ws_url=f"ws://127.0.0.1:{port}"),
        )
        try:
            with respx.mock as router:
                router.post(GATEWAY + "/v1/auth/refresh").mock(
                    side_effect=[
                        httpx.Response(200, json=response(before)),
                        httpx.Response(200, json=response(after)),
                    ]
                )
                async with await AsyncSecureClient.create(
                    private_key=PRIVATE_KEY,
                    wallet=SIGNER.address,
                    credentials=before,
                    environment=environment,
                ) as client:
                    handle = await client.subscribe(UserSpec(markets=["synthetic-market"]))
                    await asyncio.wait_for(subscribed.wait(), 5)
                    session = client._ctx.session
                    assert session is not None
                    await session.refresh(before.access_token)
                    await asyncio.wait_for(renewed.wait(), 5)
                    await asyncio.wait_for(reconnected.wait(), 5)
                    await handle.close()
                    manager = client._user_manager
                    assert manager is not None and manager._authentication is not None
                    assert manager._authentication._deadline is None
                    assert frames[0] == {
                        "type": "user",
                        "markets": ["synthetic-market"],
                        "auth": {"accessToken": before.access_token},
                    }
                    assert frames[1] == {
                        "type": "auth",
                        "auth": {"accessToken": after.access_token},
                    }
                    assert frames[2] == {
                        "type": "user",
                        "markets": ["synthetic-market"],
                        "auth": {"accessToken": after.access_token},
                    }
        finally:
            server.close()
            await server.wait_closed()
        assert before.access_token not in caplog.text and after.access_token not in caplog.text
        assert before.refresh_token not in caplog.text

    with caplog.at_level(logging.DEBUG):
        asyncio.run(run())


@pytest.mark.parametrize("async_client", [False, True])
def test_fresh_bearer_restoration_rejects_invalid_refresh_before_return(async_client: bool) -> None:
    callback = Mock()
    pair = credentials()
    with respx.mock as router:
        route = router.post(GATEWAY + "/v1/auth/refresh").respond(
            401, json={"code": "invalid_refresh_token"}
        )

        async def run() -> None:
            await AsyncSecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                credentials=pair,
                on_credentials_changed=callback,
            )

        with pytest.raises(RequestRejectedError) as rejected:
            if async_client:
                asyncio.run(run())
            else:
                SecureClient.create(
                    private_key=PRIVATE_KEY,
                    wallet=SIGNER.address,
                    credentials=pair,
                    on_credentials_changed=callback,
                )
        assert rejected.value.code == "invalid_refresh_token" and route.call_count == 1
        callback.assert_not_called()


@pytest.mark.parametrize(
    "code,reason,attempts",
    [(1008, "authentication failed", 1), (1013, "authentication unavailable, please retry", 3)],
)
def test_user_socket_auth_failure_reconnects_are_bounded(
    code: int, reason: str, attempts: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from websockets.asyncio.server import ServerConnection, serve

    from polymarket._internal.streams.clob.user import ClobUserStreamManager

    def immediate_backoff(attempt: int, *, base_s: float, max_s: float) -> float:
        return 0

    monkeypatch.setattr(
        "polymarket._internal.streams.reconnect.jittered_backoff", immediate_backoff
    )

    async def run() -> None:
        pair = credentials()
        session = AsyncGatewaySession(pair, AsyncTransport(base_url=GATEWAY))
        connections = 0

        async def handler(ws: ServerConnection) -> None:
            nonlocal connections
            connections += 1
            await ws.recv()
            await ws.close(code, reason)

        server = await serve(handler, host="127.0.0.1", port=0)
        port = next(iter(server.sockets)).getsockname()[1]
        manager = ClobUserStreamManager(
            url=f"ws://127.0.0.1:{port}", session=session, resolve_credentials=session.ensure_valid
        )
        try:
            handle = await manager.subscribe(markets=["synthetic-market"])
            with pytest.raises(RequestRejectedError):
                await asyncio.wait_for(anext(handle), 5)
            assert connections == attempts and not manager._scheduler.is_pending
        finally:
            await manager.close()
            await session.close()
            server.close()
            await server.wait_closed()

    asyncio.run(run())


@pytest.mark.parametrize("async_client", [False, True])
def test_logout_revokes_after_cached_proactive_refresh_failure(
    async_client: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [time.time()]
    pair = credentials(expiry=clock[0] + 3600)
    monkeypatch.setattr("polymarket._internal.gateway_session.time.time", lambda: clock[0])
    callback = Mock()
    with respx.mock as router:
        router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(pair))
        refresh = router.post(GATEWAY + "/v1/auth/refresh").respond(
            503, json={"code": "identity_provider_unavailable"}
        )
        logout = router.post(GATEWAY + "/v1/auth/logout").mock(
            side_effect=[httpx.Response(503), httpx.Response(204)]
        )

        async def run() -> None:
            client = await AsyncSecureClient.create(
                private_key=PRIVATE_KEY, wallet=SIGNER.address, on_credentials_changed=callback
            )
            session = client._ctx.session
            assert session is not None
            clock[0] += 3575  # still 25 seconds usable when the proactive timer fires
            session._scheduled()
            task = session._task
            assert task is not None
            with pytest.raises(RequestRejectedError):
                await task
            with pytest.raises(RequestRejectedError):
                await session.ensure_valid()  # ordinary requests still see the cached failure
            public = await client.end_authentication()
            await public.close()
            assert session._closed and session._timer is None and client._ended

        if async_client:
            asyncio.run(run())
        else:
            client = SecureClient.create(
                private_key=PRIVATE_KEY, wallet=SIGNER.address, on_credentials_changed=callback
            )
            session = client._ctx.session
            assert session is not None
            clock[0] += 3575
            with session._condition:
                session._deadline = time.monotonic()
                session._condition.notify_all()
                assert session._condition.wait_for(
                    lambda: session._error is not None and not session._refreshing, timeout=5
                )
            with pytest.raises(RequestRejectedError):
                session.ensure_valid()
            client.end_authentication().close()
            assert client._ended and session._worker is not None
            assert not session._worker.is_alive()
        assert refresh.call_count == 3 and logout.call_count == 2
        for index in range(logout.call_count):
            request = cast(Call, logout.calls[index]).request
            assert request.headers["Authorization"] == "Bearer " + pair.access_token
            assert request.content == b"" and "X-API-Key" not in request.headers
        callback.assert_not_called()


@pytest.mark.parametrize("async_client", [False, True])
@pytest.mark.parametrize("failure", ["unavailable", "invalid", "transport"])
def test_logout_failures_are_bounded_and_reported_after_cleanup(
    async_client: bool, failure: str
) -> None:
    pair = credentials()
    with respx.mock as router:
        router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(pair))
        logout = router.post(GATEWAY + "/v1/auth/logout")
        if failure == "transport":
            logout.mock(side_effect=httpx.ConnectError("synthetic connection failure"))
        else:
            logout.respond(
                503 if failure == "unavailable" else 401,
                json={
                    "code": "identity_provider_unavailable"
                    if failure == "unavailable"
                    else "invalid_access_token"
                },
            )
        expected_error = TransportError if failure == "transport" else RequestRejectedError

        async def run() -> None:
            client = await AsyncSecureClient.create(private_key=PRIVATE_KEY, wallet=SIGNER.address)
            session = client._ctx.session
            assert session is not None
            session._error = RequestRejectedError("Previous refresh failed", status=503)
            with pytest.raises(expected_error) as error:
                await client.end_authentication()
            assert str(error.value) != "Previous refresh failed"
            assert client._ended and session._closed and session._timer is None
            with pytest.raises(RuntimeError):
                await client.fetch_api_keys()

        if async_client:
            asyncio.run(run())
        else:
            client = SecureClient.create(private_key=PRIVATE_KEY, wallet=SIGNER.address)
            session = client._ctx.session
            assert session is not None
            session._error = RequestRejectedError("Previous refresh failed", status=503)
            with pytest.raises(expected_error) as error:
                client.end_authentication()
            assert str(error.value) != "Previous refresh failed"
            assert client._ended and session._stop.is_set()
            assert session._worker is not None and not session._worker.is_alive()
            with pytest.raises(RuntimeError):
                client.fetch_api_keys()
        assert logout.call_count == (1 if failure == "invalid" else 3)


@pytest.mark.parametrize("async_client", [False, True])
@pytest.mark.parametrize("expiry", ["local", "server", "repeated_server", "during_retry"])
def test_logout_expiry_recovery_is_once_without_adoption_or_callback(
    async_client: bool, expiry: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [time.time()]
    before = credentials(expiry=clock[0] + 3600)
    after = credentials(expiry=clock[0] + 7200, tag="logout-recovery")
    monkeypatch.setattr("polymarket._internal.gateway_session.time.time", lambda: clock[0])
    callback = Mock()
    with respx.mock as router:
        router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(before))
        refresh = router.post(GATEWAY + "/v1/auth/refresh").mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=response(after))]
        )
        logout = router.post(GATEWAY + "/v1/auth/logout")
        if expiry == "local":
            logout.respond(204)
        elif expiry == "during_retry":
            attempts = 0

            def transient_then_expired(request: httpx.Request) -> httpx.Response:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    clock[0] += 3601
                    return httpx.Response(503)
                return httpx.Response(204)

            logout.mock(side_effect=transient_then_expired)
        else:
            logout.mock(
                side_effect=[
                    httpx.Response(401, json={"code": "expired_access_token"}),
                    httpx.Response(401, json={"code": "expired_access_token"})
                    if expiry == "repeated_server"
                    else httpx.Response(204),
                ]
            )

        async def run() -> None:
            client = await AsyncSecureClient.create(
                private_key=PRIVATE_KEY, wallet=SIGNER.address, on_credentials_changed=callback
            )
            session = client._ctx.session
            assert session is not None
            session._error = RequestRejectedError("Cached refresh failure", status=503)
            if expiry == "local":
                clock[0] += 3601
            if expiry == "repeated_server":
                with pytest.raises(RequestRejectedError) as error:
                    await client.end_authentication()
                assert error.value.code == "expired_access_token"
            else:
                public = await client.end_authentication()
                await public.close()
            assert session.credentials == before and session._closed and session._timer is None

        if async_client:
            asyncio.run(run())
        else:
            client = SecureClient.create(
                private_key=PRIVATE_KEY, wallet=SIGNER.address, on_credentials_changed=callback
            )
            session = client._ctx.session
            assert session is not None
            session._error = RequestRejectedError("Cached refresh failure", status=503)
            if expiry == "local":
                clock[0] += 3601
            if expiry == "repeated_server":
                with pytest.raises(RequestRejectedError) as error:
                    client.end_authentication()
                assert error.value.code == "expired_access_token"
            else:
                client.end_authentication().close()
            assert session.credentials == before and session._stop.is_set()
        assert refresh.call_count == 2  # bounded transient recovery, not a refresh/retry loop
        assert logout.call_count == (1 if expiry == "local" else 2)
        assert (
            cast(Call, logout.calls[-1]).request.headers["Authorization"]
            == "Bearer " + after.access_token
        )
        assert json.loads(cast(Call, refresh.calls[0]).request.content) == {
            "refresh_token": before.refresh_token
        }
        callback.assert_not_called()


@pytest.mark.parametrize("async_client", [False, True])
@pytest.mark.parametrize("unavailable", [False, True])
def test_logout_cannot_refresh_expired_bearer_reports_rejection_and_closes(
    async_client: bool, unavailable: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [time.time()]
    pair = credentials(expiry=clock[0] + 3600)
    monkeypatch.setattr("polymarket._internal.gateway_session.time.time", lambda: clock[0])
    with respx.mock as router:
        router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(pair))
        code = "identity_provider_unavailable" if unavailable else "invalid_refresh_token"
        refresh = router.post(GATEWAY + "/v1/auth/refresh").respond(
            503 if unavailable else 401, json={"code": code}
        )

        async def run() -> None:
            client = await AsyncSecureClient.create(private_key=PRIVATE_KEY, wallet=SIGNER.address)
            session = client._ctx.session
            assert session is not None
            clock[0] += 3601
            session._error = RequestRejectedError("Cached refresh failure", status=503)
            with pytest.raises(RequestRejectedError) as error:
                await client.end_authentication()
            assert error.value.code == code
            assert client._ended and session._closed and session._timer is None

        if async_client:
            asyncio.run(run())
        else:
            client = SecureClient.create(private_key=PRIVATE_KEY, wallet=SIGNER.address)
            session = client._ctx.session
            assert session is not None
            clock[0] += 3601
            session._error = RequestRejectedError("Cached refresh failure", status=503)
            with pytest.raises(RequestRejectedError) as error:
                client.end_authentication()
            assert error.value.code == code
            assert client._ended and session._worker is not None and not session._worker.is_alive()
        assert refresh.call_count == (3 if unavailable else 1)


@pytest.mark.parametrize("async_client", [False, True])
def test_logout_stops_inflight_refresh_before_using_last_adopted_bearer(
    async_client: bool,
) -> None:
    before, after = credentials(), credentials(tag="late-refresh")
    callback = Mock()
    with respx.mock as router:
        router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(before))
        refresh = router.post(GATEWAY + "/v1/auth/refresh")
        logout = router.post(GATEWAY + "/v1/auth/logout").respond(204)

        async def run() -> None:
            entered = asyncio.Event()

            async def handle(request: httpx.Request) -> httpx.Response:
                entered.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    return httpx.Response(200, json=response(after))
                raise AssertionError("Refresh must be cancelled")

            refresh.mock(side_effect=handle)
            client = await AsyncSecureClient.create(
                private_key=PRIVATE_KEY, wallet=SIGNER.address, on_credentials_changed=callback
            )
            session = client._ctx.session
            assert session is not None
            pending = asyncio.create_task(session.refresh(before.access_token))
            await entered.wait()
            public = await client.end_authentication()
            await public.close()
            with pytest.raises(RuntimeError, match="closed"):
                await pending
            assert session.credentials == before and session._closed and session._timer is None

        if async_client:
            asyncio.run(run())
        else:
            entered, release = threading.Event(), threading.Event()

            def handle(request: httpx.Request) -> httpx.Response:
                entered.set()
                assert release.wait(5)
                return httpx.Response(200, json=response(after))

            refresh.mock(side_effect=handle)
            client = SecureClient.create(
                private_key=PRIVATE_KEY, wallet=SIGNER.address, on_credentials_changed=callback
            )
            session = client._ctx.session
            assert session is not None
            with ThreadPoolExecutor(max_workers=2) as executor:
                pending = executor.submit(session.refresh, before.access_token)
                assert entered.wait(5)
                ending = executor.submit(client.end_authentication)
                assert session._stop.wait(5)
                with pytest.raises(RuntimeError, match="closed"):
                    client.fetch_api_keys()
                release.set()
                ending.result(timeout=5).close()
                with pytest.raises(RuntimeError, match="closed"):
                    pending.result(timeout=5)
            assert session.credentials == before and session._worker is not None
            assert not session._worker.is_alive()
        assert refresh.call_count == logout.call_count == 1
        assert (
            cast(Call, logout.calls[0]).request.headers["Authorization"]
            == "Bearer " + before.access_token
        )
        callback.assert_not_called()


def test_cancelling_logout_propagates_and_still_closes_local_client() -> None:
    async def run() -> None:
        pair = credentials()
        entered = asyncio.Event()
        attempts = 0

        async def pending_logout(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            entered.set()
            await asyncio.Future()
            raise AssertionError("Logout must be cancelled")

        with respx.mock as router:
            router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
            router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(pair))
            router.post(GATEWAY + "/v1/auth/logout").mock(side_effect=pending_logout)
            client = await AsyncSecureClient.create(private_key=PRIVATE_KEY, wallet=SIGNER.address)
            session = client._ctx.session
            assert session is not None
            session._error = RequestRejectedError("Cached refresh failure", status=503)
            ending = asyncio.create_task(client.end_authentication())
            await entered.wait()
            ending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await ending
            assert attempts == 1
            assert client._ended and session._closed and session._timer is None
            with pytest.raises(RuntimeError):
                await client.fetch_api_keys()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["rejected", "cancelled"])
def test_failed_rfq_bearer_open_releases_socket_and_session_listener(failure: str) -> None:
    from dataclasses import replace

    from websockets.asyncio.server import ServerConnection, serve

    from polymarket._internal.environment import PRODUCTION_CONFIG, create_environment

    async def run() -> None:
        received, closed = asyncio.Event(), asyncio.Event()

        async def handler(ws: ServerConnection) -> None:
            try:
                await ws.recv()
                received.set()
                if failure == "rejected":
                    await ws.send(
                        json.dumps({"type": "auth", "success": False, "code": "auth_invalid"})
                    )
                await ws.wait_closed()
            finally:
                closed.set()

        async with serve(handler, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            environment = create_environment(
                name="synthetic",
                config=replace(PRODUCTION_CONFIG, rfq_quoter_ws_url=f"ws://127.0.0.1:{port}"),
            )
            with respx.mock as router:
                router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
                router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(credentials()))
                async with await AsyncSecureClient.create(
                    private_key=PRIVATE_KEY, wallet=SIGNER.address, environment=environment
                ) as client:

                    async def open_session() -> None:
                        await client.open_rfq_session()

                    opening = asyncio.create_task(open_session())
                    await asyncio.wait_for(received.wait(), 5)
                    if failure == "cancelled":
                        opening.cancel()
                    error = (
                        asyncio.CancelledError if failure == "cancelled" else RequestRejectedError
                    )
                    with pytest.raises(error):
                        await asyncio.wait_for(opening, 5)
                    await asyncio.wait_for(closed.wait(), 5)
                    session = client._ctx.session
                    assert session is not None and not session._listeners
                    assert client._rfq_session is None and client._rfq_session_connecting is None

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["disconnect", "protocol"])
def test_terminal_rfq_bearer_session_releases_authentication(failure: str) -> None:
    from dataclasses import replace

    from websockets.asyncio.server import ServerConnection, serve

    from polymarket._internal.environment import PRODUCTION_CONFIG, create_environment
    from polymarket._internal.rfq import RfqQuoterSession
    from polymarket.errors import ConnectionLostError

    async def run() -> None:
        release, closed = asyncio.Event(), asyncio.Event()

        async def handler(ws: ServerConnection) -> None:
            try:
                await ws.recv()
                await ws.send(json.dumps({"type": "auth", "success": True}))
                await release.wait()
                if failure == "disconnect":
                    await ws.close(1011, "synthetic disconnect")
                else:
                    await ws.send(
                        json.dumps(
                            {"type": "RFQ_ERROR", "request_type": "RFQ_QUOTE", "code": "synthetic"}
                        )
                    )
                await ws.wait_closed()
            finally:
                closed.set()

        async with serve(handler, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            environment = create_environment(
                name="synthetic",
                config=replace(PRODUCTION_CONFIG, rfq_quoter_ws_url=f"ws://127.0.0.1:{port}"),
            )
            with respx.mock as router:
                router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
                router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(credentials()))
                async with await AsyncSecureClient.create(
                    private_key=PRIVATE_KEY, wallet=SIGNER.address, environment=environment
                ) as client:
                    stream = cast(RfqQuoterSession, await client.open_rfq_session())
                    authentication = stream._authentication
                    assert authentication is not None
                    release.set()
                    error = ConnectionLostError if failure == "disconnect" else TransportError
                    with pytest.raises(error):
                        await asyncio.wait_for(anext(stream), 5)
                    await asyncio.wait_for(closed.wait(), 5)
                    await stream.close()
                    session = client._ctx.session
                    assert session is not None and not session._listeners
                    assert authentication._closed and not authentication._connected
                    assert authentication._deadline is None and not authentication._tasks
                    assert client._rfq_session is None

    asyncio.run(run())
