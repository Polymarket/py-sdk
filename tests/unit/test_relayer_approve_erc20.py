# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from _relayer_helpers import (
    FAKE_CREDS,
    PK_DEPLOY_WALLET,
    RELAY_PAYLOAD_DEFAULT_ADDRESS,
    SPENDER,
    TOKEN,
    install_relayer_handler,
    install_relayer_routes,
    install_rpc_handler,
    make_deposit_client,
    make_proxy_client,
    make_safe_client,
    request_json,
)

from polymarket import AsyncSecureClient
from polymarket._internal.environment import (
    PRODUCTION_CONFIG,
    with_environment_config,
)
from polymarket.errors import UserInputError
from polymarket.transactions import TransactionHandle


def test_approve_erc20_rejects_when_no_api_key() -> None:
    from eth_account import Account

    from polymarket._internal.wallet import derive_uups_deposit_wallet_address

    async def run() -> None:
        signer = Account.from_key(PK_DEPLOY_WALLET)
        wallet = derive_uups_deposit_wallet_address(
            signer.address, PRODUCTION_CONFIG.wallet_derivation
        )
        client = await AsyncSecureClient._create(
            private_key=PK_DEPLOY_WALLET,
            wallet=wallet,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            with pytest.raises(UserInputError, match="Builder API Key or Relayer API Key"):
                await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        finally:
            await client.close()

    asyncio.run(run())


def test_approve_erc20_rejects_invalid_amount() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        try:
            with pytest.raises(UserInputError, match="non-negative"):
                await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=-1)
            with pytest.raises(UserInputError, match="uint256"):
                await client.approve_erc20(
                    token_address=TOKEN,
                    spender_address=SPENDER,
                    amount=(1 << 256),
                )
        finally:
            await client.close()

    asyncio.run(run())


def test_approve_erc20_rejects_invalid_token_address() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        try:
            with pytest.raises(UserInputError, match="Invalid token_address"):
                await client.approve_erc20(
                    token_address="not-an-address",
                    spender_address=SPENDER,
                    amount=1,
                )
        finally:
            await client.close()

    asyncio.run(run())


def test_approve_erc20_deposit_wallet_payload_shape() -> None:
    captured: list[httpx.Request] = []

    async def run() -> TransactionHandle:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/v1/account/transactions/params": {
                    "address": client._ctx.signer.address,
                    "nonce": "5",
                },
                "/submit": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-deposit",
                },
            },
        )
        try:
            return await client.approve_erc20(
                token_address=TOKEN,
                spender_address=SPENDER,
                amount=10,
                metadata="approve test",
            )
        finally:
            await client.close()

    handle = asyncio.run(run())
    assert handle.transaction_id == "tx-deposit"
    assert handle.transaction_hash is None

    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert len(submit_calls) == 1
    body = request_json(submit_calls[0])
    assert body["type"] == "WALLET"
    assert body["nonce"] == "5"
    assert body["metadata"] == "approve test"
    assert body["depositWalletParams"]["calls"][0]["target"].lower() == TOKEN.lower()
    assert len(body["signature"]) == 2 + 130


def test_approve_erc20_proxy_payload_shape() -> None:
    import json as _json

    captured: list[httpx.Request] = []

    def rpc_handler(request: httpx.Request) -> httpx.Response:
        body = _json.loads(request.content.decode("utf-8"))
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
                "/v1/account/transactions/params": {
                    "address": client._ctx.signer.address,
                    "nonce": "0",
                },
                "/submit": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-proxy",
                },
            },
        )
        install_rpc_handler(client, rpc_handler)
        try:
            await client.approve_erc20(
                token_address=TOKEN,
                spender_address=SPENDER,
                amount=10,
            )
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    assert body["type"] == "PROXY"
    assert body["to"].lower() == "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052".lower()
    assert "signatureParams" in body
    assert body["signatureParams"]["gasLimit"] == "200000"
    assert body["signatureParams"]["gasPrice"] == "0"
    assert body["signatureParams"]["relayerFee"] == "0"
    assert body["signatureParams"]["relay"].lower() == RELAY_PAYLOAD_DEFAULT_ADDRESS.lower()
    assert len(body["signature"]) == 2 + 130


def test_approve_erc20_safe_single_call_payload_shape() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_safe_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/v1/account/transactions/params": {
                    "address": client._ctx.signer.address,
                    "nonce": "0",
                },
                "/submit": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-safe",
                },
            },
        )
        try:
            await client.approve_erc20(
                token_address=TOKEN,
                spender_address=SPENDER,
                amount=1,
            )
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    assert body["type"] == "SAFE"
    assert body["to"].lower() == TOKEN.lower()
    assert body["signatureParams"]["operation"] == "0"
    assert body["data"].startswith("0x095ea7b3")
    v = int(body["signature"][-2:], 16)
    assert v in (31, 32)


def test_approve_erc20_default_metadata_matches_ts_pattern() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/v1/account/transactions/params": {
                    "address": client._ctx.signer.address,
                    "nonce": "1",
                },
                "/submit": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-meta",
                },
            },
        )
        try:
            await client.approve_erc20(
                token_address=TOKEN,
                spender_address=SPENDER,
                amount=42,
            )
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    assert body["metadata"].startswith("Approve 42 of ")
    assert TOKEN.lower() in body["metadata"].lower()
    assert SPENDER.lower() in body["metadata"].lower()


def test_approve_erc20_accepts_amount_max() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/v1/account/transactions/params": {
                    "address": client._ctx.signer.address,
                    "nonce": "0",
                },
                "/submit": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-max",
                },
            },
        )
        try:
            await client.approve_erc20(
                token_address=TOKEN,
                spender_address=SPENDER,
                amount="max",
            )
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    assert body["depositWalletParams"]["calls"][0]["data"].lower().endswith("f" * 64)


