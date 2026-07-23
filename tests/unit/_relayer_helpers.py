# pyright: reportPrivateUsage=false
from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Iterator
from typing import Any, cast
from urllib.parse import urlparse

import httpx
from eth_utils.crypto import keccak

from polymarket import ApiKeyCreds, AsyncSecureClient, BuilderApiKey, SecureClient
from polymarket.clients._transport import AsyncTransport

PK_DEPLOY_WALLET = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
PK_PROXY_WALLET = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
PK_SAFE_WALLET = "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"

FAKE_CREDS = ApiKeyCreds(key="k", passphrase="p", secret="dGVzdA==")
BUILDER_AUTH = BuilderApiKey(key="bk", secret="dGVzdA==", passphrase="bp")

TOKEN = "0xDDeeAa11220000000000000000000000000000aA"
SPENDER = "0x000000000000000000000000000000000000dEaD"


async def make_deposit_client() -> AsyncSecureClient:
    from eth_account import Account

    from polymarket._internal.wallet import derive_uups_deposit_wallet_address
    from polymarket.environments import PRODUCTION

    signer = Account.from_key(PK_DEPLOY_WALLET)
    wallet = derive_uups_deposit_wallet_address(signer.address, PRODUCTION.wallet_derivation)
    return await AsyncSecureClient._create(
        private_key=PK_DEPLOY_WALLET,
        wallet=wallet,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH,
        validate_credentials=False,
    )


async def make_proxy_client() -> AsyncSecureClient:
    from eth_account import Account

    from polymarket._internal.wallet import derive_proxy_wallet_address
    from polymarket.environments import PRODUCTION

    signer = Account.from_key(PK_PROXY_WALLET)
    wallet = derive_proxy_wallet_address(signer.address, PRODUCTION.wallet_derivation)
    return await AsyncSecureClient._create(
        private_key=PK_PROXY_WALLET,
        wallet=wallet,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH,
        validate_credentials=False,
    )


async def make_eoa_client(*, with_api_key: bool = True) -> AsyncSecureClient:
    from eth_account import Account

    signer = Account.from_key(PK_DEPLOY_WALLET)
    return await AsyncSecureClient._create(
        private_key=PK_DEPLOY_WALLET,
        wallet=signer.address,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH if with_api_key else None,
        validate_credentials=False,
    )


async def make_eoa_client_with_rpc(
    *, rpc_handler: Callable[[httpx.Request], httpx.Response]
) -> AsyncSecureClient:
    from eth_account import Account

    from polymarket._internal.eoa.rpc import JsonRpcClient
    from polymarket.environments import PRODUCTION

    env = dataclasses.replace(PRODUCTION, rpc_url="https://rpc.test")
    signer = Account.from_key(PK_DEPLOY_WALLET)
    client = await AsyncSecureClient._create(
        private_key=PK_DEPLOY_WALLET,
        wallet=signer.address,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH,
        environment=env,
        validate_credentials=False,
    )
    rpc_transport = AsyncTransport(
        base_url="https://rpc.test",
        client=httpx.AsyncClient(
            base_url="https://rpc.test", transport=httpx.MockTransport(rpc_handler)
        ),
    )
    client._ctx = dataclasses.replace(client._ctx, rpc=JsonRpcClient(rpc_transport))
    return client


def make_rpc_handler(
    *,
    nonce: int = 7,
    gas_price: int = 30_000_000_000,
    gas_estimate: int = 100_000,
    send_response: str | None = None,
    receipt_responses: list[dict[str, object] | None] | None = None,
    chain_id: int = 137,
) -> Callable[[httpx.Request], httpx.Response]:
    captured: list[object] = []
    receipt_iter = iter(receipt_responses or [])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured.append(body)
        method = body["method"]
        if method == "eth_chainId":
            result: object = hex(chain_id)
        elif method == "eth_getTransactionCount":
            result = hex(nonce)
        elif method == "eth_gasPrice":
            result = hex(gas_price)
        elif method == "eth_estimateGas":
            result = hex(gas_estimate)
        elif method == "eth_sendRawTransaction":
            result = send_response or ("0x" + "ab" * 32)
        elif method == "eth_getTransactionReceipt":
            try:
                result = next(receipt_iter)
            except StopIteration:
                result = None
        else:
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "error": {"message": "unmocked"}},
                request=request,
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": result},
            request=request,
        )

    handler.captured = captured  # type: ignore[attr-defined]
    return handler


