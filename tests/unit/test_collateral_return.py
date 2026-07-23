# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import json
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from _relayer_helpers import (
    install_combos_handler,
    install_combos_routes,
    install_relayer_routes,
    install_rpc_handler,
    install_sync_combos_handler,
    install_sync_relayer_handler,
    install_sync_rpc_handler,
    make_deposit_client,
    make_eoa_client,
    make_proxy_client,
    make_safe_client,
    make_sync_deposit_client,
    request_json,
    trading_approval_rpc_handler,
)

from polymarket import CollateralReturnOperationKind, CollateralReturnPlan
from polymarket.environments import PRODUCTION
from polymarket.errors import (
    CollateralReturnPlanRejectedError,
    MissingTradingApprovalsError,
    UnexpectedResponseError,
    UserInputError,
)

_PLAN_HASH = "0x" + "ab" * 32
_ROUTER_DATA = "0x" + "1234" * 8
_CONDITION_ID = "0x03" + "cd" * 30
_EVENT_ID = "0x" + "ee" * 32
_OTHER_WALLET = "0x1111111111111111111111111111111111111111"
_SUBMIT_PATH = "/v1/collateral-return/submit"
_PLAN_PATH = "/v1/collateral-return/plan"
_NONCE_PATH = "/v1/account/transactions/params"

_SUBMIT_OK = {
    "state": "STATE_NEW",
    "transactionHash": None,
    "transactionID": "tx-collateral-return",
}


def _plan_payload(*, wallet: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "plan_hash": _PLAN_HASH,
        "chain_id": 137,
        "wallet": wallet,
        "block_number": "78123456",
        "starting_pusd": "18.983692",
        "net_pusd_out": "1",
        "final_pusd": "19.983692",
        "required_pusd_input": "0.5",
        "operations": [
            {"kind": "merge", "condition_id": _CONDITION_ID, "amount": "1000000"},
            {"kind": "redeem", "position_id": "42", "condition_index": 2, "amount": "500000"},
        ],
        "operation_count": 2,
        "truncated": False,
        "estimated_cost": "7",
        "required_positions": [{"position_id": "42", "amount": "1000000"}],
        "position_summary": {
            "consumed": [{"position_id": "42", "amount": "1000000"}],
            "created": [],
        },
        "candidate_position_ids": ["42"],
        "router_call": {"to": PRODUCTION.protocol_v2_router, "data": _ROUTER_DATA},
    }
    payload.update(overrides)
    return payload


def test_plan_parses_wire_shape() -> None:
    plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=_OTHER_WALLET))

    assert plan.plan_hash == _PLAN_HASH
    assert plan.wallet == _OTHER_WALLET
    assert plan.chain_id == 137
    assert plan.block_number == 78123456
    assert plan.starting_collateral == Decimal("18.983692")
    assert plan.collateral_returned == Decimal("1")
    assert plan.final_collateral == Decimal("19.983692")
    assert plan.required_collateral == Decimal("0.5")
    assert plan.truncated is False
    assert plan.router_call.to == PRODUCTION.protocol_v2_router
    assert plan.router_call.data == _ROUTER_DATA

    merge, redeem = plan.operations
    assert merge.kind is CollateralReturnOperationKind.MERGE
    assert merge.condition_id == _CONDITION_ID
    assert merge.condition_index == 0
    assert merge.amount == Decimal("1")
    assert redeem.kind == "redeem"
    assert redeem.position_id == "42"
    assert redeem.condition_index == 2
    assert redeem.amount == Decimal("0.5")

    assert plan.required_positions[0].position_id == "42"
    assert plan.required_positions[0].amount == Decimal("1")
    assert plan.position_summary.consumed[0].amount == Decimal("1")
    assert plan.position_summary.created == ()

    assert not hasattr(plan, "estimated_cost")
    assert not hasattr(plan, "operation_count")
    assert not hasattr(plan, "candidate_position_ids")


