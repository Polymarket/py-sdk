from collections.abc import Iterator

import httpx
import pytest

from polymarket import AsyncSecureClient, BuilderApiKey, Environment, PlatformApiKey, SecureClient
from polymarket._internal.environment import PRODUCTION_CONFIG, get_environment_config

pytestmark = pytest.mark.anyio

_SUBMISSION_PATH = "/v1/wallets/transactions"


@pytest.fixture
def submissions(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[httpx.Request]]:
    """Observe the gasless submissions the SDK sends without changing them."""
    sent: list[httpx.Request] = []
    send = httpx.AsyncClient.send

    async def observe(
        self: httpx.AsyncClient, request: httpx.Request, **kwargs: object
    ) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMISSION_PATH:
            sent.append(request)
        return await send(self, request, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.AsyncClient, "send", observe)
    yield sent


def _submission_key_headers(request: httpx.Request) -> list[str]:
    return [
        name
        for name in request.headers
        if name.lower().startswith(("poly_builder_", "relayer_api_key"))
    ]


async def _transfer_one_unit_to_signer(client: AsyncSecureClient, environment: Environment) -> None:
    handle = await client.transfer_erc20(
        token_address=get_environment_config(environment).collateral_token,
        recipient_address=client.signer,
        amount=1,
        metadata="Test gasless transfer on the session alone",
    )
    await handle.wait()


@pytest.mark.integration
@pytest.mark.metered
async def test_deposit_wallet_transfers_with_only_the_session(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    integration_environment: Environment,
    submissions: list[httpx.Request],
) -> None:
    # Live side effect: transfers 1 base unit of collateral from the Deposit Wallet to its signer.
    client = await AsyncSecureClient.create(
        private_key=deposit_wallet_private_key,
        wallet=deposit_wallet_address,
        environment=integration_environment,
    )
    async with client:
        await _transfer_one_unit_to_signer(client, integration_environment)

    assert len(submissions) == 1
    request = submissions[0]
    assert request.headers.get("Authorization", "").startswith("Bearer ")
    assert "X-API-Key" not in request.headers
    assert _submission_key_headers(request) == []


@pytest.mark.integration
@pytest.mark.metered
async def test_deposit_wallet_transfers_under_a_platform_key_without_a_submission_key(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    platform_api_key: PlatformApiKey,
    integration_environment: Environment,
    submissions: list[httpx.Request],
) -> None:
    # Live side effect: transfers 1 base unit of collateral from the Deposit Wallet to its signer.
    client = await AsyncSecureClient.create(
        private_key=deposit_wallet_private_key,
        wallet=deposit_wallet_address,
        platform_api_key=platform_api_key,
        environment=integration_environment,
    )
    async with client:
        await _transfer_one_unit_to_signer(client, integration_environment)

    assert len(submissions) == 1
    request = submissions[0]
    assert request.headers.get("Authorization", "").startswith("Bearer ")
    assert _submission_key_headers(request) == []


@pytest.mark.integration
@pytest.mark.metered
async def test_async_secure_client_executes_gasless_transaction_for_proxy_wallet(
    builder_api_key: BuilderApiKey,
    proxy_wallet_private_key: str,
    proxy_wallet_address: str,
) -> None:
    # Live side effect: submits an ERC-20 approval as a representative gasless transaction.
    client = await AsyncSecureClient.create(
        private_key=proxy_wallet_private_key,
        wallet=proxy_wallet_address,
        api_key=builder_api_key,
    )
    async with client:
        assert client.wallet_type == "POLY_PROXY"
        handle = await client.approve_erc20(
            token_address=PRODUCTION_CONFIG.collateral_token,
            spender_address=PRODUCTION_CONFIG.standard_exchange,
            amount=1,
            metadata="Test legacy Proxy wallet gasless execution",
        )
        await handle.wait()


@pytest.mark.integration
@pytest.mark.metered
async def test_async_secure_client_executes_gasless_transaction_for_safe_wallet(
    builder_api_key: BuilderApiKey,
    safe_wallet_private_key: str,
    safe_wallet_address: str,
) -> None:
    # Live side effect: submits an ERC-20 approval as a representative gasless transaction.
    client = await AsyncSecureClient.create(
        private_key=safe_wallet_private_key,
        wallet=safe_wallet_address,
        api_key=builder_api_key,
    )
    async with client:
        assert client.wallet_type == "GNOSIS_SAFE"
        handle = await client.approve_erc20(
            token_address=PRODUCTION_CONFIG.collateral_token,
            spender_address=PRODUCTION_CONFIG.standard_exchange,
            amount=1,
            metadata="Test legacy Safe wallet gasless execution",
        )
        await handle.wait()


@pytest.mark.integration
@pytest.mark.metered
def test_sync_secure_client_executes_gasless_transaction_for_proxy_wallet(
    builder_api_key: BuilderApiKey,
    proxy_wallet_private_key: str,
    proxy_wallet_address: str,
) -> None:
    # Live side effect: submits an ERC-20 approval as a representative gasless transaction.
    with SecureClient.create(
        private_key=proxy_wallet_private_key,
        wallet=proxy_wallet_address,
        api_key=builder_api_key,
    ) as client:
        assert client.wallet_type == "POLY_PROXY"
        handle = client.approve_erc20(
            token_address=PRODUCTION_CONFIG.collateral_token,
            spender_address=PRODUCTION_CONFIG.standard_exchange,
            amount=1,
            metadata="Test legacy Proxy wallet sync gasless execution",
        )
        handle.wait()


@pytest.mark.integration
@pytest.mark.metered
def test_sync_secure_client_executes_gasless_transaction_for_safe_wallet(
    builder_api_key: BuilderApiKey,
    safe_wallet_private_key: str,
    safe_wallet_address: str,
) -> None:
    # Live side effect: submits an ERC-20 approval as a representative gasless transaction.
    with SecureClient.create(
        private_key=safe_wallet_private_key,
        wallet=safe_wallet_address,
        api_key=builder_api_key,
    ) as client:
        assert client.wallet_type == "GNOSIS_SAFE"
        handle = client.approve_erc20(
            token_address=PRODUCTION_CONFIG.collateral_token,
            spender_address=PRODUCTION_CONFIG.standard_exchange,
            amount=1,
            metadata="Test legacy Safe wallet sync gasless execution",
        )
        handle.wait()
