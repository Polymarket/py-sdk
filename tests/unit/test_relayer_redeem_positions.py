# pyright: reportPrivateUsage=false
import asyncio
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from _relayer_helpers import (
    install_relayer_routes,
    make_deposit_client,
    request_json,
)
from eth_utils.crypto import keccak

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


def test_redeem_positions_uses_collateral_adapter_when_neg_risk_false() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-redeem-ctf")
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_market(neg_risk=False),)
        )
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            await client.redeem_positions(condition_id=_CONDITION_ID)
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.collateral_adapter.lower()
    ctf_selector = "0x" + keccak(b"redeemPositions(address,bytes32,bytes32,uint256[])")[:4].hex()
    assert inner["data"].startswith(ctf_selector)


def test_redeem_positions_uses_neg_risk_collateral_adapter_when_neg_risk_true() -> None:
    captured: list[httpx.Request] = []
    market_calls: list[dict[str, object]] = []

    def list_markets_stub(**kwargs: object) -> _StubPaginator:
        market_calls.append(kwargs)
        return _StubPaginator((_market(neg_risk=True),))

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-redeem-nr")
        client.list_markets = list_markets_stub  # type: ignore[method-assign]
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            await client.redeem_positions(condition_id=_CONDITION_ID)
        finally:
            await client.close()

    asyncio.run(run())
    assert market_calls == [{"condition_ids": [_CONDITION_ID], "closed": True, "page_size": 1}]
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.neg_risk_collateral_adapter.lower()
    ctf_selector = "0x" + keccak(b"redeemPositions(address,bytes32,bytes32,uint256[])")[:4].hex()
    assert inner["data"].startswith(ctf_selector)


def test_redeem_positions_rejects_both_condition_id_and_market_id() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        try:
            with pytest.raises(UserInputError, match="exactly one"):
                # Two selectors is intentionally invalid — exercises the runtime guard.
                await client.redeem_positions(  # pyright: ignore[reportCallIssue]
                    condition_id=_CONDITION_ID, market_id="123"
                )
        finally:
            await client.close()

    asyncio.run(run())


def test_redeem_positions_rejects_neither_argument() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        try:
            with pytest.raises(UserInputError, match="exactly one"):
                # Zero selectors is intentionally invalid — exercises the runtime guard.
                await client.redeem_positions()  # pyright: ignore[reportCallIssue]
        finally:
            await client.close()

    asyncio.run(run())


def test_redeem_positions_accepts_market_id() -> None:
    captured: list[httpx.Request] = []
    market_calls: list[dict[str, object]] = []

    def list_markets_stub(**kwargs: object) -> _StubPaginator:
        market_calls.append(kwargs)
        return _StubPaginator((_market(neg_risk=False),))

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-redeem-mkt")
        client.list_markets = list_markets_stub  # type: ignore[method-assign]
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            await client.redeem_positions(market_id="123")
        finally:
            await client.close()

    asyncio.run(run())
    assert market_calls == [{"ids": [123], "closed": True, "page_size": 1}]
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert len(submit_calls) == 1


def test_redeem_positions_raises_when_market_token_ids_missing() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_market(neg_risk=False, no_token_id=None),)
        )
        try:
            with pytest.raises(UnexpectedResponseError, match="Missing market token IDs"):
                await client.redeem_positions(condition_id=_CONDITION_ID)
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
