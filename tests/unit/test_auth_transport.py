# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import json
from typing import Any, cast
from urllib.parse import urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient, BuilderApiKey, BuilderApiKeyInfo
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import RequestRejectedError, UnexpectedResponseError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


def _capture(captured: list[httpx.Request], status: int, payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, json=payload, request=request)

    return httpx.MockTransport(handler)


def _install_clob(client: AsyncSecureClient, handler: httpx.MockTransport, *, secure: bool) -> None:
    if secure:
        transport = AsyncTransport(
            base_url="https://clob.test",
            client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
            header_resolver=client._ctx.secure_clob._header_resolver,
        )
        client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)
    else:
        transport = AsyncTransport(
            base_url="https://clob.test",
            client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
        )
        client._ctx = dataclasses.replace(client._ctx, clob=transport)


def test_create_or_derive_api_key_posts_l1_headers_on_first_attempt() -> None:
    from eth_account import Account

    from polymarket._internal.actions.auth import create_or_derive_api_key
    from polymarket._internal.l1_auth import sign_api_key_auth

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, json={"apiKey": "k", "secret": "s", "passphrase": "p"}, request=request
        )

    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(
            base_url="https://clob.test", transport=httpx.MockTransport(handler)
        ),
    )

    async def run() -> ApiKeyCreds:
        signer: Any = Account.from_key(PRIVATE_KEY)
        signature = sign_api_key_auth(signer, chain_id=137, timestamp=1700000000)
        creds = await create_or_derive_api_key(transport, signature)
        await transport.close()
        return creds

    creds = asyncio.run(run())

    assert creds.key == "k"
    assert len(captured) == 1
    assert captured[0].method == "POST"
    assert urlparse(str(captured[0].url)).path == "/auth/api-key"
    assert captured[0].headers.get("POLY_ADDRESS")
    assert captured[0].headers.get("POLY_SIGNATURE", "").startswith("0x")
    assert captured[0].headers.get("POLY_TIMESTAMP") == "1700000000"
    assert captured[0].headers.get("POLY_NONCE") == "0"


def test_async_secure_create_falls_back_to_derive_on_400() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if request.method == "POST" and path == "/auth/api-key":
            return httpx.Response(400, json={"error": "already exists"}, request=request)
        if request.method == "GET" and path == "/auth/derive-api-key":
            return httpx.Response(
                200,
                json={"apiKey": "derived", "secret": "s", "passphrase": "p"},
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    intercept = httpx.MockTransport(handler)
    clob_transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=intercept),
    )

    from eth_account import Account

    from polymarket._internal.actions.auth import create_or_derive_api_key
    from polymarket._internal.l1_auth import sign_api_key_auth

    async def run() -> ApiKeyCreds:
        signer: Any = Account.from_key(PRIVATE_KEY)
        signature = sign_api_key_auth(signer, chain_id=137, timestamp=1700000000)
        creds = await create_or_derive_api_key(clob_transport, signature)
        await clob_transport.close()
        return creds

    creds = asyncio.run(run())

    assert creds.key == "derived"
    assert len(captured) == 2
    assert captured[0].method == "POST"
    assert captured[1].method == "GET"
    assert urlparse(str(captured[1].url)).path == "/auth/derive-api-key"


def test_async_secure_create_with_credentials_skips_auth_flow() -> None:
    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            assert client.credentials is FAKE_CREDS
        finally:
            await client.close()

    asyncio.run(run())


def test_fetch_api_keys_sends_l2_headers() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[str, ...]:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_clob(client, _capture(captured, 200, {"apiKeys": ["k1", "k2"]}), secure=True)
            return await client.fetch_api_keys()
        finally:
            await client.close()

    keys = asyncio.run(run())

    assert keys == ("k1", "k2")
    assert captured[0].method == "GET"
    assert urlparse(str(captured[0].url)).path == "/auth/api-keys"
    headers = captured[0].headers
    assert headers.get("POLY_ADDRESS")
    assert headers.get("POLY_API_KEY") == FAKE_CREDS.key
    assert headers.get("POLY_PASSPHRASE") == FAKE_CREDS.passphrase
    assert headers.get("POLY_SIGNATURE")
    assert headers.get("POLY_TIMESTAMP")


def test_delete_api_key_succeeds_on_ok_response() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_clob(client, _capture(captured, 200, "OK"), secure=True)
            await client.delete_api_key()
        finally:
            await client.close()

    asyncio.run(run())

    assert captured[0].method == "DELETE"
    assert urlparse(str(captured[0].url)).path == "/auth/api-key"


def test_delete_api_key_raises_unexpected_response_on_non_ok_payload() -> None:
    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_clob(client, _capture([], 200, "FAIL"), secure=True)
            await client.delete_api_key()
        finally:
            await client.close()

    with pytest.raises(UnexpectedResponseError):
        asyncio.run(run())


