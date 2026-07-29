# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from _relayer_helpers import (
    BUILDER_AUTH,
    FAKE_CREDS,
    PK_DEPLOY_WALLET,
    make_eoa_client,
)

from polymarket import (
    AsyncSecureClient,
    ComboAcceptFailureReason,
    ComboQuote,
    ComboQuoteResult,
    ComboQuoteUnavailableReason,
    RfqDirection,
    RfqRejectionCode,
    RfqRequestRejectedError,
    RfqStatus,
    SecureClient,
    UserInputError,
)
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import TimeoutError as SdkTimeoutError
from polymarket.models.types import PositionId, to_combo_condition_id
from polymarket.types import HexString

BUILDER_CODE = "0x" + "ab" * 32
TX_HASH = "0x" + "cd" * 32
TAKER_ORDER_HASH = "0x" + "ef" * 32
LEGS = ["123", "456"]
CONDITION_ID = "0x03" + "0" * 60

QUOTE_READY = {
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
        "created_at": 1_773_890_758_000,
    },
    "quote": {
        "quote_id": "quote-1",
        "blended_price_e6": "450000",
        "maker_amount_e6": "966191",
        "taker_amount_e6": "1932381",
        "total_required_e6": "1000000",
    },
}

QUOTE_RESULT = ComboQuoteResult(
    rfq_id="rfq-1",
    direction=RfqDirection.BUY,
    quote=ComboQuote(
        quote_id="quote-1",
        blended_price=Decimal("0.45"),
        maker_amount=Decimal("0.966191"),
        taker_amount=Decimal("1.932381"),
        total_required=Decimal("1"),
        expires_at=1_773_890_765_500,
    ),
    position_id=PositionId("789"),
    condition_id=to_combo_condition_id(CONDITION_ID),
    builder_code=HexString(BUILDER_CODE),
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


def make_sync_eoa_client(*, with_api_key: bool = True) -> SecureClient:
    from eth_account import Account

    signer = Account.from_key(PK_DEPLOY_WALLET)
    return SecureClient._create(
        private_key=PK_DEPLOY_WALLET,
        wallet=signer.address,
        credentials=FAKE_CREDS,
        api_key=BUILDER_AUTH if with_api_key else None,
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


def test_request_combo_quote_builds_buy_request_and_parses_quote() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json=QUOTE_READY, request=request)

        client = await make_eoa_client()
        install_builder_gateway_handler(client, handler)

        result = await client.request_combo_quote(
            leg_position_ids=LEGS, direction="BUY", amount=100
        )

        request = captured[0]
        assert request.url.path == "/v1/builder/rfq/requests"
        body = json.loads(request.content.decode("utf-8"))
        assert body["direction"] == "BUY"
        assert body["side"] == "YES"
        assert body["leg_position_ids"] == LEGS
        assert body["requested_size"] == {"unit": "notional", "value_e6": "100000000"}
        assert body["signature_type"] == 0
        assert body["signer_address"] == body["maker_address"]
        assert request.headers["POLY_API_KEY"] == FAKE_CREDS.key
        assert request.headers["POLY_BUILDER_API_KEY"] == BUILDER_AUTH.key

        assert result.rfq_id == "rfq-1"
        assert result.direction is RfqDirection.BUY
        assert result.position_id == "789"
        assert result.condition_id == CONDITION_ID
        assert result.builder_code == BUILDER_CODE
        assert result.quote is not None
        assert result.quote.blended_price == Decimal("0.45")
        assert result.quote.maker_amount == Decimal("0.966191")
        assert result.quote.taker_amount == Decimal("1.932381")
        assert result.quote.total_required == Decimal("1")
        assert result.quote.expires_at == 1_773_890_765_500

    asyncio.run(run())


def test_request_combo_quote_sell_is_sized_in_shares() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json=QUOTE_READY, request=request)

        client = await make_eoa_client()
        install_builder_gateway_handler(client, handler)

        await client.request_combo_quote(leg_position_ids=LEGS, direction="SELL", size="2.5")

        body = json.loads(captured[0].content.decode("utf-8"))
        assert body["direction"] == "SELL"
        assert body["requested_size"] == {"unit": "shares", "value_e6": "2500000"}

    asyncio.run(run())