def trading_approval_rpc_handler(
    *,
    allowance: int = 0,
    approved: bool = False,
    nonce: int = 7,
    gas_price: int = 30_000_000_000,
    gas_estimate: int = 100_000,
    send_response: str | None = None,
    receipt_responses: list[dict[str, object] | None] | None = None,
    chain_id: int = 137,
) -> Callable[[httpx.Request], httpx.Response]:
    captured: list[object] = []
    receipt_iter = iter(receipt_responses or [])

    def handler(request: httpx.Request) -> httpx.Response:
        body = cast(object, json.loads(request.content.decode("utf-8")))
        captured.append(body)

        if isinstance(body, list):
            return httpx.Response(
                200,
                json=[
                    _trading_approval_rpc_response(
                        item,
                        allowance=allowance,
                        approved=approved,
                        nonce=nonce,
                        gas_price=gas_price,
                        gas_estimate=gas_estimate,
                        send_response=send_response,
                        receipt_iter=receipt_iter,
                        chain_id=chain_id,
                    )
                    for item in cast(list[object], body)
                ],
                request=request,
            )

        if not isinstance(body, dict):
            return httpx.Response(400, request=request)

        response = _trading_approval_rpc_response(
            cast(dict[str, object], body),
            allowance=allowance,
            approved=approved,
            nonce=nonce,
            gas_price=gas_price,
            gas_estimate=gas_estimate,
            send_response=send_response,
            receipt_iter=receipt_iter,
            chain_id=chain_id,
        )
        if "error" in response:
            return httpx.Response(200, json=response, request=request)
        return httpx.Response(200, json=response, request=request)

    handler.captured = captured  # type: ignore[attr-defined]
    return handler


def _trading_approval_rpc_response(
    body: object,
    *,
    allowance: int,
    approved: bool,
    nonce: int,
    gas_price: int,
    gas_estimate: int,
    send_response: str | None,
    receipt_iter: Iterator[dict[str, object] | None],
    chain_id: int,
) -> dict[str, object]:
    allowance_selector = "0x" + keccak(b"allowance(address,address)")[:4].hex()
    approved_selector = "0x" + keccak(b"isApprovedForAll(address,address)")[:4].hex()

    if not isinstance(body, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"message": "malformed"}}

    request = cast(dict[str, Any], body)
    method = request["method"]
    if method == "eth_call":
        params = cast(list[dict[str, Any]], request["params"])
        data = params[0]["data"]
        if data.startswith(allowance_selector):
            result: object = "0x" + hex(allowance)[2:].rjust(64, "0")
        elif data.startswith(approved_selector):
            result = "0x" + ("1" if approved else "0").rjust(64, "0")
        else:
            result = "0x" + "0" * 64
    elif method == "eth_chainId":
        result = hex(chain_id)
    elif method == "eth_getTransactionCount":
        result = hex(nonce)
    elif method == "eth_gasPrice":
        result = hex(gas_price)
    elif method == "eth_estimateGas":
        result = hex(gas_estimate)
    elif method == "eth_sendRawTransaction":
        result = send_response or ("0x" + "ab" * 32)
    elif method == "eth_getTransactionReceipt":
        try:
            result = next(receipt_iter)
        except StopIteration:
            result = None
    else:
        return {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"message": "unmocked"},
        }
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


async def make_safe_client() -> AsyncSecureClient:
    from eth_account import Account

    from polymarket._internal.wallet import derive_safe_wallet_address
    from polymarket.environments import PRODUCTION

    signer = Account.from_key(PK_SAFE_WALLET)
    wallet = derive_safe_wallet_address(signer.address, PRODUCTION.wallet_derivation)
    return await AsyncSecureClient._create(
        private_key=PK_SAFE_WALLET,
        wallet=wallet,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH,
        validate_credentials=False,
    )


RELAY_PAYLOAD_DEFAULT_ADDRESS = "0xe679d14b2fe0bdee4a54f25bcec2978e372de566"