def test_plan_parses_unknown_kind_and_event_operations() -> None:
    plan = CollateralReturnPlan.parse_response(
        _plan_payload(
            wallet=_OTHER_WALLET,
            operations=[
                {"kind": "quantum_fold", "amount": "1"},
                {"kind": "merge_on_event", "event_id": _EVENT_ID, "amount": "2000000"},
            ],
        )
    )

    unknown, on_event = plan.operations
    assert unknown.kind == "quantum_fold"
    assert not isinstance(unknown.kind, CollateralReturnOperationKind)
    assert unknown.amount == Decimal("0.000001")
    assert on_event.kind is CollateralReturnOperationKind.MERGE_ON_EVENT
    assert on_event.event_id == _EVENT_ID
    assert on_event.condition_id is None


def test_plan_normalizes_suffixed_condition_ids() -> None:
    plan = CollateralReturnPlan.parse_response(
        _plan_payload(
            wallet=_OTHER_WALLET,
            operations=[
                {"kind": "merge", "condition_id": _CONDITION_ID + "00", "amount": "1000000"}
            ],
        )
    )

    assert plan.operations[0].condition_id == _CONDITION_ID


def test_plan_rejects_non_integer_base_unit_amounts() -> None:
    with pytest.raises(UnexpectedResponseError):
        CollateralReturnPlan.parse_response(
            _plan_payload(
                wallet=_OTHER_WALLET,
                operations=[{"kind": "merge", "amount": "1.5"}],
            )
        )


def test_plan_parses_empty_plan_with_omitted_zero_fields() -> None:
    plan = CollateralReturnPlan.parse_response(
        {
            "plan_hash": _PLAN_HASH,
            "chain_id": 137,
            "wallet": _OTHER_WALLET,
            "block_number": "1",
            "starting_pusd": "0",
            "net_pusd_out": "0",
            "final_pusd": "0",
            "required_pusd_input": "0",
            "router_call": {"to": PRODUCTION.protocol_v2_router, "data": "0x"},
        }
    )

    assert plan.operations == ()
    assert plan.required_positions == ()
    assert plan.truncated is False
    assert plan.position_summary.consumed == ()
    assert plan.position_summary.created == ()


def test_plan_collateral_return_posts_wallet() -> None:
    captured: list[httpx.Request] = []
    wallet = ""

    async def run() -> None:
        nonlocal wallet
        client = await make_deposit_client()
        wallet = str(client.wallet)
        install_combos_routes(
            client,
            captured,
            {_PLAN_PATH: _plan_payload(wallet=wallet)},
        )
        try:
            plan = await client.plan_collateral_return()
            assert plan.wallet == wallet
        finally:
            await client.close()

    asyncio.run(run())
    assert len(captured) == 1
    request = captured[0]
    assert urlparse(str(request.url)).path == _PLAN_PATH
    assert request_json(request) == {"wallet": wallet}


def test_execute_submits_router_call_for_deposit_wallet() -> None:
    relayer_captured: list[httpx.Request] = []
    submit_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            relayer_captured,
            {_NONCE_PATH: {"address": client._ctx.signer.address, "nonce": "3"}},
        )
        install_combos_routes(client, submit_captured, {_SUBMIT_PATH: _SUBMIT_OK})
        install_rpc_handler(client, trading_approval_rpc_handler(allowance=10**12, approved=True))
        plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            handle = await client.execute_collateral_return_plan(plan=plan)
            assert handle.transaction_id == "tx-collateral-return"
        finally:
            await client.close()

    asyncio.run(run())
    assert len(submit_captured) == 1
    body = request_json(submit_captured[0])
    assert body["plan_hash"] == _PLAN_HASH
    envelope = body["envelope"]
    assert envelope["type"] == "WALLET"
    assert envelope["nonce"] == "3"
    assert envelope["metadata"] == "Collateral return"
    assert envelope["depositWalletParams"]["calls"] == [
        {"target": PRODUCTION.protocol_v2_router, "value": "0", "data": _ROUTER_DATA}
    ]