def test_request_combo_quote_returns_no_quote_outcome() -> None:
    async def run() -> None:
        client = await make_eoa_client()
        install_builder_gateway_handler(
            client,
            json_handler(
                httpx.Response(
                    200,
                    json={
                        "rfq_id": "rfq-2",
                        "status": "FAILED",
                        "builder_code": BUILDER_CODE,
                        "error": {"code": "NO_QUOTES", "message": "no quotes"},
                    },
                )
            ),
        )

        result = await client.request_combo_quote(
            leg_position_ids=LEGS, direction="BUY", amount=100
        )

        assert result.quote is None
        assert result.reason is ComboQuoteUnavailableReason.NO_QUOTES
        assert result.rfq_id == "rfq-2"

    asyncio.run(run())


def test_request_combo_quote_validates_input_before_sending() -> None:
    client = make_sync_eoa_client()

    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError("No request expected")

    install_sync_builder_gateway_handler(client, unexpected)

    invalid_calls = [
        {"leg_position_ids": ["123"], "direction": "BUY", "amount": 100},
        {"leg_position_ids": ["123", "123"], "direction": "BUY", "amount": 100},
        {"leg_position_ids": ["123", "0x2"], "direction": "BUY", "amount": 100},
        {"leg_position_ids": LEGS, "direction": "BUY", "amount": "0.0000001"},
        {"leg_position_ids": LEGS, "direction": "BUY", "amount": 0},
        {"leg_position_ids": LEGS, "direction": "BUY", "size": 1},
        {"leg_position_ids": LEGS, "direction": "SELL", "amount": 1},
        {"leg_position_ids": LEGS, "direction": "SELL", "size": -1},
        {"leg_position_ids": LEGS, "direction": "HOLD", "amount": 1},
        {"leg_position_ids": LEGS, "direction": "BUY", "amount": 1, "side": "NO"},
    ]

    for kwargs in invalid_calls:
        with pytest.raises(UserInputError):
            client.request_combo_quote(**kwargs)  # type: ignore[arg-type]


def test_request_combo_quote_requires_builder_api_key() -> None:
    async def run() -> None:
        client = await make_eoa_client(with_api_key=False)

        with pytest.raises(UserInputError, match="Builder API Key"):
            await client.request_combo_quote(leg_position_ids=LEGS, direction="BUY", amount=100)

    asyncio.run(run())


def test_request_combo_quote_classifies_rejections() -> None:
    async def run() -> None:
        client = await make_eoa_client()
        install_builder_gateway_handler(
            client,
            json_handler(
                httpx.Response(
                    400, json={"error": "contradictory legs", "code": "CONTRADICTORY_LEGS"}
                ),
                httpx.Response(400, json={"error": "something new", "code": "SOMETHING_NEW"}),
            ),
        )

        with pytest.raises(RfqRequestRejectedError) as known:
            await client.request_combo_quote(leg_position_ids=LEGS, direction="BUY", amount=100)
        assert known.value.code is RfqRejectionCode.CONTRADICTORY_LEGS
        assert known.value.status == 400

        with pytest.raises(RfqRequestRejectedError) as unknown:
            await client.request_combo_quote(leg_position_ids=LEGS, direction="BUY", amount=100)
        assert unknown.value.code == "SOMETHING_NEW"

    asyncio.run(run())


def test_accept_combo_quote_signs_and_submits_the_acceptance_order() -> None:
    async def run() -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={
                    "rfq_id": "rfq-1",
                    "status": "EXECUTING",
                    "taker_order_hash": TAKER_ORDER_HASH,
                },
                request=request,
            )

        client = await make_eoa_client()
        install_builder_gateway_handler(client, handler)

        acceptance = await client.accept_combo_quote(QUOTE_RESULT)

        request = captured[0]
        assert request.url.path == "/v1/builder/rfq/requests/rfq-1/accept"
        assert request.headers["POLY_BUILDER_API_KEY"] == BUILDER_AUTH.key
        body = json.loads(request.content.decode("utf-8"))
        assert body["quote_id"] == "quote-1"
        order = body["signed_order"]
        assert order["builder"] == BUILDER_CODE
        assert order["tokenId"] == "789"
        assert order["side"] == 0
        assert order["signatureType"] == 0
        assert order["makerAmount"] == "966191"
        assert order["takerAmount"] == "1932381"
        assert order["maker"] == order["signer"]
        assert order["metadata"] == "0x" + "0" * 64
        assert order["signature"].startswith("0x")

        assert acceptance.status == "executing"
        assert acceptance.taker_order_hash == TAKER_ORDER_HASH

    asyncio.run(run())