def install_relayer_routes(
    client: AsyncSecureClient,
    captured: list[httpx.Request],
    routes: dict[str, Any],
) -> None:
    if "/relay-payload" not in routes and "/v1/account/transactions/params" in routes:
        legacy = cast(dict[str, Any], routes["/v1/account/transactions/params"])
        raw_nonce = legacy.get("nonce")
        nonce: str = raw_nonce if isinstance(raw_nonce, str) else "0"
        routes = {
            **routes,
            "/relay-payload": {
                "address": RELAY_PAYLOAD_DEFAULT_ADDRESS,
                "nonce": nonce,
            },
        }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        for prefix, payload in routes.items():
            if path == prefix or path.startswith(f"{prefix}/"):
                return httpx.Response(200, json=payload, request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    install_relayer_handler(client, handler)


def install_relayer_handler(
    client: AsyncSecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    transport = AsyncTransport(
        base_url="https://relayer.test",
        client=httpx.AsyncClient(
            base_url="https://relayer.test", transport=httpx.MockTransport(handler)
        ),
        header_resolver=client._ctx.relayer._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, relayer=transport)


def install_combos_routes(
    client: AsyncSecureClient,
    captured: list[httpx.Request],
    routes: dict[str, Any],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        for prefix, payload in routes.items():
            if path == prefix or path.startswith(f"{prefix}/"):
                return httpx.Response(200, json=payload, request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    install_combos_handler(client, handler)


def install_combos_handler(
    client: AsyncSecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    transport = AsyncTransport(
        base_url="https://collateral-return.test",
        client=httpx.AsyncClient(
            base_url="https://collateral-return.test", transport=httpx.MockTransport(handler)
        ),
        header_resolver=client._ctx.combos._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, combos=transport)


def install_rpc_handler(
    client: AsyncSecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    from polymarket._internal.eoa.rpc import JsonRpcClient

    transport = AsyncTransport(
        base_url="https://rpc.test",
        client=httpx.AsyncClient(
            base_url="https://rpc.test", transport=httpx.MockTransport(handler)
        ),
    )
    client._ctx = dataclasses.replace(client._ctx, rpc=JsonRpcClient(transport))


def make_sync_eoa_client(*, with_api_key: bool = True) -> SecureClient:
    from eth_account import Account

    signer = Account.from_key(PK_DEPLOY_WALLET)
    return SecureClient._create(
        private_key=PK_DEPLOY_WALLET,
        wallet=signer.address,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH if with_api_key else None,
        validate_credentials=False,
    )


def make_sync_deposit_client() -> SecureClient:
    from eth_account import Account

    from polymarket._internal.wallet import derive_uups_deposit_wallet_address
    from polymarket.environments import PRODUCTION

    signer = Account.from_key(PK_DEPLOY_WALLET)
    wallet = derive_uups_deposit_wallet_address(signer.address, PRODUCTION.wallet_derivation)
    return SecureClient._create(
        private_key=PK_DEPLOY_WALLET,
        wallet=wallet,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH,
        validate_credentials=False,
    )


def make_sync_proxy_client() -> SecureClient:
    from eth_account import Account

    from polymarket._internal.wallet import derive_proxy_wallet_address
    from polymarket.environments import PRODUCTION

    signer = Account.from_key(PK_PROXY_WALLET)
    wallet = derive_proxy_wallet_address(signer.address, PRODUCTION.wallet_derivation)
    return SecureClient._create(
        private_key=PK_PROXY_WALLET,
        wallet=wallet,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH,
        validate_credentials=False,
    )


def make_sync_safe_client() -> SecureClient:
    from eth_account import Account

    from polymarket._internal.wallet import derive_safe_wallet_address
    from polymarket.environments import PRODUCTION

    signer = Account.from_key(PK_SAFE_WALLET)
    wallet = derive_safe_wallet_address(signer.address, PRODUCTION.wallet_derivation)
    return SecureClient._create(
        private_key=PK_SAFE_WALLET,
        wallet=wallet,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH,
        validate_credentials=False,
    )


def install_sync_relayer_handler(
    client: SecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    from polymarket.clients._transport import SyncTransport

    transport = SyncTransport(
        base_url="https://relayer.test",
        client=httpx.Client(
            base_url="https://relayer.test", transport=httpx.MockTransport(handler)
        ),
        header_resolver=client._ctx.relayer._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, relayer=transport)


def install_sync_combos_handler(
    client: SecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    from polymarket.clients._transport import SyncTransport

    transport = SyncTransport(
        base_url="https://collateral-return.test",
        client=httpx.Client(
            base_url="https://collateral-return.test", transport=httpx.MockTransport(handler)
        ),
        header_resolver=client._ctx.combos._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, combos=transport)


def install_sync_rpc_handler(
    client: SecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    from polymarket._internal.eoa.rpc import SyncJsonRpcClient
    from polymarket.clients._transport import SyncTransport

    transport = SyncTransport(
        base_url="https://rpc.test",
        client=httpx.Client(base_url="https://rpc.test", transport=httpx.MockTransport(handler)),
    )
    client._ctx = dataclasses.replace(client._ctx, rpc=SyncJsonRpcClient(transport))


def legacy_factory_rpc_handler() -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": 3, "message": "execution reverted"},
            },
            request=request,
        )

    return handler


def beacon_factory_rpc_handler(beacon_address: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": "0x" + beacon_address[2:].rjust(64, "0").lower(),
            },
            request=request,
        )

    return handler


def request_json(request: httpx.Request) -> Any:
    return json.loads(request.content.decode("utf-8"))


__all__ = [
    "BUILDER_AUTH",
    "FAKE_CREDS",
    "PK_DEPLOY_WALLET",
    "PK_PROXY_WALLET",
    "PK_SAFE_WALLET",
    "RELAY_PAYLOAD_DEFAULT_ADDRESS",
    "SPENDER",
    "TOKEN",
    "beacon_factory_rpc_handler",
    "install_combos_handler",
    "install_combos_routes",
    "install_relayer_handler",
    "install_relayer_routes",
    "install_rpc_handler",
    "install_sync_combos_handler",
    "install_sync_relayer_handler",
    "install_sync_rpc_handler",
    "legacy_factory_rpc_handler",
    "make_deposit_client",
    "make_eoa_client",
    "make_eoa_client_with_rpc",
    "make_proxy_client",
    "make_rpc_handler",
    "make_safe_client",
    "make_sync_deposit_client",
    "make_sync_eoa_client",
    "make_sync_proxy_client",
    "make_sync_safe_client",
    "request_json",
    "trading_approval_rpc_handler",
]
