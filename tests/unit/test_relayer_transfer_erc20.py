# pyright: reportPrivateUsage=false
import asyncio
from urllib.parse import urlparse

import httpx
from _relayer_helpers import (
    install_relayer_routes,
    make_deposit_client,
    request_json,
)
from eth_utils.crypto import keccak

_TOKEN = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
_RECIPIENT = "0x000000000000000000000000000000000000dEaD"


def test_transfer_erc20_emits_transfer_selector() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/v1/wallets/execute-params": {
                    "address": client._ctx.signer.address,
                    "nonce": "0",
                },
                "/v1/wallets/transactions": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-tr",
                },
            },
        )
        try:
            await client.transfer_erc20(
                token_address=_TOKEN,
                recipient_address=_RECIPIENT,
                amount=1_000_000,
                metadata="send 1 USDC",
            )
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/v1/wallets/transactions"]
    body = request_json(submit_calls[0])
    inner = body["depositWalletParams"]["calls"][0]
    selector = "0x" + keccak(b"transfer(address,uint256)")[:4].hex()
    assert inner["target"].lower() == _TOKEN.lower()
    assert inner["data"].startswith(selector)
    assert body["metadata"] == "send 1 USDC"


def test_transfer_erc20_self_transfer_allowed() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/v1/wallets/execute-params": {
                    "address": client._ctx.signer.address,
                    "nonce": "0",
                },
                "/v1/wallets/transactions": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-self",
                },
            },
        )
        try:
            await client.transfer_erc20(
                token_address=_TOKEN,
                recipient_address=str(client._ctx.wallet),
                amount=1,
            )
        finally:
            await client.close()

    asyncio.run(run())
