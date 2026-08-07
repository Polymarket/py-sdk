# pyright: reportPrivateUsage=false, reportUnusedFunction=false
import asyncio
import dataclasses
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient, SecureClient
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket.clients._transport import AsyncTransport, SyncTransport

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
OTHER_WALLET = "0x000000000000000000000000000000000000dEaD"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


def _capturing_handler(captured: list[httpx.Request], payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


def _install_sync_data(client: SecureClient, handler: httpx.MockTransport) -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(base_url="https://example.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, data=transport)


def _install_async_data(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://example.test",
        client=httpx.AsyncClient(base_url="https://example.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, data=transport)


def _qs_user(request: httpx.Request) -> str:
    return parse_qs(urlparse(str(request.url)).query)["user"][0]


@pytest.fixture(name="captured")
def _captured() -> list[httpx.Request]:
    return []


# ---- get_portfolio_values ----


def test_secure_get_portfolio_values_defaults_to_signer(captured: list[httpx.Request]) -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, _capturing_handler(captured, []))
        client.get_portfolio_values()

    assert _qs_user(captured[0]) == SIGNER_ADDRESS


def test_secure_get_portfolio_values_respects_explicit_user(
    captured: list[httpx.Request],
) -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, _capturing_handler(captured, []))
        client.get_portfolio_values(user=OTHER_WALLET)

    assert _qs_user(captured[0]) == OTHER_WALLET


# ---- get_traded_market_count ----


def test_secure_get_traded_market_count_defaults_to_signer(
    captured: list[httpx.Request],
) -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(
            client, _capturing_handler(captured, {"user": SIGNER_ADDRESS, "traded": 0})
        )
        client.get_traded_market_count()

    assert _qs_user(captured[0]) == SIGNER_ADDRESS


def test_secure_get_traded_market_count_respects_explicit_user(
    captured: list[httpx.Request],
) -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(
            client, _capturing_handler(captured, {"user": OTHER_WALLET, "traded": 0})
        )
        client.get_traded_market_count(user=OTHER_WALLET)

    assert _qs_user(captured[0]) == OTHER_WALLET


# ---- download_accounting_snapshot ----


def test_secure_download_accounting_snapshot_defaults_to_signer(
    captured: list[httpx.Request],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"PK\x03\x04", request=request)

    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, httpx.MockTransport(handler))
        client.download_accounting_snapshot()

    assert _qs_user(captured[0]) == SIGNER_ADDRESS


def test_secure_download_accounting_snapshot_respects_explicit_user(
    captured: list[httpx.Request],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"PK\x03\x04", request=request)

    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, httpx.MockTransport(handler))
        client.download_accounting_snapshot(user=OTHER_WALLET)

    assert _qs_user(captured[0]) == OTHER_WALLET


# ---- list_positions ----


def test_secure_list_positions_defaults_to_signer(captured: list[httpx.Request]) -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, _capturing_handler(captured, []))
        client.list_positions().first_page()

    assert _qs_user(captured[0]) == SIGNER_ADDRESS


def test_secure_list_positions_respects_explicit_user(captured: list[httpx.Request]) -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, _capturing_handler(captured, []))
        client.list_positions(user=OTHER_WALLET).first_page()

    assert _qs_user(captured[0]) == OTHER_WALLET


# ---- list_closed_positions ----


def test_secure_list_closed_positions_defaults_to_signer(captured: list[httpx.Request]) -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, _capturing_handler(captured, []))
        client.list_closed_positions().first_page()

    assert _qs_user(captured[0]) == SIGNER_ADDRESS


# ---- list_trades ----


def test_secure_list_trades_defaults_to_signer(captured: list[httpx.Request]) -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, _capturing_handler(captured, []))
        client.list_trades().first_page()

    assert _qs_user(captured[0]) == SIGNER_ADDRESS


# ---- list_activity ----


def test_secure_list_activity_defaults_to_signer(captured: list[httpx.Request]) -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, _capturing_handler(captured, []))
        client.list_activity().first_page()

    assert _qs_user(captured[0]) == SIGNER_ADDRESS


# ---- async parity ----


def test_async_secure_list_positions_defaults_to_signer() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_async_data(client, _capturing_handler(captured, []))
            await client.list_positions().first_page()
        finally:
            await client.close()

    asyncio.run(run())
    assert _qs_user(captured[0]) == SIGNER_ADDRESS


def test_async_secure_list_positions_respects_explicit_user() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_async_data(client, _capturing_handler(captured, []))
            await client.list_positions(user=OTHER_WALLET).first_page()
        finally:
            await client.close()

    asyncio.run(run())
    assert _qs_user(captured[0]) == OTHER_WALLET


def test_async_secure_list_positions_defaults_to_wallet_when_proxy() -> None:
    from polymarket._internal.wallet import derive_proxy_wallet_address

    proxy_wallet = derive_proxy_wallet_address(SIGNER_ADDRESS, PRODUCTION_CONFIG.wallet_derivation)
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=proxy_wallet,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_async_data(client, _capturing_handler(captured, []))
            await client.list_positions().first_page()
        finally:
            await client.close()

    asyncio.run(run())
    assert _qs_user(captured[0]).lower() == proxy_wallet.lower()
    assert _qs_user(captured[0]).lower() != SIGNER_ADDRESS.lower()


def test_async_secure_download_accounting_snapshot_defaults_to_signer() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"PK\x03\x04", request=request)

    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            _install_async_data(client, httpx.MockTransport(handler))
            await client.download_accounting_snapshot()
        finally:
            await client.close()

    asyncio.run(run())
    assert _qs_user(captured[0]) == SIGNER_ADDRESS


# ---- empty-string is not None ----


def test_secure_list_positions_rejects_explicit_empty_user(
    captured: list[httpx.Request],
) -> None:
    from polymarket.errors import UserInputError

    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, _capturing_handler(captured, []))
        with pytest.raises(UserInputError, match="user is required"):
            client.list_positions(user="").first_page()


def test_secure_get_portfolio_values_rejects_explicit_empty_user(
    captured: list[httpx.Request],
) -> None:
    from polymarket.errors import UserInputError

    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        _install_sync_data(client, _capturing_handler(captured, []))
        with pytest.raises(UserInputError, match="user is required"):
            client.get_portfolio_values(user="")
