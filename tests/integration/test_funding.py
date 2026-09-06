"""Live account-funding workflow coverage."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polymarket import (
    PRODUCTION,
    AsyncPublicClient,
    AsyncSecureClient,
    FundingTransaction,
    KnownFundingTransactionStatus,
    Page,
    RequestRejectedError,
    TransactionHandle,
)
from polymarket._internal.environment import get_environment_config

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

_POLYGON_CHAIN_ID = 137
_POLYGON_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
_POLYGON_POLYMARKET_USDC = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
_DOCUMENTED_FUNDING_ADDRESS = "0x23566f8b2E82aDfCf01846E54899d110e97AC053"
_WITHDRAWAL_AMOUNT = 2_100_000
_RETURN_DEPOSIT_AMOUNT = 2_000_000
_MIN_RETURN_COLLATERAL_AMOUNT = 1_950_000
_PRODUCTION_BRIDGE_URL = "https://bridge.polymarket.com"
_POLL_INTERVAL_SECONDS = 10.0
_TRANSFER_TIMEOUT_SECONDS = 600.0
_SETTLEMENT_RETRY_TIMEOUT_SECONDS = 120.0


async def _wait_for_funding_transfer(
    client: AsyncSecureClient,
    *,
    address: str,
    source_token: str,
    source_amount: int,
    not_before: datetime,
) -> FundingTransaction:
    """Poll the newest status page until the expected transfer is terminal."""
    deadline = asyncio.get_running_loop().time() + _TRANSFER_TIMEOUT_SECONDS
    while True:
        page = await client.list_funding_transactions(address=address).first_page()
        for transaction in page.items:
            if (
                transaction.created_at is None
                or transaction.created_at < not_before
                or transaction.source_chain_id != _POLYGON_CHAIN_ID
                or transaction.source_token_address.lower() != source_token.lower()
                or transaction.source_amount != source_amount
                or transaction.destination_chain_id != _POLYGON_CHAIN_ID
            ):
                continue
            if transaction.status is KnownFundingTransactionStatus.FAILED:
                pytest.fail(f"bridge transfer failed for {address}")
            if transaction.status is KnownFundingTransactionStatus.COMPLETED:
                return transaction

        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(f"bridge transfer did not complete within the timeout for {address}")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def _transfer_after_funding_settlement(
    client: AsyncSecureClient,
    *,
    token_address: str,
    recipient_address: str,
    amount: int,
    metadata: str,
) -> TransactionHandle:
    """Retry the explicit relayer simulation race after bridge completion."""
    deadline = asyncio.get_running_loop().time() + _SETTLEMENT_RETRY_TIMEOUT_SECONDS
    last_error: RequestRejectedError | None = None
    while True:
        try:
            return await client.transfer_erc20(
                token_address=token_address,
                recipient_address=recipient_address,
                amount=amount,
                metadata=metadata,
            )
        except RequestRejectedError as error:
            if error.status != 400 or "batch would revert" not in str(error).lower():
                raise
            last_error = error

        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(
                "withdrawn native USDC did not become spendable before the retry deadline"
            ) from last_error
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def _wait_for_collateral_balance(
    client: AsyncSecureClient,
    *,
    minimum_balance: int,
) -> int:
    """Wait until the completed return leg is visible in the user's CLOB balance."""
    deadline = asyncio.get_running_loop().time() + _TRANSFER_TIMEOUT_SECONDS
    while True:
        balance = await client.get_balance_allowance(asset_type="COLLATERAL")
        if balance.balance >= minimum_balance:
            return balance.balance
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(
                "returned pUSD did not appear in the user-visible collateral balance "
                f"before timeout (expected at least {minimum_balance}, saw {balance.balance})"
            )
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def test_discovery_quote_and_paginated_status_live(
    public_client: AsyncPublicClient,
) -> None:
    catalog = await public_client.fetch_supported_funding_assets()
    assert catalog.assets
    asset = catalog.assets[0]
    assert asset.chain_id > 0
    assert asset.chain_name
    assert asset.token.symbol
    assert asset.minimum_amount_usd >= Decimal(0)

    quote = await public_client.fetch_funding_quote(
        amount=10_000_000,
        source_chain_id=_POLYGON_CHAIN_ID,
        source_token_address=_POLYGON_USDC,
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_POLYMARKET_USDC,
        recipient_address="0x0000000000000000000000000000000000000001",
    )
    assert quote.quote_id
    assert quote.estimated_destination_amount > 0
    assert quote.estimated_checkout_time.total_seconds() >= 0

    paginator = public_client.list_funding_transactions(
        address=_DOCUMENTED_FUNDING_ADDRESS,
        page_size=1,
    )
    pages: list[Page[FundingTransaction]] = []
    async for page in paginator:
        pages.append(page)
        if page.has_more:
            assert len(page.items) <= 1
            assert page.next_cursor is not None

    assert pages
    assert any(page.items for page in pages)
    assert pages[-1].has_more is False
    assert pages[-1].next_cursor is None


