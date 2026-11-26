"""Controlled RPC and wallet responses isolate sizing and transaction routing."""

# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import json
from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest
from _relayer_helpers import (
    install_relayer_routes,
    install_rpc_handler,
    install_sync_relayer_handler,
    install_sync_rpc_handler,
    make_deposit_client,
    make_sync_deposit_client,
    make_sync_eoa_client,
    make_sync_proxy_client,
    make_sync_safe_client,
)
from data_v2_samples import position_payload
from eth_abi.abi import decode as abi_decode
from eth_abi.abi import encode as abi_encode

from polymarket import (
    SecureClient,
    UserInputError,
    derive_directional_bucket_positions,
    derive_directional_threshold_positions,
)
from polymarket.clients._transport import SyncTransport
from polymarket.transactions import SyncEoaTransactionHandle, SyncGaslessTransactionHandle

EVENT = "0x0400112233445566778899aabbccddeeff000400000000000000000102"
LOW = derive_directional_threshold_positions(event_id=EVENT, line=1)
HIGH = derive_directional_threshold_positions(event_id=EVENT, line=3)


class RpcRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.baskets: list[tuple[int, ...]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        result = (
            [self.respond(item) for item in cast(list[dict[str, Any]], body)]
            if isinstance(body, list)
            else self.respond(body)
        )
        return httpx.Response(200, json=result, request=request)

    def respond(self, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(body)
        method = body["method"]
        if method == "eth_call":
            data = body["params"][0]["data"]
            if data.startswith("0x4e1273f4"):
                _, ids = abi_decode(["address[]", "uint256[]"], bytes.fromhex(data[10:]))
                self.baskets.append(tuple(ids))
                # Realistic base-unit balances, independent of the indexed display quantity.
                result = "0x" + abi_encode(["uint256[]"], [[2_000_000] * len(ids)]).hex()
            else:
                assert data.startswith(("0x70a08231", "0x00fdd58e"))
                balance = 500_000 if data.startswith("0x70a08231") else 2_000_000
                result = "0x" + abi_encode(["uint256"], [balance]).hex()
        elif method == "eth_chainId":
            result = hex(137)
        elif method == "eth_getTransactionCount":
            result = hex(1)
        elif method == "eth_gasPrice":
            result = hex(1_000_000_000)
        elif method == "eth_estimateGas":
            result = hex(200_000)
        elif method == "eth_sendRawTransaction":
            result = "0x" + "a1" * 32
        else:
            raise AssertionError(f"Unexpected RPC method: {method}")
        return {"jsonrpc": "2.0", "id": body["id"], "result": result}


def test_sync_preparation_uses_exact_baskets_and_does_not_submit() -> None:
    rpc = RpcRecorder()
    with make_sync_deposit_client() as client:
        install_sync_rpc_handler(client, rpc)
        merge = client.prepare_merge_directional(HIGH.below_position_id, LOW.above_position_id)
        assert int(merge.data[-64:], 16) == 2_000_000
        assert rpc.baskets[-1] == (int(LOW.above_position_id), int(HIGH.below_position_id))
        split = client.prepare_split_directional(LOW.above_position_id, HIGH.below_position_id)
        assert int(split.data[-64:], 16) == 500_000
        with pytest.raises(UserInputError, match="pUSD"):
            client.prepare_split_directional(
                LOW.above_position_id, HIGH.below_position_id, amount=1_000_000
            )
        client.prepare_merge_event_positions(event_id=EVENT)
        assert rpc.baskets[-1] == tuple(
            int(derive_directional_bucket_positions(event_id=EVENT, bucket_index=i).yes_position_id)
            for i in range(5)
        )
        client.prepare_compose_threshold(event_id=EVENT, line=2, side="below")
        assert rpc.baskets[-1] == tuple(
            int(derive_directional_bucket_positions(event_id=EVENT, bucket_index=i).yes_position_id)
            for i in [0, 1, 4]
        )
        client.prepare_decompose_threshold(event_id=EVENT, line=2, side="above")
        assert rpc.baskets[-1] == (
            int(derive_directional_threshold_positions(event_id=EVENT, line=2).above_position_id),
        )
        void = derive_directional_bucket_positions(event_id=EVENT, bucket_index=4)
        client.prepare_convert_position(position_id=void.no_position_id)
        assert rpc.baskets[-1] == (int(void.no_position_id),)
        assert all(call["method"] == "eth_call" for call in rpc.calls)
        before = len(rpc.calls)
        bad_amounts: tuple[Any, ...] = (True, 0, 1.5, 1 << 256)
        for amount in bad_amounts:
            with pytest.raises(UserInputError):
                client.prepare_merge_directional(
                    LOW.above_position_id, HIGH.below_position_id, amount=amount
                )
        with pytest.raises(UserInputError):
            client.prepare_merge_directional(LOW.above_position_id, LOW.below_position_id)
        assert len(rpc.calls) == before


def test_async_preparation_matches_sync_contract_and_balances() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        rpc = RpcRecorder()
        install_rpc_handler(client, rpc)
        try:
            merge = await client.prepare_merge_directional(
                LOW.above_position_id, HIGH.below_position_id
            )
            split = await client.prepare_split_directional(
                HIGH.below_position_id, LOW.above_position_id
            )
            assert merge.data.startswith("0x77b72427") and int(merge.data[-64:], 16) == 2_000_000
            assert split.data.startswith("0xba860eec") and int(split.data[-64:], 16) == 500_000
            # Local directional conditions must not trigger a market lookup.
            captured: list[httpx.Request] = []
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
                        "transactionID": "directional",
                    },
                },
            )
            await client.split_position(condition_id=LOW.condition_id, amount=1_000_000)
            await client.merge_positions(condition_id=LOW.condition_id, amount="max")
            handle = await client.merge_directional(
                HIGH.below_position_id, LOW.above_position_id, amount=1_000_000
            )
            assert handle.transaction_id == "directional"
            void = derive_directional_bucket_positions(event_id=EVENT, bucket_index=4)
            await client.redeem_positions(condition_id=void.condition_id)
            await client.redeem_positions(position_id=void.no_position_id)
            submissions = [json.loads(r.content) for r in captured if r.url.path == "/submit"]
            assert len(submissions) == 5
            inner = submissions[2]["depositWalletParams"]["calls"][0]
            assert inner["data"].startswith("0x77b72427")
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "factory",
    [make_sync_deposit_client, make_sync_safe_client, make_sync_proxy_client, make_sync_eoa_client],
)
def test_existing_wallet_paths_execute_directional_call(
    factory: Callable[[], SecureClient],
) -> None:
    rpc = RpcRecorder()
    captured: list[dict[str, Any]] = []
    with factory() as client:
        install_sync_rpc_handler(client, rpc)

        def relay(request: httpx.Request) -> httpx.Response:
            if request.url.path in ("/v1/account/transactions/params", "/nonce", "/relay-payload"):
                return httpx.Response(
                    200, json={"address": client._ctx.signer.address, "nonce": "0"}, request=request
                )
            if request.url.path == "/submit":
                captured.append(json.loads(request.content))
                return httpx.Response(
                    200,
                    json={
                        "state": "STATE_NEW",
                        "transactionHash": None,
                        "transactionID": "directional",
                    },
                    request=request,
                )
            raise AssertionError(str(request.url))

        install_sync_relayer_handler(client, relay)
        handle = client.merge_directional(
            LOW.above_position_id, HIGH.below_position_id, amount=1_000_000
        )
        if client.wallet_type == "EOA":
            assert isinstance(handle, SyncEoaTransactionHandle)
            assert not captured
        else:
            assert isinstance(handle, SyncGaslessTransactionHandle)
            assert len(captured) == 1


def test_discovery_reads_all_pages_and_uses_chain_balances() -> None:
    rpc = RpcRecorder()
    requests: list[httpx.Request] = []
    with make_sync_deposit_client() as client:
        install_sync_rpc_handler(client, rpc)

        def data_handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.url.params["filter_amount"] == "0"
            assert request.url.params["user"].lower() == client.wallet.lower()
            first = len(requests) == 1
            position_id = LOW.above_position_id if first else HIGH.below_position_id
            row = position_payload(
                token_id=position_id,
                condition_id=LOW.condition_id if first else HIGH.condition_id,
                current_size="999",
            )
            return httpx.Response(
                200,
                json={
                    "data": [row],
                    "pagination": {"has_more": first, "next_cursor": "next" if first else None},
                },
                request=request,
            )

        transport = SyncTransport(
            base_url="https://data.test",
            client=httpx.Client(
                base_url="https://data.test", transport=httpx.MockTransport(data_handler)
            ),
        )
        client._ctx = dataclasses.replace(client._ctx, data=transport)
        pairs = client.find_directional_pairs(event_id=EVENT)
        assert len(requests) == 2 and len(pairs) == 1
        assert pairs[0].amount == 2_000_000
        assert pairs[0].above_position_id == LOW.above_position_id
