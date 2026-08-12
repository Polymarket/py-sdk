# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import inspect
import json
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from polymarket import (
    ApiKeyCreds,
    AsyncPublicClient,
    AsyncSecureClient,
    FundingAddressSet,
    FundingAssetCatalog,
    FundingQuote,
    FundingTransaction,
    KnownFundingTransactionStatus,
    PublicClient,
    SecureClient,
)
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket.clients._transport import AsyncTransport, SyncTransport

_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
_BOUND_WALLET = "0xBc0fF067b7740Eff76C1ca93c875Ba6B890d6B50"
_PUBLIC_WALLET = "0x52908400098527886e0f7030069857d2e4169ee7"
_PUBLIC_WALLET_CHECKSUM = "0x52908400098527886E0F7030069857D2E4169EE7"
_BUILDER_CODE = "0x" + "ab" * 32
_SOURCE_TOKEN = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
_DESTINATION_TOKEN = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
_TRON_TOKEN = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
_TRON_RECIPIENT = "TP1mjRAUVe5qXfCnpczdWhSrGpos2Arzir"
_FAKE_CREDS = ApiKeyCreds(
    key="test-key",
    passphrase="test-passphrase",
    secret="dGVzdA==",
)

_ADDRESS_SET_PAYLOAD: dict[str, object] = {
    "address": {
        "evm": _PUBLIC_WALLET_CHECKSUM,
        "svm": "CrvTBvzryYxBHbWu2TiQpcqD5M7Le7iBKzVmEj3f36Jb",
        "btc": "bc1q8eau83qffxcj8ht4hsjdza3lha9r3egfqysj3g",
        "tron": _TRON_RECIPIENT,
    }
}
_ASSET_CATALOG_PAYLOAD: dict[str, object] = {
    "supportedAssets": [
        {
            "chainId": "137",
            "chainName": "Polygon",
            "token": {
                "name": "USD Coin",
                "symbol": "USDC.e",
                "address": _DESTINATION_TOKEN,
                "decimals": 6,
            },
            "minCheckoutUsd": "5",
        }
    ]
}
_QUOTE_PAYLOAD: dict[str, object] = {
    "estCheckoutTimeMs": 25_000,
    "estFeeBreakdown": {
        "appFeeLabel": "Fun.xyz fee",
        "appFeePercent": 0,
        "appFeeUsd": 0,
        "fillCostPercent": 0,
        "fillCostUsd": 0,
        "gasUsd": "0.01",
        "maxSlippage": "0.5",
        "minReceived": "9.9",
        "swapImpact": 0,
        "swapImpactUsd": 0,
        "totalImpact": 0,
        "totalImpactUsd": 0,
    },
    "estInputUsd": "10",
    "estOutputUsd": "9.99",
    "estToTokenBaseUnit": "9990000",
    "quoteId": "quote-1",
}
_TRANSACTIONS_PAYLOAD: dict[str, object] = {
    "transactions": [
        {
            "fromChainId": "1",
            "fromTokenAddress": _SOURCE_TOKEN,
            "fromAmountBaseUnit": "10000000",
            "toChainId": "137",
            "toTokenAddress": _DESTINATION_TOKEN,
            "status": "COMPLETED",
        }
    ]
}


