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

_TOKEN = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
_OPERATOR = "0xE111180000d2663C0091e4f400237545B87B996B"


def test_approve_erc1155_for_all_default_approved_true() -> None:
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
                    "transactionID": "tx-1155",
                },
            },
        )
        try:
            await client.approve_erc1155_for_all(token_address=_TOKEN, operator_address=_OPERATOR)
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/v1/wallets/transactions"]
    body = request_json(submit_calls[0])
    inner = body["depositWalletParams"]["calls"][0]
    selector = "0x" + keccak(b"setApprovalForAll(address,bool)")[:4].hex()
    assert inner["data"].startswith(selector)
    assert body["metadata"].startswith("Approve ")


def test_approve_erc1155_for_all_revoke() -> None:
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
                    "transactionID": "tx-1155-rev",
                },
            },
        )
        try:
            await client.approve_erc1155_for_all(
                token_address=_TOKEN, operator_address=_OPERATOR, approved=False
            )
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/v1/wallets/transactions"]
    body = request_json(submit_calls[0])
    assert body["metadata"].startswith("Revoke ")
    inner = body["depositWalletParams"]["calls"][0]
    last_word = inner["data"][-64:]
    assert int(last_word, 16) == 0