def test_accept_combo_quote_polls_until_the_outcome_lands() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "rfq_id": "rfq-1",
                        "status": "AWAITING_MAKER_CONFIRMATION",
                        "taker_order_hash": TAKER_ORDER_HASH,
                    },
                    request=request,
                )
            assert "POLY_BUILDER_API_KEY" not in request.headers
            assert request.headers["POLY_API_KEY"] == FAKE_CREDS.key
            return httpx.Response(
                200, json={"rfq_id": "rfq-1", "status": "EXECUTING"}, request=request
            )

        client = await make_eoa_client()
        install_builder_gateway_handler(client, handler)

        acceptance = await client.accept_combo_quote(QUOTE_RESULT)

        assert acceptance.status == "executing"
        assert acceptance.taker_order_hash == TAKER_ORDER_HASH

    asyncio.run(run())


def test_accept_combo_quote_reports_maker_decline_as_failed() -> None:
    async def run() -> None:
        client = await make_eoa_client()
        install_builder_gateway_handler(
            client,
            json_handler(
                httpx.Response(
                    200,
                    json={
                        "rfq_id": "rfq-1",
                        "status": "FAILED",
                        "taker_order_hash": TAKER_ORDER_HASH,
                        "error": {"code": "MAKER_DECLINED", "message": "maker declined"},
                    },
                )
            ),
        )

        acceptance = await client.accept_combo_quote(QUOTE_RESULT)

        assert acceptance.status == "failed"
        assert acceptance.reason is ComboAcceptFailureReason.MAKER_DECLINED
        assert acceptance.error is not None
        assert acceptance.error.message == "maker declined"

    asyncio.run(run())


def test_accept_combo_quote_reports_expired_window_as_failed() -> None:
    async def run() -> None:
        client = await make_eoa_client()
        install_builder_gateway_handler(
            client,
            json_handler(httpx.Response(409, json={"error": "expired rfq", "code": "EXPIRED_RFQ"})),
        )

        acceptance = await client.accept_combo_quote(QUOTE_RESULT)

        assert acceptance.status == "failed"
        assert acceptance.reason is ComboAcceptFailureReason.ACCEPTANCE_WINDOW_EXPIRED

    asyncio.run(run())


def test_accept_combo_quote_rejects_result_without_quote() -> None:
    async def run() -> None:
        client = await make_eoa_client()

        with pytest.raises(UserInputError, match="without a quote"):
            await client.accept_combo_quote(
                ComboQuoteResult(
                    rfq_id="rfq-2",
                    direction=RfqDirection.BUY,
                    quote=None,
                    reason=ComboQuoteUnavailableReason.NO_QUOTES,
                )
            )

    asyncio.run(run())


def test_wait_for_combo_fill_normalizes_confirmed_to_filled() -> None:
    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(
        client,
        json_handler(
            httpx.Response(200, json={"rfq_id": "rfq-1", "status": "EXECUTING"}),
            httpx.Response(200, json={"rfq_id": "rfq-1", "status": "MINED", "tx_hash": TX_HASH}),
            httpx.Response(
                200, json={"rfq_id": "rfq-1", "status": "CONFIRMED", "tx_hash": TX_HASH}
            ),
        ),
    )

    fill = client.wait_for_combo_fill(rfq_id="rfq-1", polling_interval=0.001)

    assert fill.status is RfqStatus.FILLED
    assert fill.tx_hash == TX_HASH


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
    assert fill.tx_hash is None
    assert fill.error is not None
    assert fill.error.code == "TRADE_SUBMISSION_FAILED"


def test_wait_for_combo_fill_times_out_while_non_terminal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rfq_id": "rfq-1", "status": "EXECUTING"}, request=request)

    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(client, handler)

    with pytest.raises(SdkTimeoutError):
        client.wait_for_combo_fill(rfq_id="rfq-1", timeout=0.01, polling_interval=0.001)


def test_fetch_rfq_status_maps_rejections() -> None:
    client = make_sync_eoa_client()
    install_sync_builder_gateway_handler(
        client,
        json_handler(
            httpx.Response(409, json={"error": "rfq not accepted", "code": "RFQ_NOT_ACCEPTED"})
        ),
    )

    with pytest.raises(RfqRequestRejectedError) as rejected:
        client.fetch_rfq_status(rfq_id="rfq-1")

    assert rejected.value.status == 409
    assert rejected.value.code == "RFQ_NOT_ACCEPTED"
