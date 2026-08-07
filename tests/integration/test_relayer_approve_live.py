# pyright: reportPrivateUsage=false
import asyncio
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient, BuilderApiKey, GaslessTransaction
from polymarket._internal.environment import get_environment_config
from polymarket.environments import PRODUCTION


def _builder_auth(require_env: Callable[[str], str]) -> BuilderApiKey:
    return BuilderApiKey(
        key=require_env("POLYMARKET_BUILDER_API_KEY"),
        secret=require_env("POLYMARKET_BUILDER_SECRET"),
        passphrase=require_env("POLYMARKET_BUILDER_PASSPHRASE"),
    )


def _existing_user_credentials() -> ApiKeyCreds | None:
    k = os.environ.get("POLYMARKET_TEST_API_KEY")
    s = os.environ.get("POLYMARKET_TEST_API_SECRET")
    p = os.environ.get("POLYMARKET_TEST_API_PASSPHRASE")
    if k and s and p:
        return ApiKeyCreds(key=k, secret=s, passphrase=p)
    return None


@asynccontextmanager
async def _secure_client(
    require_env: Callable[[str], str],
) -> AsyncGenerator[AsyncSecureClient, None]:
    client = await AsyncSecureClient.create(
        private_key=require_env("POLYMARKET_PRIVATE_KEY"),
        wallet=require_env("POLYMARKET_DEPOSIT_WALLET"),
        credentials=_existing_user_credentials(),
        api_key=_builder_auth(require_env),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.mark.integration
@pytest.mark.metered
def test_fetch_relayer_nonce_with_builder_auth(
    require_env: Callable[[str], str],
) -> None:
    from polymarket._internal.actions.relayer.nonce import fetch_execute_params
    from polymarket.models.clob.relayer import RelayerTransactionType

    async def run() -> str:
        async with _secure_client(require_env) as client:
            wt = (
                RelayerTransactionType.WALLET
                if client.wallet_type == "DEPOSIT_WALLET"
                else RelayerTransactionType.PROXY
                if client.wallet_type == "POLY_PROXY"
                else RelayerTransactionType.SAFE
            )
            params = await fetch_execute_params(client._ctx.relayer, address=client.signer, type=wt)
            assert params.nonce.isdigit()
            return params.nonce

    asyncio.run(asyncio.wait_for(run(), timeout=30.0))


@pytest.mark.integration
def test_secure_client_create_defaults_to_deposit_wallet(
    require_env: Callable[[str], str],
) -> None:
    async def run() -> None:
        expected_wallet = require_env("POLYMARKET_DEPOSIT_WALLET")
        client = await AsyncSecureClient.create(
            private_key=require_env("POLYMARKET_PRIVATE_KEY"),
            credentials=_existing_user_credentials(),
        )
        try:
            assert client.wallet_type == "DEPOSIT_WALLET"
            assert str(client.wallet).lower() == expected_wallet.lower()
        finally:
            await client.close()

    asyncio.run(asyncio.wait_for(run(), timeout=30.0))


_SKIP_REASON = (
    "Requires a Builder/Relayer API Key authorized to submit for the test wallet's "
    "signer. Enable when authorized credentials are available."
)


@pytest.mark.integration
@pytest.mark.metered
@pytest.mark.skip(reason=_SKIP_REASON)
def test_approve_erc20_live_against_relayer(
    require_env: Callable[[str], str],
) -> None:
    async def run() -> GaslessTransaction:
        async with _secure_client(require_env) as client:
            handle = await client.approve_erc20(
                token_address=get_environment_config(PRODUCTION).collateral_token,
                spender_address=get_environment_config(PRODUCTION).standard_exchange,
                amount=1,
                metadata="py-sdk integration test: approve_erc20",
            )
            outcome = await handle.wait()
            assert outcome.transaction_id
            assert outcome.transaction_hash.startswith("0x")
            return outcome  # type: ignore[return-value]

    asyncio.run(asyncio.wait_for(run(), timeout=240.0))


@pytest.mark.integration
@pytest.mark.metered
@pytest.mark.skip(reason=_SKIP_REASON)
def test_approve_erc1155_for_all_live(require_env: Callable[[str], str]) -> None:
    async def run() -> None:
        async with _secure_client(require_env) as client:
            handle = await client.approve_erc1155_for_all(
                token_address=get_environment_config(PRODUCTION).conditional_tokens,
                operator_address=get_environment_config(PRODUCTION).standard_exchange,
                metadata="py-sdk integration test: approve_erc1155_for_all",
            )
            await handle.wait()

    asyncio.run(asyncio.wait_for(run(), timeout=240.0))


@pytest.mark.integration
@pytest.mark.metered
def test_setup_trading_approvals_live(
    builder_api_key: BuilderApiKey,
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
) -> None:
    async def run() -> None:
        client = await AsyncSecureClient.create(
            private_key=deposit_wallet_private_key,
            wallet=deposit_wallet_address,
            api_key=builder_api_key,
        )
        async with client:
            # Live side effect: submits any missing trading approvals for the configured wallet.
            handle = await client.setup_trading_approvals()
            await handle.wait()

    asyncio.run(asyncio.wait_for(run(), timeout=240.0))


@pytest.mark.integration
@pytest.mark.metered
@pytest.mark.skip(reason=_SKIP_REASON)
def test_transfer_erc20_live(require_env: Callable[[str], str]) -> None:
    async def run() -> None:
        async with _secure_client(require_env) as client:
            handle = await client.transfer_erc20(
                token_address=get_environment_config(PRODUCTION).collateral_token,
                recipient_address=str(client.wallet),
                amount=1,
                metadata="py-sdk integration test: self-transfer",
            )
            await handle.wait()

    asyncio.run(asyncio.wait_for(run(), timeout=240.0))


@pytest.mark.integration
@pytest.mark.metered
@pytest.mark.skip(reason=_SKIP_REASON)
def test_split_position_live(require_env: Callable[[str], str]) -> None:
    async def run() -> None:
        async with _secure_client(require_env) as client:
            handle = await client.split_position(
                condition_id=require_env("POLYMARKET_TEST_CONDITION_ID"),
                amount=1_000_000,
                metadata="py-sdk integration test: split_position",
            )
            await handle.wait()

    asyncio.run(asyncio.wait_for(run(), timeout=240.0))


@pytest.mark.integration
@pytest.mark.metered
@pytest.mark.skip(reason=_SKIP_REASON)
def test_merge_positions_live(require_env: Callable[[str], str]) -> None:
    async def run() -> None:
        async with _secure_client(require_env) as client:
            handle = await client.merge_positions(
                condition_id=require_env("POLYMARKET_TEST_CONDITION_ID"),
                amount="max",
                metadata="py-sdk integration test: merge_positions",
            )
            await handle.wait()

    asyncio.run(asyncio.wait_for(run(), timeout=240.0))


@pytest.mark.integration
@pytest.mark.metered
@pytest.mark.skip(reason=_SKIP_REASON)
def test_redeem_positions_live(require_env: Callable[[str], str]) -> None:
    async def run() -> None:
        async with _secure_client(require_env) as client:
            handle = await client.redeem_positions(
                condition_id=require_env("POLYMARKET_TEST_CONDITION_ID"),
                metadata="py-sdk integration test: redeem_positions",
            )
            await handle.wait()

    asyncio.run(asyncio.wait_for(run(), timeout=240.0))