def test_create_builder_api_key_sends_l2_headers() -> None:
    captured: list[httpx.Request] = []

    async def run() -> BuilderApiKey:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_clob(
                client,
                _capture(
                    captured,
                    200,
                    {"key": "builder-key", "secret": "dGVzdA==", "passphrase": "builder-pass"},
                ),
                secure=True,
            )
            return await client.create_builder_api_key()
        finally:
            await client.close()

    creds = asyncio.run(run())

    assert creds.key == "builder-key"
    assert captured[0].method == "POST"
    assert urlparse(str(captured[0].url)).path == "/auth/builder-api-key"
    headers = captured[0].headers
    assert headers.get("POLY_API_KEY") == FAKE_CREDS.key
    assert headers.get("POLY_SIGNATURE")


def test_fetch_builder_api_keys_sends_l2_headers() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[BuilderApiKeyInfo, ...]:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_clob(
                client,
                _capture(captured, 200, [{"key": "builder-key", "createdAt": 1700000000000}]),
                secure=True,
            )
            return await client.fetch_builder_api_keys()
        finally:
            await client.close()

    keys = asyncio.run(run())

    assert keys[0].key == "builder-key"
    assert captured[0].method == "GET"
    assert urlparse(str(captured[0].url)).path == "/auth/builder-api-key"
    assert captured[0].headers.get("POLY_API_KEY") == FAKE_CREDS.key


def test_revoke_builder_api_key_uses_secure_clob() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_clob(client, _capture(captured, 200, "OK"), secure=True)
            await client.revoke_builder_api_key()
        finally:
            await client.close()

    asyncio.run(run())

    assert captured[0].method == "DELETE"
    assert urlparse(str(captured[0].url)).path == "/auth/builder-api-key"
    assert captured[0].headers.get("POLY_API_KEY") == FAKE_CREDS.key


def test_fetch_api_keys_propagates_401_as_request_rejected() -> None:
    async def run() -> tuple[str, ...]:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_clob(client, _capture([], 401, {"error": "invalid"}), secure=True)
            return await client.fetch_api_keys()
        finally:
            await client.close()

    with pytest.raises(RequestRejectedError) as info:
        asyncio.run(run())
    assert info.value.status == 401


def test_async_secure_create_rejects_credentials_with_nonzero_nonce() -> None:
    from polymarket.errors import UserInputError

    async def run() -> None:
        await AsyncSecureClient._create(
            private_key=PRIVATE_KEY, wallet=SIGNER_ADDRESS, credentials=FAKE_CREDS, nonce=1
        )

    with pytest.raises(UserInputError, match="nonce cannot be combined"):
        asyncio.run(run())


def test_async_secure_create_rejects_negative_nonce() -> None:
    from polymarket.errors import UserInputError

    async def run() -> None:
        await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            nonce=-1,
        )

    with pytest.raises(UserInputError, match="non-negative integer"):
        asyncio.run(run())


def test_async_secure_create_rejects_bool_nonce() -> None:
    from polymarket.errors import UserInputError

    async def run() -> None:
        await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            nonce=True,  # type: ignore[arg-type]
        )

    with pytest.raises(UserInputError, match="non-negative integer"):
        asyncio.run(run())


def test_validated_credentials_pass_through_when_active() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if urlparse(str(request.url)).path == "/auth/api-keys":
            return httpx.Response(200, json={"apiKeys": [FAKE_CREDS.key]}, request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    intercept = httpx.MockTransport(handler)

    async def run() -> AsyncSecureClient:
        from eth_account import Account

        from polymarket._internal.actions.auth import fetch_api_keys
        from polymarket.clients.async_secure import _make_l2_header_resolver

        signer: Any = Account.from_key(PRIVATE_KEY)
        probe = AsyncTransport(
            base_url="https://clob.test",
            client=httpx.AsyncClient(base_url="https://clob.test", transport=intercept),
            header_resolver=_make_l2_header_resolver(signer, FAKE_CREDS),
        )
        keys = await fetch_api_keys(probe)
        await probe.close()
        assert FAKE_CREDS.key in keys
        return cast(Any, None)

    asyncio.run(run())

    assert len(captured) == 1
    assert urlparse(str(captured[0].url)).path == "/auth/api-keys"


def test_l2_signature_includes_canonical_body_for_authenticated_post() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            transport = AsyncTransport(
                base_url="https://clob.test",
                client=httpx.AsyncClient(
                    base_url="https://clob.test",
                    transport=_capture(captured, 200, "OK"),
                ),
                header_resolver=client._ctx.secure_clob._header_resolver,
            )
            await transport.post_json("/some-endpoint", json={"a": 1, "b": 2})
            await transport.close()
        finally:
            await client.close()

    asyncio.run(run())

    request = captured[0]
    assert request.method == "POST"
    body_str = json.dumps({"a": 1, "b": 2}, separators=(",", ":"))
    assert request.content == body_str.encode("utf-8")
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["POLY_SIGNATURE"]
