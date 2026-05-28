# pyright: reportPrivateUsage=false
import contextlib
import dataclasses
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, BuilderApiKey, BuilderApiKeyInfo, PublicClient, SecureClient
from polymarket.clients._transport import SyncTransport
from polymarket.errors import RequestRejectedError, UnexpectedResponseError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


def _capture(captured: list[httpx.Request], status: int, payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, json=payload, request=request)

    return httpx.MockTransport(handler)


def _install_secure_clob(client: SecureClient, handler: httpx.MockTransport) -> None:
    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=handler),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)


def _make_client() -> SecureClient:
    return SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def test_fetch_api_keys_sends_l2_headers() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, {"apiKeys": ["k1", "k2"]}))
        keys = client.fetch_api_keys()

    assert keys == ("k1", "k2")
    request = captured[0]
    assert request.method == "GET"
    assert urlparse(str(request.url)).path == "/auth/api-keys"
    headers = request.headers
    assert headers.get("POLY_ADDRESS")
    assert headers.get("POLY_API_KEY") == FAKE_CREDS.key
    assert headers.get("POLY_PASSPHRASE") == FAKE_CREDS.passphrase
    assert headers.get("POLY_SIGNATURE")
    assert headers.get("POLY_TIMESTAMP")


def test_delete_api_key_succeeds_on_ok_response() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, "OK"))
        client.delete_api_key()

    assert captured[0].method == "DELETE"
    assert urlparse(str(captured[0].url)).path == "/auth/api-key"


def test_delete_api_key_raises_unexpected_response_on_non_ok_payload() -> None:
    with pytest.raises(UnexpectedResponseError), _make_client() as client:
        _install_secure_clob(client, _capture([], 200, "FAIL"))
        client.delete_api_key()


def test_create_builder_api_key_sends_l2_headers() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(
            client,
            _capture(
                captured,
                200,
                {"key": "builder-key", "secret": "dGVzdA==", "passphrase": "builder-pass"},
            ),
        )
        creds: BuilderApiKey = client.create_builder_api_key()

    assert creds.key == "builder-key"
    assert captured[0].method == "POST"
    assert urlparse(str(captured[0].url)).path == "/auth/builder-api-key"
    assert captured[0].headers.get("POLY_API_KEY") == FAKE_CREDS.key


def test_fetch_builder_api_keys_sends_l2_headers() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(
            client,
            _capture(captured, 200, [{"key": "builder-key", "createdAt": 1700000000000}]),
        )
        keys: tuple[BuilderApiKeyInfo, ...] = client.fetch_builder_api_keys()

    assert keys[0].key == "builder-key"
    assert captured[0].method == "GET"
    assert urlparse(str(captured[0].url)).path == "/auth/builder-api-key"
    assert captured[0].headers.get("POLY_API_KEY") == FAKE_CREDS.key


def test_revoke_builder_api_key_uses_secure_clob() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, "OK"))
        client.revoke_builder_api_key()

    assert captured[0].method == "DELETE"
    assert urlparse(str(captured[0].url)).path == "/auth/builder-api-key"
    assert captured[0].headers.get("POLY_API_KEY") == FAKE_CREDS.key


def test_end_authentication_calls_delete_and_returns_public_client() -> None:
    captured: list[httpx.Request] = []
    client = _make_client()
    _install_secure_clob(client, _capture(captured, 200, "OK"))
    public = client.end_authentication()

    assert isinstance(public, PublicClient)
    assert captured[0].method == "DELETE"
    assert urlparse(str(captured[0].url)).path == "/auth/api-key"
    public.close()


def test_end_authentication_returned_public_client_has_same_environment() -> None:
    client = _make_client()
    _install_secure_clob(client, _capture([], 200, "OK"))
    public = client.end_authentication()

    assert public.environment.name == "production"
    public.close()


def test_end_authentication_blocks_subsequent_method_calls() -> None:
    client = _make_client()
    _install_secure_clob(client, _capture([], 200, "OK"))
    client.end_authentication()

    with pytest.raises(RuntimeError, match="ended authentication"):
        client.fetch_api_keys()


def test_end_authentication_blocks_property_access_after_end() -> None:
    client = _make_client()
    _install_secure_clob(client, _capture([], 200, "OK"))
    client.end_authentication()

    with pytest.raises(RuntimeError, match="ended authentication"):
        _ = client.wallet


def test_end_authentication_tolerates_401_on_delete() -> None:
    client = _make_client()
    _install_secure_clob(client, _capture([], 401, {"error": "invalid"}))
    public = client.end_authentication()

    assert isinstance(public, PublicClient)
    public.close()


def test_end_authentication_tolerates_404_on_delete() -> None:
    client = _make_client()
    _install_secure_clob(client, _capture([], 404, {"error": "not found"}))
    public = client.end_authentication()

    assert isinstance(public, PublicClient)
    public.close()


def test_end_authentication_propagates_unexpected_errors_from_delete() -> None:
    client = _make_client()
    _install_secure_clob(client, _capture([], 500, {"error": "boom"}))

    with pytest.raises(RequestRejectedError) as info:
        client.end_authentication()
    assert info.value.status == 500


def test_end_authentication_marks_client_ended_even_when_delete_fails() -> None:
    client = _make_client()
    _install_secure_clob(client, _capture([], 500, {"error": "boom"}))
    with contextlib.suppress(RequestRejectedError):
        client.end_authentication()

    assert client._ended is True


def test_close_after_end_authentication_does_not_raise() -> None:
    client = _make_client()
    _install_secure_clob(client, _capture([], 200, "OK"))
    public = client.end_authentication()
    client.close()
    public.close()
