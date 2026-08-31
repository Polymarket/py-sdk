# pyright: reportPrivateUsage=false
import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlparse

import httpx
import pytest
from _relayer_helpers import (
    install_relayer_routes,
    install_rpc_handler,
    make_deposit_client,
    request_json,
)
from eth_abi.abi import decode as abi_decode
from eth_abi.abi import encode as abi_encode
from eth_utils.crypto import keccak

from polymarket import AsyncSecureClient
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket.calls import merge_v2_call
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.transactions import GaslessTransactionHandle
from polymarket.types import EvmAddress

_COMBO_CONDITION_ID = "0x032def24bfb0c5c57fb236fac08b94236a0000000000000000000000000000"
_CONDITION_ID = "0x" + "11" * 32


def test_split_position_with_combo_legs_bundles_prepare_and_split() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-combo-split")
        try:
            await client.split_position(legs=[_leg_position(2, 1), _leg_position(1, 0)], amount=5)
        finally:
            await client.close()

    asyncio.run(run())
    body = _submit_body(captured)
    calls = _deposit_wallet_calls(body)
    assert calls[0]["target"].lower() == PRODUCTION_CONFIG.combinatorial_module.lower()
    assert calls[1]["target"].lower() == PRODUCTION_CONFIG.protocol_v2_router.lower()
    assert calls[0]["data"].startswith("0x" + keccak(b"prepareCondition(uint256[])")[:4].hex())
    assert calls[1]["data"].startswith("0x" + keccak(b"split(bytes31,uint256)")[:4].hex())
    assert body["metadata"] == f"Split 5 combo positions for condition {_COMBO_CONDITION_ID}"


def test_merge_positions_with_combo_legs_uses_onchain_balances() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-combo-merge")
        install_rpc_handler(client, _eth_call_result("uint256[]", [100, 60]))
        try:
            await client.merge_positions(
                legs=[_leg_position(1, 0), _leg_position(2, 1)], amount="max"
            )
        finally:
            await client.close()

    asyncio.run(run())
    body = _submit_body(captured)
    calls = _deposit_wallet_calls(body)
    assert len(calls) == 2
    assert calls[0]["target"].lower() == PRODUCTION_CONFIG.combinatorial_module.lower()
    assert calls[1]["target"].lower() == PRODUCTION_CONFIG.protocol_v2_router.lower()
    assert calls[1]["data"].startswith("0x" + keccak(b"merge(bytes31,uint256)")[:4].hex())
    assert body["metadata"] == f"Merge 60 combo positions for condition {_COMBO_CONDITION_ID}"


def test_redeem_positions_with_combo_position_id_uses_onchain_balance() -> None:
    captured: list[httpx.Request] = []
    position_id = _combo_position(_COMBO_CONDITION_ID, 1)

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-combo-redeem")
        install_rpc_handler(client, _eth_call_result("uint256", 42))
        try:
            await client.redeem_positions(position_id=position_id)
        finally:
            await client.close()

    asyncio.run(run())
    body = _submit_body(captured)
    calls = _deposit_wallet_calls(body)
    assert len(calls) == 1
    assert calls[0]["target"].lower() == PRODUCTION_CONFIG.protocol_v2_router.lower()
    assert calls[0]["data"].startswith("0x" + keccak(b"redeem(bytes31,uint256,uint256)")[:4].hex())
    assert body["metadata"] == f"Redeem position {position_id}"


def test_split_market_position_routes_position_ids_to_v2_router() -> None:
    captured: list[httpx.Request] = []
    condition_id = "0x01" + "44" * 30

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-v2-split")
        client.list_markets = _async_list_markets_stub(  # type: ignore[method-assign]
            [], (_stub_v2_market(condition_id),)
        )
        try:
            await client.split_position(condition_id=condition_id, amount=5)
        finally:
            await client.close()

    asyncio.run(run())
    calls = _deposit_wallet_calls(_submit_body(captured))
    assert len(calls) == 1
    assert calls[0]["target"].lower() == PRODUCTION_CONFIG.protocol_v2_router.lower()
    assert calls[0]["data"].startswith("0x" + keccak(b"split(bytes31,uint256)")[:4].hex())


def test_merge_market_position_routes_position_ids_to_v2_router() -> None:
    captured: list[httpx.Request] = []
    condition_id = "0x02" + "55" * 30

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-v2-merge")
        client.list_markets = _async_list_markets_stub(  # type: ignore[method-assign]
            [], (_stub_v2_market(condition_id),)
        )
        install_rpc_handler(client, _eth_call_result("uint256[]", [100, 60]))
        try:
            await client.merge_positions(condition_id=condition_id, amount="max")
        finally:
            await client.close()

    asyncio.run(run())
    calls = _deposit_wallet_calls(_submit_body(captured))
    assert len(calls) == 1
    assert calls[0]["target"].lower() == PRODUCTION_CONFIG.protocol_v2_router.lower()
    assert calls[0]["data"].startswith("0x" + keccak(b"merge(bytes31,uint256)")[:4].hex())
    assert calls[0]["data"][-64:] == f"{60:064x}"