def test_execute_submits_direct_safe_call() -> None:
    relayer_captured: list[httpx.Request] = []
    submit_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_safe_client()
        install_relayer_routes(
            client,
            relayer_captured,
            {_NONCE_PATH: {"address": client._ctx.signer.address, "nonce": "0"}},
        )
        install_combos_routes(client, submit_captured, {_SUBMIT_PATH: _SUBMIT_OK})
        install_rpc_handler(client, trading_approval_rpc_handler(allowance=10**12, approved=True))
        plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            await client.execute_collateral_return_plan(plan=plan)
        finally:
            await client.close()

    asyncio.run(run())
    envelope = request_json(submit_captured[0])["envelope"]
    assert envelope["type"] == "SAFE"
    assert envelope["to"] == PRODUCTION.protocol_v2_router
    assert envelope["data"] == _ROUTER_DATA
    assert envelope["signatureParams"]["operation"] == "0"
    assert "value" not in envelope


def test_execute_submits_proxy_factory_call() -> None:
    relayer_captured: list[httpx.Request] = []
    submit_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_proxy_client()
        install_relayer_routes(
            client,
            relayer_captured,
            {_NONCE_PATH: {"address": client._ctx.signer.address, "nonce": "0"}},
        )
        install_combos_routes(client, submit_captured, {_SUBMIT_PATH: _SUBMIT_OK})
        install_rpc_handler(client, trading_approval_rpc_handler(allowance=10**12, approved=True))
        plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            await client.execute_collateral_return_plan(plan=plan)
        finally:
            await client.close()

    asyncio.run(run())
    envelope = request_json(submit_captured[0])["envelope"]
    assert envelope["type"] == "PROXY"
    assert envelope["to"] == PRODUCTION.wallet_derivation.proxy_factory
    assert envelope["signatureParams"]["gasPrice"] == "0"
    assert envelope["signatureParams"]["relayerFee"] == "0"


def test_plan_and_execute_reject_eoa_wallets() -> None:
    async def run() -> None:
        client = await make_eoa_client()
        plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            with pytest.raises(UserInputError, match="EOA"):
                await client.plan_collateral_return()
            with pytest.raises(UserInputError, match="EOA"):
                await client.execute_collateral_return_plan(plan=plan)
        finally:
            await client.close()

    asyncio.run(run())


def test_execute_rejects_plan_for_other_wallet() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=_OTHER_WALLET))
        try:
            with pytest.raises(UserInputError, match="does not match"):
                await client.execute_collateral_return_plan(plan=plan)
        finally:
            await client.close()

    asyncio.run(run())


def test_execute_rejects_plan_for_other_chain() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        plan = CollateralReturnPlan.parse_response(
            _plan_payload(wallet=str(client.wallet), chain_id=80002)
        )
        try:
            with pytest.raises(UserInputError, match="chain id"):
                await client.execute_collateral_return_plan(plan=plan)
        finally:
            await client.close()

    asyncio.run(run())


def test_execute_rejects_plan_without_operations() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        plan = CollateralReturnPlan.parse_response(
            _plan_payload(wallet=str(client.wallet), operations=[])
        )
        try:
            with pytest.raises(UserInputError, match="no operations"):
                await client.execute_collateral_return_plan(plan=plan)
        finally:
            await client.close()

    asyncio.run(run())


def test_execute_fails_fast_on_missing_approvals() -> None:
    relayer_captured: list[httpx.Request] = []
    submit_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            relayer_captured,
            {_NONCE_PATH: {"address": client._ctx.signer.address, "nonce": "0"}},
        )
        install_combos_routes(client, submit_captured, {_SUBMIT_PATH: _SUBMIT_OK})
        install_rpc_handler(client, trading_approval_rpc_handler(allowance=0, approved=False))
        plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            with pytest.raises(MissingTradingApprovalsError, match="setup_trading_approvals"):
                await client.execute_collateral_return_plan(plan=plan)
        finally:
            await client.close()

    asyncio.run(run())
    assert relayer_captured == []
    assert submit_captured == []