def _bridge_handler(captured: list[httpx.Request]) -> httpx.MockTransport:
    responses: dict[tuple[str, str], dict[str, object]] = {
        ("POST", "/deposit"): _ADDRESS_SET_PAYLOAD,
        ("POST", "/withdraw"): _ADDRESS_SET_PAYLOAD,
        ("GET", "/supported-assets"): _ASSET_CATALOG_PAYLOAD,
        ("POST", "/quote"): _QUOTE_PAYLOAD,
        ("GET", f"/status/{_PUBLIC_WALLET_CHECKSUM}"): _TRANSACTIONS_PAYLOAD,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        route = (request.method, urlparse(str(request.url)).path)
        payload = responses.get(route)
        if payload is None:
            raise AssertionError(f"Unexpected funding request: {route!r}")
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


def _install_sync_bridge(
    client: PublicClient | SecureClient,
    handler: httpx.MockTransport,
) -> httpx.Client:
    http_client = httpx.Client(base_url="https://bridge.test", transport=handler)
    bridge = SyncTransport(base_url="https://bridge.test", client=http_client)
    bridge._owns_client = True
    client._ctx.bridge.close()
    client._ctx = cast(
        SyncSecureClientContext,
        dataclasses.replace(client._ctx, bridge=bridge),
    )
    return http_client


async def _install_async_bridge(
    client: AsyncPublicClient | AsyncSecureClient,
    handler: httpx.MockTransport,
) -> httpx.AsyncClient:
    http_client = httpx.AsyncClient(base_url="https://bridge.test", transport=handler)
    bridge = AsyncTransport(base_url="https://bridge.test", client=http_client)
    bridge._owns_client = True
    await client._ctx.bridge.close()
    client._ctx = cast(
        AsyncSecureClientContext,
        dataclasses.replace(client._ctx, bridge=bridge),
    )
    return http_client


def _assert_public_results(
    deposit: FundingAddressSet,
    withdrawal: FundingAddressSet,
    catalog: FundingAssetCatalog,
    quote: FundingQuote,
    transactions: tuple[FundingTransaction, ...],
) -> None:
    assert deposit.addresses.tron == _TRON_RECIPIENT
    assert withdrawal.addresses.evm == _PUBLIC_WALLET_CHECKSUM
    assert catalog.assets[0].chain_id == 137
    assert quote.quote_id == "quote-1"
    assert len(transactions) == 1
    assert transactions[0].status is KnownFundingTransactionStatus.COMPLETED


def _assert_public_requests(captured: list[httpx.Request]) -> None:
    assert [(request.method, urlparse(str(request.url)).path) for request in captured] == [
        ("POST", "/deposit"),
        ("POST", "/withdraw"),
        ("GET", "/supported-assets"),
        ("POST", "/quote"),
        ("GET", f"/status/{_PUBLIC_WALLET_CHECKSUM}"),
    ]
    assert all(request.url.host == "bridge.test" for request in captured)
    assert json.loads(captured[0].content) == {"address": _PUBLIC_WALLET_CHECKSUM}
    assert captured[0].headers["X-Builder-Code"] == _BUILDER_CODE
    assert json.loads(captured[1].content) == {
        "address": _PUBLIC_WALLET_CHECKSUM,
        "toChainId": "728126428",
        "toTokenAddress": _TRON_TOKEN,
        "recipientAddr": _TRON_RECIPIENT,
    }
    assert captured[1].headers["X-Builder-Code"] == _BUILDER_CODE
    assert captured[2].content == b""
    assert json.loads(captured[3].content) == {
        "fromAmountBaseUnit": "10000000",
        "fromChainId": "137",
        "fromTokenAddress": _SOURCE_TOKEN,
        "recipientAddress": _PUBLIC_WALLET_CHECKSUM,
        "toChainId": "137",
        "toTokenAddress": _DESTINATION_TOKEN,
    }
    assert "X-Builder-Code" not in captured[3].headers
    assert captured[4].content == b""


def _public_funding_args() -> dict[str, Any]:
    return {
        "amount": 10_000_000,
        "source_chain_id": 137,
        "source_token_address": _SOURCE_TOKEN,
        "destination_chain_id": 137,
        "destination_token_address": _DESTINATION_TOKEN,
        "recipient_address": _PUBLIC_WALLET_CHECKSUM,
    }


def test_sync_public_funding_calls_use_bridge_transport_and_close_it() -> None:
    captured: list[httpx.Request] = []

    with PublicClient() as client:
        bridge_client = _install_sync_bridge(client, _bridge_handler(captured))
        deposit = client.create_deposit_addresses(
            wallet=_PUBLIC_WALLET,
            builder_code=_BUILDER_CODE,
        )
        withdrawal = client.create_withdrawal_addresses(
            wallet=_PUBLIC_WALLET,
            destination_chain_id=728126428,
            destination_token_address=_TRON_TOKEN,
            recipient_address=_TRON_RECIPIENT,
            builder_code=_BUILDER_CODE,
        )
        catalog = client.get_supported_funding_assets()
        quote = client.get_funding_quote(**_public_funding_args())
        transactions = client.get_funding_transactions(address=_PUBLIC_WALLET_CHECKSUM)

    assert bridge_client.is_closed
    _assert_public_results(deposit, withdrawal, catalog, quote, transactions)
    _assert_public_requests(captured)


def test_async_public_funding_calls_use_bridge_transport_and_close_it() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[
        FundingAddressSet,
        FundingAddressSet,
        FundingAssetCatalog,
        FundingQuote,
        tuple[FundingTransaction, ...],
        httpx.AsyncClient,
    ]:
        async with AsyncPublicClient() as client:
            bridge_client = await _install_async_bridge(client, _bridge_handler(captured))
            deposit = await client.create_deposit_addresses(
                wallet=_PUBLIC_WALLET,
                builder_code=_BUILDER_CODE,
            )
            withdrawal = await client.create_withdrawal_addresses(
                wallet=_PUBLIC_WALLET,
                destination_chain_id=728126428,
                destination_token_address=_TRON_TOKEN,
                recipient_address=_TRON_RECIPIENT,
                builder_code=_BUILDER_CODE,
            )
            catalog = await client.get_supported_funding_assets()
            quote = await client.get_funding_quote(**_public_funding_args())
            transactions = await client.get_funding_transactions(address=_PUBLIC_WALLET_CHECKSUM)
        return deposit, withdrawal, catalog, quote, transactions, bridge_client

    deposit, withdrawal, catalog, quote, transactions, bridge_client = asyncio.run(run())

    assert bridge_client.is_closed
    _assert_public_results(deposit, withdrawal, catalog, quote, transactions)
    _assert_public_requests(captured)


def _assert_secure_address_requests(
    captured: list[httpx.Request],
    *,
    wallet: str,
) -> None:
    assert [(request.method, urlparse(str(request.url)).path) for request in captured] == [
        ("POST", "/deposit"),
        ("POST", "/withdraw"),
    ]
    assert all(request.url.host == "bridge.test" for request in captured)
    assert json.loads(captured[0].content) == {"address": wallet}
    assert json.loads(captured[1].content) == {
        "address": wallet,
        "toChainId": "728126428",
        "toTokenAddress": _TRON_TOKEN,
        "recipientAddr": _TRON_RECIPIENT,
    }
    assert all(request.headers["X-Builder-Code"] == _BUILDER_CODE for request in captured)


def test_sync_secure_address_creation_uses_only_bound_wallet() -> None:
    assert "wallet" not in inspect.signature(SecureClient.create_deposit_addresses).parameters
    assert "wallet" not in inspect.signature(SecureClient.create_withdrawal_addresses).parameters
    captured: list[httpx.Request] = []

    with SecureClient._create(
        private_key=_PRIVATE_KEY,
        wallet=_BOUND_WALLET,
        credentials=_FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        assert client.wallet != client.signer
        bound_wallet = str(client.wallet)
        bridge_client = _install_sync_bridge(client, _bridge_handler(captured))
        deposit = client.create_deposit_addresses(builder_code=_BUILDER_CODE)
        withdrawal = client.create_withdrawal_addresses(
            destination_chain_id=728126428,
            destination_token_address=_TRON_TOKEN,
            recipient_address=_TRON_RECIPIENT,
            builder_code=_BUILDER_CODE,
        )

    assert bridge_client.is_closed
    assert isinstance(deposit, FundingAddressSet)
    assert isinstance(withdrawal, FundingAddressSet)
    _assert_secure_address_requests(captured, wallet=bound_wallet)


def test_async_secure_address_creation_uses_only_bound_wallet() -> None:
    assert "wallet" not in inspect.signature(AsyncSecureClient.create_deposit_addresses).parameters
    assert (
        "wallet" not in inspect.signature(AsyncSecureClient.create_withdrawal_addresses).parameters
    )
    captured: list[httpx.Request] = []

    async def run() -> tuple[str, FundingAddressSet, FundingAddressSet, httpx.AsyncClient]:
        client = await AsyncSecureClient._create(
            private_key=_PRIVATE_KEY,
            wallet=_BOUND_WALLET,
            credentials=_FAKE_CREDS,
            validate_credentials=False,
        )
        async with client:
            assert client.wallet != client.signer
            bound_wallet = str(client.wallet)
            bridge_client = await _install_async_bridge(client, _bridge_handler(captured))
            deposit = await client.create_deposit_addresses(builder_code=_BUILDER_CODE)
            withdrawal = await client.create_withdrawal_addresses(
                destination_chain_id=728126428,
                destination_token_address=_TRON_TOKEN,
                recipient_address=_TRON_RECIPIENT,
                builder_code=_BUILDER_CODE,
            )
        return bound_wallet, deposit, withdrawal, bridge_client

    bound_wallet, deposit, withdrawal, bridge_client = asyncio.run(run())

    assert bridge_client.is_closed
    assert isinstance(deposit, FundingAddressSet)
    assert isinstance(withdrawal, FundingAddressSet)
    _assert_secure_address_requests(captured, wallet=bound_wallet)
