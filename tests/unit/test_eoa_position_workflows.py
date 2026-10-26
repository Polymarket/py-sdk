# pyright: reportPrivateUsage=false
import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
from _relayer_helpers import make_eoa_client_with_rpc, make_rpc_handler
from eth_abi.abi import encode as abi_encode

from polymarket.pagination import Page
from polymarket.transactions import EoaTransactionHandle

_CONDITION_ID = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"


class _StubPaginator:
    def __init__(self, items: tuple[Any, ...]) -> None:
        self._items = items

    async def first_page(self) -> Page[Any]:
        return Page(items=self._items, has_more=False)


def _make_market_stub(neg_risk: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id="123",
        version="v1",
        condition_id=_CONDITION_ID,
        state=SimpleNamespace(neg_risk=neg_risk),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id="101"),
            no=SimpleNamespace(token_id="202"),
        ),
    )


def test_eoa_split_position_signs_and_broadcasts() -> None:
    handler = make_rpc_handler(send_response="0x" + "a1" * 32)

    async def run() -> object:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_make_market_stub(neg_risk=False),)
        )
        try:
            return await client.split_position(condition_id=_CONDITION_ID, amount=1_000_000)
        finally:
            await client.close()

    handle = asyncio.run(run())
    assert isinstance(handle, EoaTransactionHandle)
    assert handle.transaction_hash == "0x" + "a1" * 32
    methods = [c["method"] for c in handler.captured]  # pyright: ignore[reportFunctionMemberAccess]
    assert "eth_sendRawTransaction" in methods


def test_eoa_merge_positions_signs_and_broadcasts() -> None:
    handler = _make_rpc_handler_with_balance(
        send_response="0x" + "b2" * 32,
        balances=[50_000_000, 30_000_000],
    )

    async def run() -> object:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_make_market_stub(neg_risk=False),)
        )
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            return await client.merge_positions(condition_id=_CONDITION_ID, amount="max")
        finally:
            await client.close()

    handle = asyncio.run(run())
    assert isinstance(handle, EoaTransactionHandle)
    assert handle.transaction_hash == "0x" + "b2" * 32


def test_eoa_redeem_positions_ctf_signs_and_broadcasts() -> None:
    handler = make_rpc_handler(send_response="0x" + "c3" * 32)

    async def run() -> object:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_make_market_stub(neg_risk=False),)
        )
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            return await client.redeem_positions(condition_id=_CONDITION_ID)
        finally:
            await client.close()

    handle = asyncio.run(run())
    assert isinstance(handle, EoaTransactionHandle)
    assert handle.transaction_hash == "0x" + "c3" * 32


def test_eoa_redeem_positions_neg_risk_signs_and_broadcasts() -> None:
    handler = make_rpc_handler(send_response="0x" + "d4" * 32)

    async def run() -> object:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_make_market_stub(neg_risk=True),)
        )
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            return await client.redeem_positions(condition_id=_CONDITION_ID)
        finally:
            await client.close()

    handle = asyncio.run(run())
    assert isinstance(handle, EoaTransactionHandle)
    assert handle.transaction_hash == "0x" + "d4" * 32


def test_eoa_split_position_invalid_amount_propagates() -> None:
    handler = make_rpc_handler()

    async def run() -> None:
        client = await make_eoa_client_with_rpc(rpc_handler=handler)
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_make_market_stub(neg_risk=False),)
        )
        try:
            import pytest as _pytest

            from polymarket.errors import UserInputError

            with _pytest.raises(UserInputError, match="non-negative"):
                await client.split_position(condition_id=_CONDITION_ID, amount=-1)
        finally:
            await client.close()

    asyncio.run(run())


def _fail_list_positions(**_: object) -> None:
    raise AssertionError("list_positions should not be called")


def _make_rpc_handler_with_balance(
    *,
    send_response: str,
    balances: list[int],
):
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured.append(body)
        method = body["method"]
        if method == "eth_call":
            result: object = "0x" + abi_encode(["uint256[]"], [balances]).hex()
        elif method == "eth_chainId":
            result = hex(137)
        elif method == "eth_getTransactionCount":
            result = hex(7)
        elif method == "eth_gasPrice":
            result = hex(30_000_000_000)
        elif method == "eth_estimateGas":
            result = hex(100_000)
        elif method == "eth_sendRawTransaction":
            result = send_response
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