def test_execute_skips_approval_check_when_plan_needs_no_inputs() -> None:
    relayer_captured: list[httpx.Request] = []
    submit_captured: list[httpx.Request] = []
    rpc_captured: list[httpx.Request] = []

    def rpc_handler(request: httpx.Request) -> httpx.Response:
        rpc_captured.append(request)
        return httpx.Response(500, json={"error": "unexpected rpc call"}, request=request)

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            relayer_captured,
            {_NONCE_PATH: {"address": client._ctx.signer.address, "nonce": "0"}},
        )
        install_combos_routes(client, submit_captured, {_SUBMIT_PATH: _SUBMIT_OK})
        install_rpc_handler(client, rpc_handler)
        plan = CollateralReturnPlan.parse_response(
            _plan_payload(
                wallet=str(client.wallet),
                required_pusd_input="0",
                required_positions=[],
            )
        )
        try:
            handle = await client.execute_collateral_return_plan(plan=plan)
            assert handle.transaction_id == "tx-collateral-return"
        finally:
            await client.close()

    asyncio.run(run())
    assert rpc_captured == []
    assert len(submit_captured) == 1


def test_execute_maps_409_to_plan_rejected_without_retry() -> None:
    relayer_captured: list[httpx.Request] = []
    submit_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submit_count
        submit_count += 1
        return httpx.Response(
            409, json={"error": "fresh plan required: state changed"}, request=request
        )

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(
            client,
            relayer_captured,
            {_NONCE_PATH: {"address": client._ctx.signer.address, "nonce": "0"}},
        )
        install_combos_handler(client, handler)
        install_rpc_handler(client, trading_approval_rpc_handler(allowance=10**12, approved=True))
        plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            with pytest.raises(CollateralReturnPlanRejectedError, match="fresh plan required"):
                await client.execute_collateral_return_plan(plan=plan)
        finally:
            await client.close()

    asyncio.run(run())
    assert submit_count == 1


def test_execute_resubmits_with_fresh_nonce_on_transient_wallet_busy() -> None:
    relayer_captured: list[httpx.Request] = []
    submit_bodies: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        submit_bodies.append(json.loads(request.content.decode("utf-8")))
        if len(submit_bodies) == 1:
            return httpx.Response(
                400, json={"error": "wallet busy with an active action"}, request=request
            )
        return httpx.Response(200, json=_SUBMIT_OK, request=request)

    async def run() -> None:
        client = await make_deposit_client()
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=dataclasses.replace(PRODUCTION, relayer_poll_frequency_ms=0),
        )
        install_relayer_routes(
            client,
            relayer_captured,
            {_NONCE_PATH: {"address": client._ctx.signer.address, "nonce": "5"}},
        )
        install_combos_handler(client, handler)
        install_rpc_handler(client, trading_approval_rpc_handler(allowance=10**12, approved=True))
        plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            handle = await client.execute_collateral_return_plan(plan=plan)
            assert handle.transaction_id == "tx-collateral-return"
        finally:
            await client.close()

    asyncio.run(run())
    assert len(submit_bodies) == 2
    nonce_fetches = [
        request for request in relayer_captured if urlparse(str(request.url)).path == _NONCE_PATH
    ]
    assert len(nonce_fetches) == 2


def test_sync_execute_submits_router_call_for_deposit_wallet() -> None:
    relayer_captured: list[httpx.Request] = []
    submit_captured: list[httpx.Request] = []

    def relayer_handler(request: httpx.Request) -> httpx.Response:
        relayer_captured.append(request)
        return httpx.Response(200, json={"address": "0x0", "nonce": "9"}, request=request)

    def submit_handler(request: httpx.Request) -> httpx.Response:
        submit_captured.append(request)
        return httpx.Response(200, json=_SUBMIT_OK, request=request)

    client = make_sync_deposit_client()
    install_sync_relayer_handler(client, relayer_handler)
    install_sync_combos_handler(client, submit_handler)
    install_sync_rpc_handler(client, trading_approval_rpc_handler(allowance=10**12, approved=True))
    plan = CollateralReturnPlan.parse_response(_plan_payload(wallet=str(client.wallet)))
    try:
        handle = client.execute_collateral_return_plan(plan=plan)
        assert handle.transaction_id == "tx-collateral-return"
    finally:
        client.close()

    body = request_json(submit_captured[0])
    assert body["plan_hash"] == _PLAN_HASH
    assert body["envelope"]["nonce"] == "9"
    assert body["envelope"]["depositWalletParams"]["calls"] == [
        {"target": PRODUCTION.protocol_v2_router, "value": "0", "data": _ROUTER_DATA}
    ]
