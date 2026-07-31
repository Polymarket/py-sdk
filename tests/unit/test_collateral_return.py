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
    install_sync_combos_handler,
    install_sync_relayer_handler,
    make_deposit_client,
    make_eoa_client,
    make_sync_deposit_client,
    request_json,
)

from polymarket import CollateralReturnOperationKind, CollateralReturnPlanResponse
from polymarket.environments import PRODUCTION
from polymarket.errors import (
    RequestRejectedError,
    UnexpectedResponseError,
    UserInputError,
)

_PLAN_HASH = "0x" + "ab" * 32
_ROUTER_DATA = "0x" + "1234" * 8
_CONDITION_ID = "0x03" + "cd" * 30
_EVENT_ID = "0x" + "ee" * 32
_OTHER_WALLET = "0x1111111111111111111111111111111111111111"
_SUBMIT_PATH = "/v1/collateral-return/submit"
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
            {"kind": "merge", "condition_id": _CONDITION_ID + "00", "amount": "1000000"},
            {"kind": "redeem", "position_id": "42", "condition_index": 2, "amount": "500000"},
        ],
        "operation_count": 2,
        "truncated": False,
        "estimated_cost": 7,
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


def _nonce_route(client: Any, nonce: str = "0") -> dict[str, Any]:
    return {_NONCE_PATH: {"address": client._ctx.signer.address, "nonce": nonce}}


def test_plan_parses_wire_shape() -> None:
    plan = CollateralReturnPlanResponse.parse_response(_plan_payload(wallet=_OTHER_WALLET))

    assert plan.block_number == 78123456
    assert plan.net_pusd_out == Decimal("1")
    assert plan.operation_count == 2
    assert plan.estimated_cost == 7
    assert plan.candidate_position_ids == ("42",)
    merge = plan.operations[0]
    assert merge.kind is CollateralReturnOperationKind.MERGE
    assert merge.condition_id == _CONDITION_ID  # outcome-suffixed wire id is normalized
    assert merge.amount == Decimal("1")  # e6 base units scaled to collateral units


def test_plan_parses_unknown_kinds_as_plain_strings() -> None:
    plan = CollateralReturnPlanResponse.parse_response(
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
    assert on_event.kind is CollateralReturnOperationKind.MERGE_ON_EVENT


def test_plan_rejects_malformed_base_unit_amounts() -> None:
    for amount in ("1.5", "-1000000"):
        with pytest.raises(UnexpectedResponseError):
            CollateralReturnPlanResponse.parse_response(
                _plan_payload(
                    wallet=_OTHER_WALLET, operations=[{"kind": "merge", "amount": amount}]
                )
            )


def test_plan_requires_service_fields() -> None:
    payload = _plan_payload(wallet=_OTHER_WALLET)
    del payload["operations"]

    with pytest.raises(UnexpectedResponseError):
        CollateralReturnPlanResponse.parse_response(payload)


def test_plan_tolerates_missing_position_summary() -> None:
    payload = _plan_payload(
        wallet=_OTHER_WALLET,
        operations=[],
        operation_count=0,
        required_positions=[],
        candidate_position_ids=[],
    )
    del payload["position_summary"]

    plan = CollateralReturnPlanResponse.parse_response(payload)

    assert plan.position_summary.consumed == ()
    assert plan.position_summary.created == ()


def test_plan_json_round_trips_scaled_amounts() -> None:
    plan = CollateralReturnPlanResponse.parse_response(_plan_payload(wallet=_OTHER_WALLET))

    restored = CollateralReturnPlanResponse.model_validate_json(plan.model_dump_json())

    assert restored == plan


def test_execute_submits_router_call_for_deposit_wallet() -> None:
    submit_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(client, [], _nonce_route(client))
        install_combos_routes(client, submit_captured, {_SUBMIT_PATH: _SUBMIT_OK})
        plan = CollateralReturnPlanResponse.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            handle = await client.execute_collateral_return_plan(plan=plan)
            assert handle.transaction_id == "tx-collateral-return"
        finally:
            await client.close()

    asyncio.run(run())
    body = request_json(submit_captured[0])
    assert body["plan_hash"] == _PLAN_HASH
    assert body["envelope"]["type"] == "WALLET"
    assert body["envelope"]["depositWalletParams"]["calls"] == [
        {"target": PRODUCTION.protocol_v2_router, "value": "0", "data": _ROUTER_DATA}
    ]


def test_sync_execute_submits_router_call_for_deposit_wallet() -> None:
    submit_captured: list[httpx.Request] = []

    def relayer_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"address": "0x0", "nonce": "9"}, request=request)

    def submit_handler(request: httpx.Request) -> httpx.Response:
        submit_captured.append(request)
        return httpx.Response(200, json=_SUBMIT_OK, request=request)

    client = make_sync_deposit_client()
    install_sync_relayer_handler(client, relayer_handler)
    install_sync_combos_handler(client, submit_handler)
    plan = CollateralReturnPlanResponse.parse_response(_plan_payload(wallet=str(client.wallet)))
    try:
        handle = client.execute_collateral_return_plan(plan=plan)
        assert handle.transaction_id == "tx-collateral-return"
    finally:
        client.close()

    assert len(submit_captured) == 1  # submit body shape is asserted by the async twin


