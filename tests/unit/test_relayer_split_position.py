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

from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.pagination import Page

_CONDITION_ID = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"


class _StubPaginator:
    def __init__(self, items: tuple[Any, ...]) -> None:
        self._items = items

    async def first_page(self) -> Page[Any]:
        return Page(items=self._items, has_more=False)


def _make_market_stub(neg_risk: bool | None) -> SimpleNamespace:
    return SimpleNamespace(
        id="123",
        condition_id=_CONDITION_ID,
        state=SimpleNamespace(neg_risk=neg_risk),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id="101"),
            no=SimpleNamespace(token_id="202"),
        ),
    )


def test_split_position_uses_collateral_adapter_when_neg_risk_false() -> None:
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
                    "transactionID": "tx-split",
                },
            },
        )
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_make_market_stub(neg_risk=False),)
        )
        try:
            await client.split_position(condition_id=_CONDITION_ID, amount=1_000_000)
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.collateral_adapter.lower()
    assert body["metadata"] == f"Split 1000000 positions for condition {_CONDITION_ID}"


def test_split_position_uses_neg_risk_collateral_adapter_when_neg_risk_true() -> None:
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
                    "transactionID": "tx-split-nr",
                },
            },
        )
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_make_market_stub(neg_risk=True),)
        )
        try:
            await client.split_position(condition_id=_CONDITION_ID, amount=42)
        finally:
            await client.close()

    asyncio.run(run())
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.neg_risk_collateral_adapter.lower()


def test_split_position_rejects_when_market_lookup_finds_nothing() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        client.list_markets = lambda **_: _StubPaginator(())  # type: ignore[method-assign]
        try:
            with pytest.raises(UserInputError, match="No market found"):
                await client.split_position(condition_id=_CONDITION_ID, amount=1)
        finally:
            await client.close()

    asyncio.run(run())


def test_split_position_rejects_when_neg_risk_flag_missing() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        client.list_markets = lambda **_: _StubPaginator(  # type: ignore[method-assign]
            (_make_market_stub(neg_risk=None),)
        )
        try:
            with pytest.raises(UnexpectedResponseError, match="negative-risk"):
                await client.split_position(condition_id=_CONDITION_ID, amount=1)
        finally:
            await client.close()

    asyncio.run(run())
