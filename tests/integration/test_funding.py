"""Live account-funding workflow coverage."""

from decimal import Decimal

import pytest

from polymarket import AsyncPublicClient

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

_WALLET = "0x0000000000000000000000000000000000000001"
_POLYGON_CHAIN_ID = 137
_POLYGON_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
_POLYGON_POLYMARKET_USDC = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
_DOCUMENTED_FUNDING_ADDRESS = "0x23566f8b2E82aDfCf01846E54899d110e97AC053"


@pytest.mark.metered
async def test_create_deposit_addresses_live(public_client: AsyncPublicClient) -> None:
    """Creates provider-side address records but does not move or spend funds."""
    result = await public_client.create_deposit_addresses(wallet=_WALLET)

    assert result.addresses.evm
    assert result.addresses.svm
    assert result.addresses.btc


@pytest.mark.metered
async def test_create_withdrawal_addresses_live(public_client: AsyncPublicClient) -> None:
    """Creates provider-side address records but does not initiate a transfer."""
    result = await public_client.create_withdrawal_addresses(
        wallet=_WALLET,
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_USDC,
        recipient_address=_WALLET,
    )

    assert result.addresses.evm
    assert result.addresses.svm
    assert result.addresses.btc


async def test_get_supported_funding_assets_live(public_client: AsyncPublicClient) -> None:
    catalog = await public_client.get_supported_funding_assets()

    assert catalog.assets
    asset = catalog.assets[0]
    assert asset.chain_id > 0
    assert asset.chain_name
    assert asset.token.symbol
    assert asset.token.decimals >= 0
    assert asset.minimum_amount_usd >= Decimal(0)


async def test_get_funding_quote_live(public_client: AsyncPublicClient) -> None:
    quote = await public_client.get_funding_quote(
        amount=10_000_000,
        source_chain_id=_POLYGON_CHAIN_ID,
        source_token_address=_POLYGON_USDC,
        destination_chain_id=_POLYGON_CHAIN_ID,
        destination_token_address=_POLYGON_POLYMARKET_USDC,
        recipient_address=_WALLET,
    )

    assert quote.quote_id
    assert quote.estimated_destination_amount > 0
    assert quote.estimated_checkout_time.total_seconds() >= 0


async def test_get_funding_transactions_live(public_client: AsyncPublicClient) -> None:
    transactions = await public_client.get_funding_transactions(address=_DOCUMENTED_FUNDING_ADDRESS)

    assert transactions
    transaction = transactions[0]
    assert transaction.source_chain_id > 0
    assert transaction.source_token_address
    assert transaction.source_amount >= 0
    assert transaction.destination_chain_id > 0
    assert transaction.destination_token_address
    assert transaction.status