def test_redeem_market_position_emits_one_v2_call_per_nonzero_outcome() -> None:
    captured: list[httpx.Request] = []
    condition_id = "0x03" + "66" * 30

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-v2-redeem")
        client.list_markets = _async_list_markets_stub(  # type: ignore[method-assign]
            [], (_stub_v2_market(condition_id),)
        )
        install_rpc_handler(client, _eth_call_result("uint256[]", [12, 34]))
        try:
            await client.redeem_positions(condition_id=condition_id)
        finally:
            await client.close()

    asyncio.run(run())
    calls = _deposit_wallet_calls(_submit_body(captured))
    assert len(calls) == 2
    assert {call["target"].lower() for call in calls} == {
        PRODUCTION_CONFIG.protocol_v2_router.lower()
    }
    selector = "0x" + keccak(b"redeem(bytes31,uint256,uint256)")[:4].hex()
    assert all(call["data"].startswith(selector) for call in calls)


def test_execute_transaction_async_batches_custom_calls() -> None:
    captured: list[httpx.Request] = []
    router = EvmAddress(PRODUCTION_CONFIG.protocol_v2_router)

    async def run() -> object:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-execute")
        try:
            return await client.execute_transaction(
                calls=[
                    merge_v2_call(router=router, condition_id="0x03" + "11" * 30, amount=1),
                    merge_v2_call(router=router, condition_id="0x03" + "22" * 30, amount=2),
                    merge_v2_call(router=router, condition_id="0x03" + "33" * 30, amount=3),
                ],
                metadata="Merge 3 combo positions",
            )
        finally:
            await client.close()

    handle = asyncio.run(run())

    assert isinstance(handle, GaslessTransactionHandle)
    body = _submit_body(captured)
    calls = _deposit_wallet_calls(body)
    assert len(calls) == 3
    assert body["metadata"] == "Merge 3 combo positions"
    assert {call["target"].lower() for call in calls} == {router.lower()}


def test_merge_multiple_positions_async_batches_combo_merges() -> None:
    captured: list[httpx.Request] = []

    async def run() -> object:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-merge-multiple")
        install_rpc_handler(client, _eth_call_result("uint256[]", [100, 60]))
        try:
            return await client.merge_multiple_positions(
                positions=[
                    {"position_id": _combo_position("0x03" + "11" * 30, 0), "amount": 1},
                    {"position_id": _combo_position("0x03" + "22" * 30, 1), "amount": "max"},
                    {"position_id": _combo_position("0x03" + "33" * 30, 0)},
                ],
                metadata="Merge selected combo positions",
            )
        finally:
            await client.close()

    handle = asyncio.run(run())

    assert isinstance(handle, GaslessTransactionHandle)
    body = _submit_body(captured)
    calls = _deposit_wallet_calls(body)
    assert len(calls) == 3
    assert body["metadata"] == "Merge selected combo positions"
    assert {call["target"].lower() for call in calls} == {
        PRODUCTION_CONFIG.protocol_v2_router.lower()
    }
    assert [call["data"][-64:] for call in calls] == [
        f"{1:064x}",
        f"{60:064x}",
        f"{60:064x}",
    ]


def test_merge_multiple_positions_async_batches_market_merges() -> None:
    captured: list[httpx.Request] = []
    first_condition_id = "0x" + "11" * 32
    second_condition_id = "0x" + "22" * 32
    market_calls: list[dict[str, object]] = []

    async def run() -> object:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-market-merge-multiple")

        def list_markets_stub(**kwargs: object):  # type: ignore[no-untyped-def]
            market_calls.append(kwargs)
            condition_ids = kwargs.get("condition_ids")
            if condition_ids == [first_condition_id]:
                return _AsyncStubPaginator((_stub_market(first_condition_id),))
            if condition_ids == [second_condition_id]:
                return _AsyncStubPaginator((_stub_market(second_condition_id),))
            return _AsyncStubPaginator(())

        client.list_markets = list_markets_stub  # type: ignore[method-assign]
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        install_rpc_handler(client, _eth_call_result("uint256[]", [100_000_000, 60_000_000]))
        try:
            return await client.merge_multiple_positions(
                positions=[
                    {"condition_id": first_condition_id, "amount": 1_000_000},
                    {"condition_id": second_condition_id, "amount": "max"},
                ],
                metadata="Merge selected market positions",
            )
        finally:
            await client.close()

    handle = asyncio.run(run())

    assert isinstance(handle, GaslessTransactionHandle)
    assert market_calls == [
        {"condition_ids": [first_condition_id], "page_size": 1},
        {"condition_ids": [second_condition_id], "page_size": 1},
    ]
    body = _submit_body(captured)
    calls = _deposit_wallet_calls(body)
    assert len(calls) == 2
    assert body["metadata"] == "Merge selected market positions"
    assert {call["target"].lower() for call in calls} == {
        PRODUCTION_CONFIG.neg_risk_collateral_adapter.lower()
    }
    assert [_decode_merge_positions_amount(call["data"]) for call in calls] == [
        1_000_000,
        60_000_000,
    ]


