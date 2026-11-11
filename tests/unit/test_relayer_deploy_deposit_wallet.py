# pyright: reportPrivateUsage=false
import asyncio
from urllib.parse import urlparse

import httpx
from _relayer_helpers import (
    install_relayer_routes,
    make_deposit_client,
    request_json,
)

from polymarket._internal.actions.relayer.gasless import submit_deposit_wallet_create


def test_deploy_deposit_wallet_wire_payload_has_no_signature() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            captured,
            {
                "/v1/wallets/transactions": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-dep-create",
                },
            },
        )
        try:
            handle = await submit_deposit_wallet_create(client._ctx)
            assert handle.transaction_id == "tx-dep-create"
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/v1/wallets/transactions"]
    body = request_json(submit_calls[0])
    assert body["type"] == "WALLET-CREATE"
    assert "signature" not in body
    assert "nonce" not in body
    assert body["metadata"] == ""
