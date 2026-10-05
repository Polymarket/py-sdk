# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from typing import cast

import httpx
import pytest
from _relayer_helpers import (
    make_eoa_client_with_rpc,
    make_rpc_handler,
)

from polymarket import TransactionCall
from polymarket._internal.environment import with_environment_config
from polymarket.errors import TimeoutError, TransactionFailedError, UserInputError
from polymarket.transactions import DeprecatedTransactionHandle, EoaTransactionHandle
from polymarket.types import EvmAddress

_TOKEN = EvmAddress("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
_SPENDER = EvmAddress("0xE111180000d2663C0091e4f400237545B87B996B")


def test_eoa_approve_erc20_signs_and_broadcasts() -> None:
    expected_hash = "0x" + "11" * 32
    handler = make_rpc_handler(send_response=expected_hash)

    async def run() -> object:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        try:
            return await client.approve_erc20(
                token_address=str(_TOKEN), spender_address=str(_SPENDER), amount=1
            )
        finally:
            await client.close()

    h = asyncio.run(run())
    assert isinstance(h, EoaTransactionHandle)
    assert h.transaction_hash == expected_hash
    assert h.transaction_id is None
    methods = [c["method"] for c in handler.captured]  # pyright: ignore[reportFunctionMemberAccess]
    assert "eth_getTransactionCount" in methods
    assert "eth_gasPrice" in methods
    assert "eth_estimateGas" in methods
    assert "eth_sendRawTransaction" in methods


def test_eoa_wait_returns_outcome_on_success_receipt() -> None:
    expected_hash = "0x" + "22" * 32
    receipts: list[dict[str, object] | None] = [None, {"status": "0x1"}]
    handler = make_rpc_handler(send_response=expected_hash, receipt_responses=receipts)

    async def run() -> object:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
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
            handle = await client.approve_erc20(
                token_address=str(_TOKEN), spender_address=str(_SPENDER), amount=1
            )
            return await handle.wait()
        finally:
            await client.close()

    outcome = asyncio.run(run())
    assert outcome.transaction_hash == expected_hash  # type: ignore[union-attr]
    assert outcome.transaction_id is None  # type: ignore[union-attr]


def test_eoa_wait_raises_on_reverted_receipt() -> None:
    revert_receipts: list[dict[str, object] | None] = [{"status": "0x0"}]
    handler = make_rpc_handler(send_response="0x" + "33" * 32, receipt_responses=revert_receipts)

    async def run() -> None:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
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
            handle = await client.approve_erc20(
                token_address=str(_TOKEN), spender_address=str(_SPENDER), amount=1
            )
            await handle.wait()
        finally:
            await client.close()

    with pytest.raises(TransactionFailedError, match="reverted"):
        asyncio.run(run())


def test_eoa_wait_times_out_when_receipt_never_appears() -> None:
    handler = make_rpc_handler(
        send_response="0x" + "44" * 32,
        receipt_responses=[None, None, None, None],
    )

    async def run() -> None:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config,
                    relayer_poll_frequency_ms=1,
                    relayer_max_polls=3,
                ),
            ),
        )
        try:
            handle = await client.approve_erc20(
                token_address=str(_TOKEN), spender_address=str(_SPENDER), amount=1
            )
            await handle.wait()
        finally:
            await client.close()

    with pytest.raises(TimeoutError):
        asyncio.run(run())


def test_eoa_transfer_erc20_dispatches_to_rpc() -> None:
    handler = make_rpc_handler(send_response="0x" + "55" * 32)

    async def run() -> None:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        try:
            handle = await client.transfer_erc20(
                token_address=str(_TOKEN),
                recipient_address="0x000000000000000000000000000000000000dEaD",
                amount=1,
            )
            assert isinstance(handle, EoaTransactionHandle)
        finally:
            await client.close()

    asyncio.run(run())


def test_eoa_setup_trading_approvals_submits_and_waits_for_required_calls_sequentially() -> None:
    send_hashes = ["0x" + f"{i:02x}" * 32 for i in range(1, 18)]
    send_iter = iter(send_hashes)
    receipts: list[dict[str, object] | None] = [{"status": "0x1"} for _ in range(len(send_hashes))]
    receipt_iter = iter(receipts)
    calls: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = cast(object, json.loads(request.content.decode("utf-8")))
        calls.append(body)
        if isinstance(body, list):
            return httpx.Response(
                200,
                json=[
                    {
                        "jsonrpc": "2.0",
                        "id": item["id"],
                        "result": _approval_check_result(item),
                    }
                    for item in cast(list[dict[str, object]], body)
                ],
                request=request,
            )

        body = cast(dict[str, object], body)
        method = body["method"]
        if method == "eth_chainId":
            result: object = hex(137)
        elif method == "eth_call":
            result = _approval_check_result(body)
        elif method == "eth_getTransactionCount":
            result = hex(7)
        elif method == "eth_gasPrice":
            result = hex(30_000_000_000)
        elif method == "eth_estimateGas":
            result = hex(100_000)
        elif method == "eth_sendRawTransaction":
            result = next(send_iter)
        elif method == "eth_getTransactionReceipt":
            try:
                result = next(receipt_iter)
            except StopIteration:
                result = None
        else:
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "error": "unknown"}, request=request
            )
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}, request=request
        )

    def _approval_check_result(body: dict[str, object]) -> str:
        return "0x" + "0" * 64

    async def run() -> object:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
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
            return await client.setup_trading_approvals()
        finally:
            await client.close()

    handle = asyncio.run(run())
    assert isinstance(handle, DeprecatedTransactionHandle)
    assert handle.transaction_hash is None
    assert _rpc_method_count(calls, "eth_sendRawTransaction") == len(send_hashes)
    assert _rpc_method_count(calls, "eth_getTransactionReceipt") >= len(send_hashes)


def _rpc_method_count(calls: list[object], method: str) -> int:
    total = 0
    for call in calls:
        if not isinstance(call, dict):
            continue
        rpc_call = cast(dict[str, object], call)
        if rpc_call.get("method") == method:
            total += 1
    return total


def test_rpc_client_closes_with_client() -> None:
    handler = make_rpc_handler()

    async def run() -> None:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        assert client._ctx.rpc is not None
        await client.close()

    asyncio.run(run())


def test_transaction_call_is_exposed_at_top_level() -> None:
    assert TransactionCall is not None


def test_eoa_workflow_rejects_when_rpc_chain_id_mismatch() -> None:
    handler = make_rpc_handler(chain_id=1)

    async def run() -> None:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        try:
            with pytest.raises(UserInputError, match="chain id"):
                await client.approve_erc20(
                    token_address=str(_TOKEN), spender_address=str(_SPENDER), amount=1
                )
        finally:
            await client.close()

    asyncio.run(run())


def test_eoa_workflow_verifies_chain_id_only_once() -> None:
    handler = make_rpc_handler()

    async def run() -> None:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        try:
            await client.approve_erc20(
                token_address=str(_TOKEN), spender_address=str(_SPENDER), amount=1
            )
            await client.approve_erc20(
                token_address=str(_TOKEN), spender_address=str(_SPENDER), amount=2
            )
        finally:
            await client.close()

    asyncio.run(run())
    chain_id_calls = [
        c
        for c in handler.captured  # pyright: ignore[reportFunctionMemberAccess]
        if c["method"] == "eth_chainId"
    ]
    assert len(chain_id_calls) == 1