def test_merge_multiple_positions_async_rejects_mixed_market_and_combo_positions() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        try:
            await client.merge_multiple_positions(
                positions=[
                    {"condition_id": _CONDITION_ID},
                    {"position_id": _combo_position(_COMBO_CONDITION_ID, 0)},
                ]
            )
        finally:
            await client.close()

    with pytest.raises(UserInputError, match="Cannot mix market and combo"):
        asyncio.run(run())


def test_redeem_positions_market_id_resolves_condition_before_fetching_positions() -> None:
    captured: list[httpx.Request] = []
    market_calls: list[dict[str, object]] = []

    async def run() -> None:
        client = await make_deposit_client()
        _setup_relayer(client, captured, "tx-market-redeem")
        client.list_markets = _async_list_markets_stub(  # type: ignore[method-assign]
            market_calls, (_stub_market(_CONDITION_ID),)
        )
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        try:
            await client.redeem_positions(market_id="123")
        finally:
            await client.close()

    asyncio.run(run())

    assert market_calls == [{"ids": [123], "closed": True, "page_size": 1}]
    body = _submit_body(captured)
    calls = _deposit_wallet_calls(body)
    assert calls[0]["target"].lower() == PRODUCTION_CONFIG.neg_risk_collateral_adapter.lower()


def test_redeem_positions_market_id_rejects_non_integer() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        try:
            await client.redeem_positions(market_id="not-an-int")
        finally:
            await client.close()

    with pytest.raises(UserInputError, match="Market ID must be an integer"):
        asyncio.run(run())


def test_redeem_positions_market_id_raises_when_condition_missing() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        client.list_markets = _async_list_markets_stub(  # type: ignore[method-assign]
            [],
            (_stub_market(None),),
        )
        try:
            await client.redeem_positions(market_id="123")
        finally:
            await client.close()

    with pytest.raises(UnexpectedResponseError, match="Missing condition ID for market 123"):
        asyncio.run(run())


def _setup_relayer(client: AsyncSecureClient, captured: list[httpx.Request], tx_id: str) -> None:
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


def _eth_call_result(abi_type: str, value: object) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
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


def _decode_merge_positions_amount(data: str) -> int:
    decoded = abi_decode(
        ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
        bytes.fromhex(data[10:]),
    )
    amount = decoded[4]
    assert isinstance(amount, int)
    return amount


def _submit_body(captured: list[httpx.Request]) -> dict[str, object]:
    submit = [request for request in captured if urlparse(str(request.url)).path == "/submit"][0]
    body = request_json(submit)
    assert isinstance(body, dict)
    return cast(dict[str, object], body)


def _deposit_wallet_calls(body: dict[str, object]) -> list[dict[str, str]]:
    raw_params = body["depositWalletParams"]
    assert isinstance(raw_params, dict)
    params = cast(dict[str, object], raw_params)
    calls = params["calls"]
    assert isinstance(calls, list)
    return cast(list[dict[str, str]], calls)


def _stub_market(condition_id: str | None):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        id="123",
        condition_id=condition_id,
        state=SimpleNamespace(neg_risk=True),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id="101"),
            no=SimpleNamespace(token_id="202"),
        ),
    )


def _stub_v2_market(condition_id: str):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        id="123",
        condition_id=condition_id,
        state=SimpleNamespace(neg_risk=None),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id=None, position_id=_combo_position(condition_id, 0)),
            no=SimpleNamespace(token_id=None, position_id=_combo_position(condition_id, 1)),
        ),
    )


def _fail_list_positions(**_: object) -> None:
    raise AssertionError("list_positions should not be called")


class _AsyncStubPaginator:
    def __init__(self, items: tuple[object, ...]) -> None:
        self._items = items

    async def first_page(self):  # type: ignore[no-untyped-def]
        from polymarket.pagination import Page

        return Page(
            items=self._items,
            has_more=False,
            next_cursor=None,
            total_count=len(self._items),
        )


def _async_list_markets_stub(calls: list[dict[str, object]], items: tuple[object, ...]):  # type: ignore[no-untyped-def]
    def list_markets(**kwargs: object):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        return _AsyncStubPaginator(items)

    return list_markets


def _leg_position(marker: int, outcome: int) -> str:
    raw = bytearray(32)
    raw[0] = 1
    raw[30] = marker
    raw[31] = outcome
    return str(int("0x" + raw.hex(), 16))


def _combo_position(condition_id: str, outcome: int) -> str:
    return str(int(f"{condition_id}{outcome:02x}", 16))
