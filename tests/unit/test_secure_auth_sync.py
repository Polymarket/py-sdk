# pyright: reportPrivateUsage=false
import dataclasses
import json
from typing import Any, cast
from urllib.parse import urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, SecureClient
from polymarket._internal.environment import get_environment_config
from polymarket.clients._transport import SyncTransport
from polymarket.clients.secure import _make_l2_header_resolver_sync
from polymarket.errors import RequestRejectedError, UserInputError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


def _capture(captured: list[httpx.Request], status: int, payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, json=payload, request=request)

    return httpx.MockTransport(handler)


def _make_client() -> SecureClient:
    return SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def test_create_or_derive_api_key_sync_posts_l1_headers_on_first_attempt() -> None:
    from eth_account import Account

    from polymarket._internal.actions.auth import create_or_derive_api_key_sync
    from polymarket._internal.l1_auth import sign_api_key_auth

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, json={"apiKey": "k", "secret": "s", "passphrase": "p"}, request=request
        )

    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=httpx.MockTransport(handler)),
    )

    signer: Any = Account.from_key(PRIVATE_KEY)
    signature = sign_api_key_auth(signer, chain_id=137, timestamp=1700000000)
    creds = create_or_derive_api_key_sync(transport, signature)
    transport.close()

    assert creds.key == "k"
    assert len(captured) == 1
    assert captured[0].method == "POST"
    assert urlparse(str(captured[0].url)).path == "/auth/api-key"
    assert captured[0].headers.get("POLY_ADDRESS")
    assert captured[0].headers.get("POLY_SIGNATURE", "").startswith("0x")
    assert captured[0].headers.get("POLY_TIMESTAMP") == "1700000000"
    assert captured[0].headers.get("POLY_NONCE") == "0"


def test_create_or_derive_api_key_sync_falls_back_to_derive_on_400() -> None:
    from eth_account import Account

    from polymarket._internal.actions.auth import create_or_derive_api_key_sync
    from polymarket._internal.l1_auth import sign_api_key_auth

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

    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=httpx.MockTransport(handler)),
    )

    signer: Any = Account.from_key(PRIVATE_KEY)
    signature = sign_api_key_auth(signer, chain_id=137, timestamp=1700000000)
    creds = create_or_derive_api_key_sync(transport, signature)
    transport.close()

    assert creds.key == "derived"
    assert len(captured) == 2
    assert captured[0].method == "POST"
    assert captured[1].method == "GET"
    assert urlparse(str(captured[1].url)).path == "/auth/derive-api-key"


def test_create_with_credentials_skips_auth_flow_when_validation_disabled() -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        assert client.credentials is FAKE_CREDS


def test_create_validates_credentials_via_fetch_api_keys_when_enabled() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if urlparse(str(request.url)).path == "/auth/api-keys":
            return httpx.Response(200, json={"apiKeys": [FAKE_CREDS.key]}, request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    from eth_account import Account

    from polymarket._internal.actions.auth import fetch_api_keys_sync

    signer: Any = Account.from_key(PRIVATE_KEY)
    probe = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=httpx.MockTransport(handler)),
        header_resolver=_make_l2_header_resolver_sync(signer, FAKE_CREDS),
    )
    keys = fetch_api_keys_sync(probe)
    probe.close()
    assert FAKE_CREDS.key in keys
    assert len(captured) == 1
    headers = captured[0].headers
    assert headers.get("POLY_API_KEY") == FAKE_CREDS.key
    assert headers.get("POLY_SIGNATURE")
    assert headers.get("POLY_TIMESTAMP")


def test_create_rejects_credentials_with_nonzero_nonce() -> None:
    with pytest.raises(UserInputError, match="nonce cannot be combined"):
        SecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            nonce=1,
        )


def test_create_rejects_negative_nonce() -> None:
    with pytest.raises(UserInputError, match="non-negative integer"):
        SecureClient._create(private_key=PRIVATE_KEY, wallet=SIGNER_ADDRESS, nonce=-1)


def test_create_rejects_bool_nonce() -> None:
    with pytest.raises(UserInputError, match="non-negative integer"):
        SecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            nonce=cast(int, True),
        )


def test_create_defaults_wallet_to_current_deposit_wallet() -> None:
    from eth_account import Account

    from polymarket._internal.wallet import derive_uups_deposit_wallet_address
    from polymarket.environments import PRODUCTION

    signer = Account.from_key(PRIVATE_KEY)
    expected = derive_uups_deposit_wallet_address(
        signer.address, get_environment_config(PRODUCTION).wallet_derivation
    )

    with SecureClient._create(
        private_key=PRIVATE_KEY,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        assert client.wallet_type == "DEPOSIT_WALLET"
        assert str(client.wallet) == expected


def test_create_rejects_invalid_wallet_address() -> None:
    with pytest.raises(UserInputError, match="Invalid wallet address"):
        SecureClient._create(
            private_key=PRIVATE_KEY,
            wallet="not-an-address",
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )


def test_create_classifies_eoa_when_wallet_equals_signer() -> None:
    with _make_client() as client:
        assert client.wallet_type == "EOA"
        assert client.wallet == client.signer


def test_create_normalizes_wallet_to_checksum() -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS.lower(),
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        assert client.wallet == SIGNER_ADDRESS


def test_l2_signature_includes_canonical_body_for_authenticated_post() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        transport = SyncTransport(
            base_url="https://clob.test",
            client=httpx.Client(
                base_url="https://clob.test",
                transport=_capture(captured, 200, "OK"),
            ),
            header_resolver=client._ctx.secure_clob._header_resolver,
        )
        transport.post_json("/some-endpoint", json={"a": 1, "b": 2})
        transport.close()

    request = captured[0]
    assert request.method == "POST"
    body_str = json.dumps({"a": 1, "b": 2}, separators=(",", ":"))
    assert request.content == body_str.encode("utf-8")
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["POLY_SIGNATURE"]


def test_fetch_api_keys_propagates_401_as_request_rejected() -> None:
    with _make_client() as client:
        transport = SyncTransport(
            base_url="https://clob.test",
            client=httpx.Client(
                base_url="https://clob.test",
                transport=_capture([], 401, {"error": "invalid"}),
            ),
            header_resolver=client._ctx.secure_clob._header_resolver,
        )
        client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)
        with pytest.raises(RequestRejectedError) as info:
            client.fetch_api_keys()
        assert info.value.status == 401
