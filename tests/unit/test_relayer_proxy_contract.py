# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import json
from typing import Any, cast
from urllib.parse import urlparse

import httpx
from _relayer_helpers import (
    SPENDER,
    TOKEN,
    install_relayer_routes,
    install_rpc_handler,
    make_proxy_client,
    request_json,
)

from polymarket._internal.actions.relayer.signing.proxy import (
    build_proxy_transaction_hash,
)
from polymarket._internal.environment import get_environment_config
from polymarket._internal.eoa.rpc import JsonRpcClient
from polymarket.clients._transport import AsyncTransport
from polymarket.environments import PRODUCTION
from polymarket.types import EvmAddress, HexString

RELAYER_ADDRESS = "0xe679d14b2fe0bdee4a54f25bcec2978e372de566"


def _submit_route() -> dict[str, str | None]:
    return {
        "state": "STATE_NEW",
        "transactionHash": None,
        "transactionID": "tx-proxy",
    }


def test_proxy_submission_hits_relay_payload_not_legacy_params() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_proxy_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/relay-payload": {"address": RELAYER_ADDRESS, "nonce": "42"},
                "/submit": _submit_route(),
            },
        )
        try:
            await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(r.url)).path for r in captured]
    assert "/relay-payload" in paths, paths
    assert "/v1/account/transactions/params" not in paths, paths


def test_proxy_signs_relay_address_returned_from_relay_payload() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_proxy_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/relay-payload": {"address": RELAYER_ADDRESS, "nonce": "42"},
                "/submit": _submit_route(),
            },
        )
        try:
            await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        finally:
            await client.close()

    asyncio.run(run())
    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    assert body["signatureParams"]["relay"].lower() == RELAYER_ADDRESS.lower()
    assert body["signatureParams"]["relay"] != "0x" + "00" * 20


def test_proxy_signs_default_gas_limit_when_rpc_estimate_fails() -> None:
    captured: list[httpx.Request] = []

    def rpc_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32_603, "message": "upstream unavailable"},
            },
            request=request,
        )

    async def run() -> None:
        client = await make_proxy_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/relay-payload": {"address": RELAYER_ADDRESS, "nonce": "0"},
                "/submit": _submit_route(),
            },
        )
        install_rpc_handler(client, rpc_handler)
        try:
            await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        finally:
            await client.close()

    asyncio.run(run())
    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    assert body["signatureParams"]["gasLimit"] == "200000"


def test_proxy_signs_rpc_estimated_gas_limit_when_rpc_configured() -> None:
    captured: list[httpx.Request] = []
    rpc_calls: list[dict[str, object]] = []

    def rpc_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        rpc_calls.append(body)
        if body["method"] == "eth_estimateGas":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": hex(173_245)},
                request=request,
            )
        if body["method"] == "eth_chainId":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": hex(137)},
                request=request,
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "error": {"message": "unmocked"}},
            request=request,
        )

    async def run() -> None:
        client = await make_proxy_client()
        rpc_transport = AsyncTransport(
            base_url="https://rpc.test",
            client=httpx.AsyncClient(
                base_url="https://rpc.test", transport=httpx.MockTransport(rpc_handler)
            ),
        )
        client._ctx = dataclasses.replace(client._ctx, rpc=JsonRpcClient(rpc_transport))
        install_relayer_routes(
            client,
            captured,
            {
                "/relay-payload": {"address": RELAYER_ADDRESS, "nonce": "0"},
                "/submit": _submit_route(),
            },
        )
        try:
            await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        finally:
            await client.close()

    asyncio.run(run())
    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    assert body["signatureParams"]["gasLimit"] == "173245"
    assert any(call["method"] == "eth_estimateGas" for call in rpc_calls)


def test_proxy_signed_hash_binds_relay_and_gas_limit() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[Any, str]:
        client = await make_proxy_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/relay-payload": {"address": RELAYER_ADDRESS, "nonce": "0"},
                "/submit": _submit_route(),
            },
        )
        signer_address = client._ctx.signer.address
        try:
            await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        finally:
            await client.close()
        return (
            request_json([r for r in captured if urlparse(str(r.url)).path == "/submit"][0]),
            signer_address,
        )

    body, signer_address = asyncio.run(run())

    canonical = build_proxy_transaction_hash(
        from_address=cast(EvmAddress, signer_address),
        to=cast(EvmAddress, body["to"]),
        data=cast(HexString, body["data"]),
        relayer_fee=body["signatureParams"]["relayerFee"],
        gas_price=body["signatureParams"]["gasPrice"],
        gas_limit=body["signatureParams"]["gasLimit"],
        nonce=body["nonce"],
        relay_hub=cast(EvmAddress, get_environment_config(PRODUCTION).relay_hub),
        relay=cast(EvmAddress, body["signatureParams"]["relay"]),
    )
    with_zero_relay = build_proxy_transaction_hash(
        from_address=cast(EvmAddress, signer_address),
        to=cast(EvmAddress, body["to"]),
        data=cast(HexString, body["data"]),
        relayer_fee=body["signatureParams"]["relayerFee"],
        gas_price=body["signatureParams"]["gasPrice"],
        gas_limit=body["signatureParams"]["gasLimit"],
        nonce=body["nonce"],
        relay_hub=cast(EvmAddress, get_environment_config(PRODUCTION).relay_hub),
        relay=cast(EvmAddress, "0x" + "00" * 20),
    )
    with_legacy_gas = build_proxy_transaction_hash(
        from_address=cast(EvmAddress, signer_address),
        to=cast(EvmAddress, body["to"]),
        data=cast(HexString, body["data"]),
        relayer_fee=body["signatureParams"]["relayerFee"],
        gas_price=body["signatureParams"]["gasPrice"],
        gas_limit="10000000",
        nonce=body["nonce"],
        relay_hub=cast(EvmAddress, get_environment_config(PRODUCTION).relay_hub),
        relay=cast(EvmAddress, body["signatureParams"]["relay"]),
    )

    assert canonical != with_zero_relay
    assert canonical != with_legacy_gas
