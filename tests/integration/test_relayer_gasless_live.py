import pytest

from polymarket import AsyncSecureClient, BuilderApiKey, SecureClient
from polymarket._internal.environment import PRODUCTION_CONFIG

pytestmark = pytest.mark.anyio


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