def test_plan_and_execute_reject_eoa_wallets() -> None:
    async def run() -> None:
        client = await make_eoa_client()
        plan = CollateralReturnPlanResponse.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            with pytest.raises(UserInputError, match="EOA"):
                await client.plan_collateral_return()
            with pytest.raises(UserInputError, match="EOA"):
                await client.execute_collateral_return_plan(plan=plan)
        finally:
            await client.close()

    asyncio.run(run())


def test_execute_rejects_mismatched_plans() -> None:
    async def run() -> None:
        client = await make_deposit_client()
        wallet = str(client.wallet)
        try:
            with pytest.raises(UserInputError, match="does not match"):
                await client.execute_collateral_return_plan(
                    plan=CollateralReturnPlanResponse.parse_response(
                        _plan_payload(wallet=_OTHER_WALLET)
                    )
                )
            with pytest.raises(UserInputError, match="chain id"):
                await client.execute_collateral_return_plan(
                    plan=CollateralReturnPlanResponse.parse_response(
                        _plan_payload(wallet=wallet, chain_id=80002)
                    )
                )
        finally:
            await client.close()

    asyncio.run(run())


def test_execute_does_not_retry_plan_rejections() -> None:
    submit_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submit_count
        submit_count += 1
        return httpx.Response(
            409, json={"error": "fresh plan required: state changed"}, request=request
        )

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(client, [], _nonce_route(client))
        install_combos_handler(client, handler)
        plan = CollateralReturnPlanResponse.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            with pytest.raises(RequestRejectedError, match="fresh plan required") as excinfo:
                await client.execute_collateral_return_plan(plan=plan)
            assert excinfo.value.status == 409
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
        install_relayer_routes(client, relayer_captured, _nonce_route(client, nonce="5"))
        install_combos_handler(client, handler)
        plan = CollateralReturnPlanResponse.parse_response(_plan_payload(wallet=str(client.wallet)))
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


def test_execute_self_heals_with_nonce_from_submit_error() -> None:
    submit_bodies: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        submit_bodies.append(json.loads(request.content.decode("utf-8")))
        if len(submit_bodies) == 1:
            return httpx.Response(
                400,
                json={"error": "batch nonce 9 does not match on-chain nonce 2"},
                request=request,
            )
        return httpx.Response(200, json=_SUBMIT_OK, request=request)

    async def run() -> None:
        client = await make_deposit_client()
        install_relayer_routes(client, [], _nonce_route(client, nonce="9"))
        install_combos_handler(client, handler)
        plan = CollateralReturnPlanResponse.parse_response(_plan_payload(wallet=str(client.wallet)))
        try:
            handle = await client.execute_collateral_return_plan(plan=plan)
            assert handle.transaction_id == "tx-collateral-return"
        finally:
            await client.close()

    asyncio.run(run())
    assert len(submit_bodies) == 2
    assert submit_bodies[1]["envelope"]["nonce"] == "2"


def test_sync_execute_self_heals_with_nonce_from_submit_error() -> None:
    submit_bodies: list[Any] = []

    def relayer_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"address": "0x0", "nonce": "9"}, request=request)

    def submit_handler(request: httpx.Request) -> httpx.Response:
        submit_bodies.append(json.loads(request.content.decode("utf-8")))
        if len(submit_bodies) == 1:
            return httpx.Response(
                400,
                json={"error": "batch nonce 9 does not match on-chain nonce 2"},
                request=request,
            )
        return httpx.Response(200, json=_SUBMIT_OK, request=request)

    client = make_sync_deposit_client()
    install_sync_relayer_handler(client, relayer_handler)
    install_sync_combos_handler(client, submit_handler)
    plan = CollateralReturnPlanResponse.parse_response(_plan_payload(wallet=str(client.wallet)))
    try:
        handle = client.execute_collateral_return_plan(plan=plan)
        assert handle.transaction_id == "tx-collateral-return"
    finally:
        client.close()

    assert len(submit_bodies) == 2
    assert submit_bodies[1]["envelope"]["nonce"] == "2"
