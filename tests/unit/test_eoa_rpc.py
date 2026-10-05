from __future__ import annotations

import asyncio
import json

import httpx

from polymarket._internal.eoa.rpc import JsonRpcClient, SyncJsonRpcClient
from polymarket.clients._transport import AsyncTransport, SyncTransport

_BLOCK_TIMESTAMP = 1_900_000_000
_PATH_BASED_RPC_URL = "https://rpc.test/rpc-key"


def test_async_eth_get_latest_block_timestamp() -> None:
    bodies: list[dict[str, object]] = []
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = json.loads(request.content.decode("utf-8"))
        bodies.append(body)
        urls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"timestamp": hex(_BLOCK_TIMESTAMP)},
            },
            request=request,
        )

    async def run() -> int:
        http_client = httpx.AsyncClient(
            base_url=_PATH_BASED_RPC_URL, transport=httpx.MockTransport(handler)
        )
        client = JsonRpcClient(AsyncTransport(base_url=_PATH_BASED_RPC_URL, client=http_client))
        try:
            return await client.eth_get_latest_block_timestamp()
        finally:
            await http_client.aclose()

    assert asyncio.run(run()) == _BLOCK_TIMESTAMP
    assert bodies[0]["method"] == "eth_getBlockByNumber"
    assert bodies[0]["params"] == ["latest", False]
    assert urls == [_PATH_BASED_RPC_URL]


def test_sync_eth_get_latest_block_timestamp() -> None:
    bodies: list[dict[str, object]] = []
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = json.loads(request.content.decode("utf-8"))
        bodies.append(body)
        urls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"timestamp": hex(_BLOCK_TIMESTAMP)},
            },
            request=request,
        )

    http_client = httpx.Client(base_url=_PATH_BASED_RPC_URL, transport=httpx.MockTransport(handler))
    client = SyncJsonRpcClient(SyncTransport(base_url=_PATH_BASED_RPC_URL, client=http_client))
    try:
        result = client.eth_get_latest_block_timestamp()
    finally:
        http_client.close()

    assert result == _BLOCK_TIMESTAMP
    assert bodies[0]["method"] == "eth_getBlockByNumber"
    assert bodies[0]["params"] == ["latest", False]
    assert urls == [_PATH_BASED_RPC_URL]


def test_async_eth_call_batch_splits_rejected_batches_preserving_order() -> None:
    bodies: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        bodies.append(body)
        if isinstance(body, list):
            return httpx.Response(500, request=request)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": body["params"][0]["data"],
            },
            request=request,
        )

    async def run() -> list[str]:
        http_client = httpx.AsyncClient(
            base_url="https://rpc.test", transport=httpx.MockTransport(handler)
        )
        client = JsonRpcClient(AsyncTransport(base_url="https://rpc.test", client=http_client))
        try:
            return await client.eth_call_batch(_batch_requests())
        finally:
            await http_client.aclose()

    assert asyncio.run(run()) == ["0x11111111", "0x22222222", "0x33333333", "0x44444444"]
    assert len(bodies) == 7


def test_sync_eth_call_batch_splits_rejected_batches_preserving_order() -> None:
    bodies: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        bodies.append(body)
        if isinstance(body, list):
            return httpx.Response(500, request=request)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": body["params"][0]["data"],
            },
            request=request,
        )

    http_client = httpx.Client(base_url="https://rpc.test", transport=httpx.MockTransport(handler))
    client = SyncJsonRpcClient(SyncTransport(base_url="https://rpc.test", client=http_client))
    try:
        result = client.eth_call_batch(_batch_requests())
    finally:
        http_client.close()

    assert result == ["0x11111111", "0x22222222", "0x33333333", "0x44444444"]
    assert len(bodies) == 7


def _batch_requests() -> list[tuple[str, str]]:
    to = "0x0000000000000000000000000000000000000001"
    return [
        (to, "0x11111111"),
        (to, "0x22222222"),
        (to, "0x33333333"),
        (to, "0x44444444"),
    ]
