# pyright: reportPrivateUsage=false
import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from _relayer_helpers import (
    install_relayer_routes,
    install_rpc_handler,
    make_deposit_client,
    request_json,
)
from eth_abi.abi import encode as abi_encode

from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.pagination import Page

_CONDITION_ID = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"


class _StubPaginator:
    def __init__(self, items: tuple[Any, ...]) -> None:
        self._items = items

    async def first_page(self) -> Page[Any]:
        return Page(items=self._items, has_more=False)


def _setup_relayer(client: Any, captured: list[httpx.Request], tx_id: str) -> None:
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
                "transactionID": tx_id,
            },
        },
    )


def test_merge_positions_resolves_max_to_min_of_yes_no() -> None:
    captured: list[httpx.Request] = []
    rpc_calls: list[dict[str, Any]] = []

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-merge-max")
        install_rpc_handler(
            client, _eth_call_result("uint256[]", [100_000_000, 60_000_000], rpc_calls)
        )
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_market(neg_risk=False),)
        )
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            await client.merge_positions(condition_id=_CONDITION_ID, amount="max")
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.collateral_adapter.lower()
    assert "Merge 60000000 positions" in body["metadata"]
    assert rpc_calls[0]["params"][0]["to"].lower() == PRODUCTION_CONFIG.conditional_tokens.lower()


def test_merge_positions_rejects_amount_above_max() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        install_rpc_handler(client, _eth_call_result("uint256[]", [100_000_000, 60_000_000]))
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_market(neg_risk=False),)
        )
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            with pytest.raises(UserInputError, match="exceeds the maximum"):
                await client.merge_positions(condition_id=_CONDITION_ID, amount=70_000_000)
        finally:
            await client.close()

    asyncio.run(run())


def test_merge_positions_neg_risk_uses_neg_risk_collateral_adapter_target() -> None:
    captured: list[httpx.Request] = []
    rpc_calls: list[dict[str, Any]] = []

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-merge-nr")
        install_rpc_handler(
            client, _eth_call_result("uint256[]", [50_000_000, 50_000_000], rpc_calls)
        )
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_market(neg_risk=True),)
        )
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            await client.merge_positions(condition_id=_CONDITION_ID, amount="max")
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.neg_risk_collateral_adapter.lower()
    assert rpc_calls[0]["params"][0]["to"].lower() == PRODUCTION_CONFIG.neg_risk_adapter.lower()


def test_merge_positions_rejects_when_no_complementary_balance() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        install_rpc_handler(client, _eth_call_result("uint256[]", [0, 0]))
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_market(neg_risk=False),)
        )
        try:
            with pytest.raises(UserInputError, match="no complementary"):
                await client.merge_positions(condition_id=_CONDITION_ID, amount="max")
        finally:
            await client.close()

    asyncio.run(run())


def test_merge_positions_rejects_single_side_balance_only() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        install_rpc_handler(client, _eth_call_result("uint256[]", [100_000_000, 0]))
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_market(neg_risk=False),)
        )
        try:
            with pytest.raises(UserInputError, match="no complementary"):
                await client.merge_positions(condition_id=_CONDITION_ID, amount="max")
        finally:
            await client.close()

    asyncio.run(run())


def test_merge_positions_raises_when_market_token_ids_missing() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_market(neg_risk=False, yes_token_id=None),)
        )
        try:
            with pytest.raises(UnexpectedResponseError, match="Incomplete market token IDs"):
                await client.merge_positions(condition_id=_CONDITION_ID, amount="max")
        finally:
            await client.close()

    asyncio.run(run())


def _market(
    *,
    neg_risk: bool | None,
    condition_id: str | None = _CONDITION_ID,
    yes_token_id: str | None = "101",
    no_token_id: str | None = "202",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="123",
        condition_id=condition_id,
        state=SimpleNamespace(neg_risk=neg_risk),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id=yes_token_id),
            no=SimpleNamespace(token_id=no_token_id),
        ),
    )


def _fail_list_positions(**_: object) -> None:
    raise AssertionError("list_positions should not be called")


def _eth_call_result(
    abi_type: str,
    value: object,
    calls: list[dict[str, Any]] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if calls is not None:
            calls.append(body)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": "0x" + abi_encode([abi_type], [value]).hex(),
            },
            request=request,
        )

    return handler
