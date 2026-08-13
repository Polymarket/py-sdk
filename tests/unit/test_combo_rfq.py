# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest
from _relayer_helpers import BUILDER_AUTH, FAKE_CREDS, PK_DEPLOY_WALLET, make_eoa_client

from polymarket import (
    AsyncSecureClient,
    ComboAcceptFailureReason,
    ComboQuote,
    ComboQuoteUnavailableReason,
    RfqDirection,
    RfqStatus,
    SecureClient,
)
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import TimeoutError as SdkTimeoutError
from polymarket.errors import UnexpectedResponseError
from polymarket.models.types import PositionId
from polymarket.types import HexString

BUILDER_CODE = "0x" + "ab" * 32
LEGS = ["123", "456"]
CONDITION_ID = "0x03" + "0" * 60

QUOTE_READY: dict[str, Any] = {
    "rfq_id": "rfq-1",
    "status": "AWAITING_REQUESTER_ACCEPTANCE",
    "expires_at": 1_773_890_765_500,
    "builder_code": BUILDER_CODE,
    "request": {
        "rfq_id": "rfq-1",
        "leg_position_ids": LEGS,
        "condition_id": CONDITION_ID,
        "yes_position_id": "789",
        "no_position_id": "790",
        "direction": "BUY",
        "side": "YES",
        "requested_size": {"unit": "notional", "value_e6": "100000000"},
        "created_at": 1_773_890_758_000,
    },
    "quote": {
        "quote_id": "quote-1",
        "blended_price_e6": "450000",
        "maker_amount_e6": "966191",
        "taker_amount_e6": "1932381",
        "total_required_e6": "1000000",
        "net_receive_e6": "1932381",
    },
}

QUOTE = ComboQuote(
    rfq_id="rfq-1",
    quote_id="quote-1",
    builder_code=HexString(BUILDER_CODE),
    direction=RfqDirection.BUY,
    position_id=PositionId("789"),
    blended_price=Decimal("0.45"),
    maker_amount=Decimal("0.966191"),
    taker_amount=Decimal("1.932381"),
    total_required=Decimal("1"),
    expires_at=1_773_890_765_500,
)


