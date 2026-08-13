"""Live account-funding workflow coverage."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polymarket import (
    AsyncPublicClient,
    AsyncSecureClient,
    FundingTransaction,
    KnownFundingTransactionStatus,
    Page,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

_POLYGON_CHAIN_ID = 137
_POLYGON_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
_POLYGON_POLYMARKET_USDC = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
_DOCUMENTED_FUNDING_ADDRESS = "0x23566f8b2E82aDfCf01846E54899d110e97AC053"
_DEPOSIT_AMOUNT = 2_100_000
_WITHDRAWAL_AMOUNT = 2_000_000
_POLL_INTERVAL_SECONDS = 10.0
_TRANSFER_TIMEOUT_SECONDS = 600.0


async def _wait_for_funding_transfer(
    client: AsyncSecureClient,
    *,
    address: str,
    source_token: str,
    source_amount: int,
    destination_token: str,
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
                or transaction.destination_token_address.lower() != destination_token.lower()
            ):
                continue
            if transaction.status is KnownFundingTransactionStatus.FAILED:
                pytest.fail(f"bridge transfer failed for {address}")
            if transaction.status is KnownFundingTransactionStatus.COMPLETED:
                return transaction

        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(f"bridge transfer did not complete within the timeout for {address}")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def test_discovery_quote_and_paginated_status_live(
    public_client: AsyncPublicClient,
) -> None:
    catalog = await public_client.get_supported_funding_assets()
    assert catalog.assets
    asset = catalog.assets[0]
    assert asset.chain_id > 0
    assert asset.chain_name
    assert asset.token.symbol
    assert asset.minimum_amount_usd >= Decimal(0)

    quote = await public_client.get_funding_quote(
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
async def test_minimum_usdc_deposit_and_withdrawal_round_trip_live(
    deposit_wallet_client: AsyncSecureClient,
    builder_code: str,
) -> None:
    """Round-trip the minimum withdrawal; irreversibly spends bridge fees and moves funds.

    The configured wallet must hold at least 2.10 native Polygon USDC before the run.
    """
    client = deposit_wallet_client
    wallet = str(client.wallet)
    catalog = await client.get_supported_funding_assets()
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
    if Decimal(_DEPOSIT_AMOUNT) / 1_000_000 < native_usdc.minimum_amount_usd:
        pytest.skip("the deposit amount is below the current native USDC minimum")
    if Decimal(_WITHDRAWAL_AMOUNT) / 1_000_000 < pusd.minimum_amount_usd:
        pytest.skip("the withdrawal amount is below the current pUSD minimum")

    deposit = await client.create_deposit_addresses(builder_code=builder_code)
    withdrawal = await client.create_withdrawal_addresses(
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_USDC,
        recipient_address=wallet,
        builder_code=builder_code,
    )
    quote = await client.get_funding_quote(
        amount=_DEPOSIT_AMOUNT,
        source_chain_id=_POLYGON_CHAIN_ID,
        source_token_address=_POLYGON_USDC,
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_POLYMARKET_USDC,
        recipient_address=wallet,
    )
    withdrawal_quote = await client.get_funding_quote(
        amount=_WITHDRAWAL_AMOUNT,
        source_chain_id=_POLYGON_CHAIN_ID,
        source_token_address=_POLYGON_POLYMARKET_USDC,
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_USDC,
        recipient_address=wallet,
    )
    if (
        quote.estimated_fees.minimum_received < Decimal("2.05")
        or quote.estimated_destination_amount < _WITHDRAWAL_AMOUNT
        or withdrawal_quote.estimated_destination_amount < 1_950_000
        or withdrawal_quote.estimated_fees.minimum_received < Decimal("1.95")
    ):
        pytest.skip("current quotes cannot safely complete the minimum round trip")

    # Fund-moving side effects begin here: this moves at most 2.10 USDC into the bridge and
    # irreversibly spends its fees even if a later assertion fails.
    deposit_started_at = datetime.now(UTC) - timedelta(minutes=1)
    deposit_handle = await client.transfer_erc20(
        token_address=_POLYGON_USDC,
        recipient_address=str(deposit.addresses.evm),
        amount=_DEPOSIT_AMOUNT,
        metadata="py-sdk bridge integration test: minimum USDC deposit",
    )
    await deposit_handle.wait()
    await _wait_for_funding_transfer(
        client,
        address=str(deposit.addresses.evm),
        source_token=_POLYGON_USDC,
        source_amount=_DEPOSIT_AMOUNT,
        destination_token=_POLYGON_POLYMARKET_USDC,
        not_before=deposit_started_at,
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
        destination_token=_POLYGON_USDC,
        not_before=withdrawal_started_at,
    )
