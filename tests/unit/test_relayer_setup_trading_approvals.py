# pyright: reportPrivateUsage=false
import asyncio
from urllib.parse import urlparse

import httpx
from _relayer_helpers import (
    install_relayer_routes,
    install_rpc_handler,
    make_deposit_client,
    make_safe_client,
    request_json,
    trading_approval_rpc_handler,
)
from eth_utils.crypto import keccak

from polymarket._internal.environment import PRODUCTION_CONFIG


def _selector(sig: str) -> str:
    return "0x" + keccak(sig.encode("ascii"))[:4].hex()


def test_setup_trading_approvals_bundles_required_calls_for_deposit_wallet() -> None:
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
                    "transactionID": "tx-setup",
                },
                "/v1/account/transactions/tx-setup": {
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": "0x" + "ab" * 32,
                    "transaction_id": "tx-setup",
                },
            },
        )
        install_rpc_handler(client, trading_approval_rpc_handler())
        try:
            await client.setup_trading_approvals()
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert len(submit_calls) == 1
    body = request_json(submit_calls[0])
    assert body["type"] == "WALLET"
    inner = body["depositWalletParams"]["calls"]
    assert len(inner) == 17

    erc20_sel = _selector("approve(address,uint256)")
    erc1155_sel = _selector("setApprovalForAll(address,bool)")
    # ERC20 approvals: standard_exchange, neg_risk_exchange, collateral_adapter,
    # neg_risk_collateral_adapter, protocol_v2_router, exchange_v3, perps_deposit_contract
    for index, spender in enumerate(
        [
            PRODUCTION_CONFIG.standard_exchange,
            PRODUCTION_CONFIG.neg_risk_exchange,
            PRODUCTION_CONFIG.collateral_adapter,
            PRODUCTION_CONFIG.neg_risk_collateral_adapter,
            PRODUCTION_CONFIG.protocol_v2_router,
            PRODUCTION_CONFIG.exchange_v3,
            PRODUCTION_CONFIG.perps_deposit_contract,
        ]
    ):
        assert inner[index]["target"].lower() == PRODUCTION_CONFIG.collateral_token.lower()
        assert inner[index]["data"].startswith(erc20_sel)
        assert spender[2:].lower() in inner[index]["data"].lower()
    # ERC1155 conditional-token approvals: standard_exchange, neg_risk_exchange,
    # collateral_adapter, neg_risk_collateral_adapter, auto_redeem_operator,
    # binary_module, neg_risk_module
    for offset, operator in enumerate(
        [
            PRODUCTION_CONFIG.standard_exchange,
            PRODUCTION_CONFIG.neg_risk_exchange,
            PRODUCTION_CONFIG.collateral_adapter,
            PRODUCTION_CONFIG.neg_risk_collateral_adapter,
            PRODUCTION_CONFIG.auto_redeem_operator,
            PRODUCTION_CONFIG.binary_module,
            PRODUCTION_CONFIG.neg_risk_module,
        ]
    ):
        index = 7 + offset
        assert inner[index]["target"].lower() == PRODUCTION_CONFIG.conditional_tokens.lower()
        assert inner[index]["data"].startswith(erc1155_sel)
        assert operator[2:].lower() in inner[index]["data"].lower()

    # ERC1155 position-manager approvals: protocol_v2_router, exchange_v3, auto_redeem_operator
    for offset, operator in enumerate(
        [
            PRODUCTION_CONFIG.protocol_v2_router,
            PRODUCTION_CONFIG.exchange_v3,
            PRODUCTION_CONFIG.auto_redeem_operator,
        ]
    ):
        index = 14 + offset
        assert inner[index]["target"].lower() == PRODUCTION_CONFIG.position_manager.lower()
        assert inner[index]["data"].startswith(erc1155_sel)
        assert operator[2:].lower() in inner[index]["data"].lower()
    assert body["metadata"] == "Trading setup approvals"


def test_setup_trading_approvals_skips_submit_when_already_approved() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(client, captured, {})
        install_rpc_handler(
            client,
            trading_approval_rpc_handler(allowance=(1 << 256) - 1, approved=True),
        )
        try:
            handle = await client.setup_trading_approvals()
            await handle.wait()
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert submit_calls == []


def test_setup_trading_approvals_uses_safe_multisend_for_safe() -> None:
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
                    "transactionID": "tx-setup-safe",
                },
                "/v1/account/transactions/tx-setup-safe": {
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": "0x" + "cd" * 32,
                    "transaction_id": "tx-setup-safe",
                },
            },
        )
        install_rpc_handler(client, trading_approval_rpc_handler())
        try:
            await client.setup_trading_approvals()
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    assert body["type"] == "SAFE"
    assert body["to"].lower() == PRODUCTION_CONFIG.safe_multisend.lower()
    assert body["signatureParams"]["operation"] == "1"
    assert body["data"].startswith("0x8d80ff0a")