@pytest.mark.metered
async def test_minimum_pusd_withdrawal_and_deposit_round_trip_live(
    deposit_wallet_client: AsyncSecureClient,
    builder_code: str,
) -> None:
    """Withdraw 2.10 pUSD, then return 2.00 USDC; bridge fees are irreversible.

    The configured wallet must hold at least 2.10 pUSD before the run. A passing
    run ends with the returned collateral visible in the user's CLOB balance.
    """
    client = deposit_wallet_client
    wallet = str(client.wallet)
    config = get_environment_config(client.environment)
    if (
        client.environment != PRODUCTION
        or config.chain_id != _POLYGON_CHAIN_ID
        or config.bridge_url != _PRODUCTION_BRIDGE_URL
        or config.collateral_token.lower() != _POLYGON_POLYMARKET_USDC.lower()
    ):
        pytest.skip("the metered funding round trip is restricted to Polygon production")

    catalog = await client.fetch_supported_funding_assets()
    native_usdc = next(
        (
            asset
            for asset in catalog.assets
            if asset.chain_id == _POLYGON_CHAIN_ID
            and asset.token.address.lower() == _POLYGON_USDC.lower()
        ),
        None,
    )
    pusd = next(
        (
            asset
            for asset in catalog.assets
            if asset.chain_id == _POLYGON_CHAIN_ID
            and asset.token.address.lower() == _POLYGON_POLYMARKET_USDC.lower()
        ),
        None,
    )
    if native_usdc is None or pusd is None:
        pytest.skip("required Polygon funding assets are unavailable")
    if native_usdc.token.decimals != 6 or pusd.token.decimals != 6:
        pytest.skip("the metered amounts require six-decimal Polygon funding assets")
    if Decimal(_WITHDRAWAL_AMOUNT) / 1_000_000 < pusd.minimum_amount_usd:
        pytest.skip("the withdrawal amount is below the current pUSD minimum")
    if Decimal(_RETURN_DEPOSIT_AMOUNT) / 1_000_000 < native_usdc.minimum_amount_usd:
        pytest.skip("the return deposit is below the current native USDC minimum")

    initial_collateral = await client.get_balance_allowance(asset_type="COLLATERAL")
    if initial_collateral.balance < _WITHDRAWAL_AMOUNT:
        pytest.skip("the integration wallet has insufficient pUSD for the round trip")

    withdrawal_quote = await client.fetch_funding_quote(
        amount=_WITHDRAWAL_AMOUNT,
        source_chain_id=_POLYGON_CHAIN_ID,
        source_token_address=_POLYGON_POLYMARKET_USDC,
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_USDC,
        recipient_address=wallet,
    )
    return_preflight_quote = await client.fetch_funding_quote(
        amount=_RETURN_DEPOSIT_AMOUNT,
        source_chain_id=_POLYGON_CHAIN_ID,
        source_token_address=_POLYGON_USDC,
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_POLYMARKET_USDC,
        recipient_address=wallet,
    )
    if (
        withdrawal_quote.estimated_destination_amount < _RETURN_DEPOSIT_AMOUNT
        or withdrawal_quote.estimated_fees.minimum_received < Decimal("2")
        or return_preflight_quote.estimated_destination_amount < _MIN_RETURN_COLLATERAL_AMOUNT
        or return_preflight_quote.estimated_fees.minimum_received < Decimal("1.95")
    ):
        pytest.skip("current quotes cannot safely complete the minimum round trip")

    # Fund-moving side effects begin here. The hard caps are the two constant
    # transfer amounts above; fees remain spent if any later assertion fails.
    withdrawal = await client.create_withdrawal_addresses(
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_USDC,
        recipient_address=wallet,
        builder_code=builder_code,
    )
    withdrawal_started_at = datetime.now(UTC) - timedelta(minutes=1)
    withdrawal_handle = await client.transfer_erc20(
        token_address=_POLYGON_POLYMARKET_USDC,
        recipient_address=str(withdrawal.addresses.evm),
        amount=_WITHDRAWAL_AMOUNT,
        metadata="py-sdk bridge integration test: minimum USDC withdrawal",
    )
    await withdrawal_handle.wait()
    await _wait_for_funding_transfer(
        client,
        address=str(withdrawal.addresses.evm),
        source_token=_POLYGON_POLYMARKET_USDC,
        source_amount=_WITHDRAWAL_AMOUNT,
        not_before=withdrawal_started_at,
    )

    return_quote = await client.fetch_funding_quote(
        amount=_RETURN_DEPOSIT_AMOUNT,
        source_chain_id=_POLYGON_CHAIN_ID,
        source_token_address=_POLYGON_USDC,
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_POLYMARKET_USDC,
        recipient_address=wallet,
    )
    if (
        return_quote.estimated_destination_amount < _MIN_RETURN_COLLATERAL_AMOUNT
        or return_quote.estimated_fees.minimum_received < Decimal("1.95")
    ):
        pytest.fail("the refreshed return quote is unsafe; withdrawn USDC was not deposited")

    deposit = await client.create_deposit_addresses(builder_code=builder_code)
    deposit_started_at = datetime.now(UTC) - timedelta(minutes=1)
    deposit_handle = await _transfer_after_funding_settlement(
        client,
        token_address=_POLYGON_USDC,
        recipient_address=str(deposit.addresses.evm),
        amount=_RETURN_DEPOSIT_AMOUNT,
        metadata="py-sdk bridge integration test: return withdrawn native USDC",
    )
    await deposit_handle.wait()
    await _wait_for_funding_transfer(
        client,
        address=str(deposit.addresses.evm),
        source_token=_POLYGON_USDC,
        source_amount=_RETURN_DEPOSIT_AMOUNT,
        not_before=deposit_started_at,
    )

    minimum_final_collateral = (
        initial_collateral.balance - _WITHDRAWAL_AMOUNT + _MIN_RETURN_COLLATERAL_AMOUNT
    )
    final_collateral = await _wait_for_collateral_balance(
        client,
        minimum_balance=minimum_final_collateral,
    )
    assert final_collateral >= minimum_final_collateral
