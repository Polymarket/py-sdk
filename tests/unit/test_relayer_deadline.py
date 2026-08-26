# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Callable

import httpx
import pytest
from _relayer_helpers import (
    SPENDER,
    TOKEN,
    install_rpc_handler,
    install_sync_rpc_handler,
    make_deposit_client,
    make_sync_deposit_client,
)

from polymarket import AsyncSecureClient, SecureClient
from polymarket._internal.actions.relayer.calls import TransactionCall, erc20_approval_call
from polymarket._internal.actions.relayer.gasless import (
    build_signed_deposit_wallet_batch,
    build_signed_deposit_wallet_batch_sync,
)
from polymarket._internal.environment import with_environment_config
from polymarket.types import EvmAddress

_WALL_CLOCK_TIMESTAMP = 1_000
_DEADLINE_WINDOW = 600


def test_async_deposit_wallet_deadline_uses_custom_chain_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain_timestamp = 2_000
    captured: list[dict[str, object]] = []

    async def run() -> str:
        client = await make_deposit_client()
        _use_custom_rpc_async(client)
        install_rpc_handler(client, _latest_block_handler(chain_timestamp, captured))
        try:
            batch = await build_signed_deposit_wallet_batch(
                client._ctx,
                calls=[_approval_call()],
                nonce="3",
            )
            return batch.deadline
        finally:
            await client.close()

    monkeypatch.setattr(
        "polymarket._internal.actions.relayer.gasless.time.time",
        lambda: _WALL_CLOCK_TIMESTAMP,
    )

    assert asyncio.run(run()) == str(chain_timestamp + _DEADLINE_WINDOW)
    assert [body["method"] for body in captured] == ["eth_getBlockByNumber"]


def test_sync_deposit_wallet_deadline_does_not_precede_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain_timestamp = 500
    captured: list[dict[str, object]] = []
    client = make_sync_deposit_client()
    _use_custom_rpc_sync(client)
    install_sync_rpc_handler(client, _latest_block_handler(chain_timestamp, captured))
    monkeypatch.setattr(
        "polymarket._internal.actions.relayer.gasless.time.time",
        lambda: _WALL_CLOCK_TIMESTAMP,
    )
    try:
        batch = build_signed_deposit_wallet_batch_sync(
            client._ctx,
            calls=[_approval_call()],
            nonce="3",
        )
    finally:
        client.close()

    assert batch.deadline == str(_WALL_CLOCK_TIMESTAMP + _DEADLINE_WINDOW)
    assert [body["method"] for body in captured] == ["eth_getBlockByNumber"]


def _use_custom_rpc_async(client: AsyncSecureClient) -> None:
    context = client._ctx
    environment = with_environment_config(
        context.environment,
        config=dataclasses.replace(context.environment_config, rpc_url="https://rpc.test"),
    )
    client._ctx = dataclasses.replace(context, environment=environment)


def _use_custom_rpc_sync(client: SecureClient) -> None:
    context = client._ctx
    environment = with_environment_config(
        context.environment,
        config=dataclasses.replace(context.environment_config, rpc_url="https://rpc.test"),
    )
    client._ctx = dataclasses.replace(context, environment=environment)


def _latest_block_handler(
    timestamp: int,
    captured: list[dict[str, object]],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = json.loads(request.content.decode("utf-8"))
        captured.append(body)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"timestamp": hex(timestamp)},
            },
            request=request,
        )

    return handler


def _approval_call() -> TransactionCall:
    return erc20_approval_call(
        token_address=EvmAddress(TOKEN),
        spender=EvmAddress(SPENDER),
        amount=1,
    )