def install_builder_gateway_handler(
    client: AsyncSecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    transport = AsyncTransport(
        base_url="https://builder-gateway.test",
        client=httpx.AsyncClient(
            base_url="https://builder-gateway.test", transport=httpx.MockTransport(handler)
        ),
        header_resolver=client._ctx.builder_gateway._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, builder_gateway=transport)


def make_sync_eoa_client() -> SecureClient:
    from eth_account import Account

    signer = Account.from_key(PK_DEPLOY_WALLET)
    return SecureClient._create(
        private_key=PK_DEPLOY_WALLET,
        wallet=signer.address,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH,
        validate_credentials=False,
    )


def install_sync_builder_gateway_handler(
    client: SecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    transport = SyncTransport(
        base_url="https://builder-gateway.test",
        client=httpx.Client(
            base_url="https://builder-gateway.test", transport=httpx.MockTransport(handler)
        ),
        header_resolver=client._ctx.builder_gateway._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, builder_gateway=transport)


def json_handler(*responses: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            raise AssertionError("Unexpected builder gateway request")
        return queue.pop(0)

    return handler


def accept_retry_handler(
    failure: str, captured: list[httpx.Request]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if len(captured) == 1:
            if failure == "transport":
                raise httpx.ReadTimeout("connection dropped", request=request)
            return httpx.Response(
                200,
                json={"rfq_id": "rfq-1", "status": "UNKNOWN"},
                request=request,
            )
        return httpx.Response(
            200,
            json={"rfq_id": "rfq-1", "status": "EXECUTING"},
            request=request,
        )

    return handler


def test_request_combo_quote_handles_sell_net_proceeds() -> None:
    response = copy.deepcopy(QUOTE_READY)
    response["request"]["direction"] = "SELL"
    response["request"]["requested_size"] = {"unit": "shares", "value_e6": "2500000"}
    response["quote"].update(
        {
            "maker_amount_e6": "2500000",
            "taker_amount_e6": "1125000",
            "total_required_e6": "2500000",
            "net_receive_e6": "1090000",
        }
    )
    missing = copy.deepcopy(response)
    del missing["quote"]["net_receive_e6"]
    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(
        client,
        json_handler(
            httpx.Response(200, json=response),
            httpx.Response(200, json=missing),
        ),
    )

    result = client.request_combo_quote(leg_position_ids=LEGS, direction="SELL", size="2.5")
    assert result.quote is not None
    assert result.quote.direction is RfqDirection.SELL
    assert result.quote.net_receive == Decimal("1.09")

    with pytest.raises(UnexpectedResponseError, match="omitted net sell proceeds"):
        client.request_combo_quote(leg_position_ids=LEGS, direction="SELL", size="2.5")


def test_request_combo_quote_returns_no_quote_outcome() -> None:
    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(
        client,
        json_handler(
            httpx.Response(
                200,
                json={
                    "rfq_id": "rfq-2",
                    "status": "FAILED",
                    "error": {"code": "NO_QUOTES", "message": "no quotes"},
                },
            )
        ),
    )

    result = client.request_combo_quote(leg_position_ids=LEGS, direction="BUY", amount=100)

    assert result.rfq_id == "rfq-2"
    assert result.quote is None
    assert result.reason is ComboQuoteUnavailableReason.NO_QUOTES


def test_request_combo_quote_canonicalizes_numeric_leg_ids() -> None:
    captured: list[httpx.Request] = []
    response = copy.deepcopy(QUOTE_READY)
    response["request"]["leg_position_ids"] = ["2", "10"]

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=response, request=request)

    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(client, handler)

    client.request_combo_quote(leg_position_ids=["0010", "02"], direction="BUY", amount=100)

    body = json.loads(captured[0].content)
    assert body["leg_position_ids"] == ["2", "10"]


@pytest.mark.parametrize(
    ("status_code", "payload", "reason"),
    [
        (
            200,
            {
                "rfq_id": "rfq-1",
                "status": "FAILED",
                "error": {"code": "MAKER_DECLINED", "message": "maker declined"},
            },
            ComboAcceptFailureReason.MAKER_DECLINED,
        ),
        (
            409,
            {"error": "expired rfq", "code": "EXPIRED_RFQ"},
            ComboAcceptFailureReason.ACCEPTANCE_WINDOW_EXPIRED,
        ),
    ],
)
def test_accept_combo_quote_maps_failure_outcomes(
    status_code: int,
    payload: dict[str, object],
    reason: ComboAcceptFailureReason,
) -> None:
    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(
        client, json_handler(httpx.Response(status_code, json=payload))
    )

    acceptance = client.accept_combo_quote(QUOTE)

    assert acceptance.status == "failed"
    assert acceptance.reason is reason


@pytest.mark.parametrize("failure", ["transport", "unexpected_response"])
def test_accept_combo_quote_retries_ambiguous_async_failure(failure: str) -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []
        client = await make_eoa_client()
        install_builder_gateway_handler(client, accept_retry_handler(failure, captured))

        acceptance = await client.accept_combo_quote(QUOTE)

        assert len(captured) == 2
        assert captured[0].content == captured[1].content
        assert acceptance.status == "executing"

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["transport", "unexpected_response"])
def test_accept_combo_quote_retries_ambiguous_sync_failure(failure: str) -> None:
    captured: list[httpx.Request] = []
    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(client, accept_retry_handler(failure, captured))

    acceptance = client.accept_combo_quote(QUOTE)

    assert len(captured) == 2
    assert captured[0].content == captured[1].content
    assert acceptance.status == "executing"


def test_wait_for_combo_fill_returns_terminal_failure() -> None:
    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(
        client,
        json_handler(
            httpx.Response(
                200,
                json={
                    "rfq_id": "rfq-1",
                    "status": "FAILED",
                    "error": {
                        "code": "TRADE_SUBMISSION_FAILED",
                        "message": "trade submission failed",
                    },
                },
            )
        ),
    )

    fill = client.wait_for_combo_fill(rfq_id="rfq-1")

    assert fill.status is RfqStatus.FAILED
    assert fill.error is not None
    assert fill.error.code == "TRADE_SUBMISSION_FAILED"


def test_wait_for_combo_fill_times_out_while_non_terminal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"rfq_id": "rfq-1", "status": "EXECUTING"},
            request=request,
        )

    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(client, handler)

    with pytest.raises(SdkTimeoutError):
        client.wait_for_combo_fill(rfq_id="rfq-1", timeout=0.01, polling_interval=0.001)


def test_fetch_rfq_status_rejects_mismatched_response_id() -> None:
    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(
        client,
        json_handler(httpx.Response(200, json={"rfq_id": "rfq-2", "status": "EXECUTING"})),
    )

    with pytest.raises(UnexpectedResponseError, match="did not match requested ID"):
        client.fetch_rfq_status(rfq_id="rfq-1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rfq_id", "rfq-2"),
        ("direction", "SELL"),
        ("side", "NO"),
        ("leg_position_ids", list(reversed(LEGS))),
        ("requested_size", {"unit": "notional", "value_e6": "99999999"}),
        ("requested_size", {"unit": "shares", "value_e6": "100000000"}),
    ],
)
def test_request_combo_quote_rejects_mismatched_request_echo(field: str, value: object) -> None:
    response = copy.deepcopy(QUOTE_READY)
    response["request"][field] = value
    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(client, json_handler(httpx.Response(200, json=response)))

    with pytest.raises(UnexpectedResponseError, match=field):
        client.request_combo_quote(leg_position_ids=LEGS, direction="BUY", amount=100)