def test_approve_erc20_retries_with_fresh_nonce_on_nonce_mismatch() -> None:
    captured: list[httpx.Request] = []
    nonces = iter(["3", "9"])
    submit_attempts = 0

    async def run() -> None:
        nonlocal submit_attempts
        client = await make_deposit_client()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal submit_attempts
            captured.append(request)
            path = urlparse(str(request.url)).path
            if path == "/v1/account/transactions/params":
                return httpx.Response(
                    200,
                    json={"address": client._ctx.signer.address, "nonce": next(nonces)},
                    request=request,
                )
            if path == "/submit":
                submit_attempts += 1
                if submit_attempts == 1:
                    return httpx.Response(
                        400,
                        json={"error": "batch nonce 3 does not match on-chain nonce 9"},
                        request=request,
                    )
                return httpx.Response(
                    200,
                    json={
                        "state": "STATE_NEW",
                        "transactionHash": None,
                        "transactionID": "tx-retry",
                    },
                    request=request,
                )
            return httpx.Response(404, request=request)

        install_relayer_handler(client, handler)
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config, relayer_poll_frequency_ms=1
                ),
            ),
        )
        try:
            await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        finally:
            await client.close()

    asyncio.run(run())
    assert submit_attempts == 2

    submit_bodies = [request_json(r) for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert submit_bodies[0]["nonce"] == "3"
    assert submit_bodies[1]["nonce"] == "9"
    assert submit_bodies[0]["signature"] != submit_bodies[1]["signature"]


def test_approve_erc20_self_heals_with_nonce_from_submit_error() -> None:
    captured: list[httpx.Request] = []
    submit_attempts = 0

    async def run() -> TransactionHandle:
        nonlocal submit_attempts
        client = await make_deposit_client()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal submit_attempts
            captured.append(request)
            path = urlparse(str(request.url)).path
            if path == "/v1/account/transactions/params":
                return httpx.Response(
                    200,
                    json={"address": client._ctx.signer.address, "nonce": "9"},
                    request=request,
                )
            if path == "/submit":
                submit_attempts += 1
                if submit_attempts == 1:
                    return httpx.Response(
                        400,
                        json={"error": "batch nonce 9 does not match on-chain nonce 2"},
                        request=request,
                    )
                return httpx.Response(
                    200,
                    json={
                        "state": "STATE_NEW",
                        "transactionHash": None,
                        "transactionID": "tx-healed",
                    },
                    request=request,
                )
            return httpx.Response(404, request=request)

        install_relayer_handler(client, handler)
        try:
            return await client.approve_erc20(
                token_address=TOKEN, spender_address=SPENDER, amount=1
            )
        finally:
            await client.close()

    handle = asyncio.run(run())
    assert handle.transaction_id == "tx-healed"
    assert submit_attempts == 2

    submit_bodies = [request_json(r) for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert submit_bodies[1]["nonce"] == "2"


def test_wait_polls_until_confirmed() -> None:
    captured: list[httpx.Request] = []
    polls = 0

    async def run() -> Any:
        client = await make_deposit_client()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal polls
            captured.append(request)
            path = urlparse(str(request.url)).path
            if path == "/v1/account/transactions/params":
                return httpx.Response(
                    200,
                    json={"address": client._ctx.signer.address, "nonce": "1"},
                    request=request,
                )
            if path == "/submit":
                return httpx.Response(
                    200,
                    json={
                        "state": "STATE_NEW",
                        "transactionHash": None,
                        "transactionID": "tx-9",
                    },
                    request=request,
                )
            if path.startswith("/v1/account/transactions/"):
                polls += 1
                state = "STATE_CONFIRMED" if polls >= 2 else "STATE_NEW"
                return httpx.Response(
                    200,
                    json={
                        "state": state,
                        "transaction_hash": "0x" + "11" * 32 if polls >= 2 else "",
                        "transaction_id": "tx-9",
                    },
                    request=request,
                )
            return httpx.Response(404, request=request)

        install_relayer_handler(client, handler)
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config, relayer_poll_frequency_ms=10
                ),
            ),
        )
        try:
            handle = await client.approve_erc20(
                token_address=TOKEN, spender_address=SPENDER, amount=1
            )
            return await handle.wait()
        finally:
            await client.close()

    outcome = asyncio.run(run())
    assert outcome.transaction_id == "tx-9"
    assert outcome.transaction_hash == "0x" + "11" * 32


def test_approve_erc20_works_with_relayer_api_key() -> None:
    from eth_account import Account

    from polymarket import RelayerApiKey
    from polymarket._internal.wallet import derive_uups_deposit_wallet_address

    captured: list[httpx.Request] = []

    async def run() -> None:
        signer = Account.from_key(PK_DEPLOY_WALLET)
        wallet = derive_uups_deposit_wallet_address(
            signer.address, PRODUCTION_CONFIG.wallet_derivation
        )
        client = await AsyncSecureClient._create(
            private_key=PK_DEPLOY_WALLET,
            wallet=wallet,
            credentials=FAKE_CREDS,
            api_key=RelayerApiKey(key="rk", address=signer.address),
            validate_credentials=False,
        )
        install_relayer_routes(
            client,
            captured,
            {
                "/v1/account/transactions/params": {
                    "address": client._ctx.signer.address,
                    "nonce": "0",
                },
                "/submit": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-rk",
                },
            },
        )
        try:
            await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    headers = submit_calls[0].headers
    assert headers.get("RELAYER_API_KEY") == "rk"
    assert "RELAYER_API_KEY_ADDRESS" in headers
