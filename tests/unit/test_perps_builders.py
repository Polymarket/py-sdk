"""Builder receipt, pagination, and signing contracts."""

import asyncio
import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from polymarket._internal.actions.perps import builders
from polymarket._internal.actions.perps.signing import build_perps_op_typed_data
from polymarket._internal.actions.perps.trading import (
    create_orders_op,
    to_command_body_op,
    to_raw_order,
)
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UnexpectedResponseError
from polymarket.models.perps import (
    PerpsBuilderAttribution,
    PerpsBuilderEarningsPage,
    PerpsBuilderEarningsSnapshot,
    PerpsBuilderEarningsSummary,
    PerpsFill,
    PerpsInstrumentId,
    PerpsOrderId,
    PerpsOrderRequest,
    PerpsTradeId,
)

BUILDER = "0x" + "ab" * 20


def test_builder_order_signed_payload_and_body_match() -> None:
    terms = PerpsBuilderAttribution(address=BUILDER, fee_rate=Decimal("0.0005"))
    row = to_raw_order(
        PerpsOrderRequest(
            instrument_id=1,
            side="BUY",
            quantity="10",
            price="100.50",
            time_in_force="gtc",
            builder_attribution=terms,
        )
    )
    assert row[10] == [BUILDER, "0.0005"]
    op = create_orders_op([row])
    assert to_command_body_op(op)["args"][0]["builder"] == {
        "address": BUILDER,
        "fee_rate": "0.0005",
    }
    payload = build_perps_op_typed_data(chain_id=31337, op=op, salt=1, timestamp_ms=1739491200000)
    assert (
        payload["message"]["data"]
        == "0x5061f9fbcacaff846c1f561fc8386902671fbb660c31f6dcf6433a24f16bc4f2"
    )


@pytest.mark.parametrize(
    "rate", ["NaN", "Infinity", "-0", "-0.0001", "0.00000000000000000000000000001"]
)
def test_builder_rate_constraints(rate: str) -> None:
    with pytest.raises(ValidationError):
        PerpsBuilderAttribution(address=BUILDER, fee_rate=Decimal(rate))


def test_legacy_fill_fee_totals_are_exact() -> None:
    fill: dict[str, Any] = {
        "tid": 9,
        "oid": 77,
        "iid": 1,
        "side": "long",
        "p": "0.5",
        "qty": "1",
        "taker": True,
        "fee": "-0.01",
        "fea": "USDC",
        "psz": "0",
        "pep": "0",
        "pnl": "0",
        "liq": False,
        "ts": 1751500000000,
    }
    legacy = PerpsFill.parse_response(fill)
    assert legacy.builder_fee == 0 and legacy.total_fee == Decimal("-0.01")
    parsed = PerpsFill.parse_response(
        {
            **fill,
            "fee": "9999999999999999999999999999.9999999999999999999999999999",
            "builder_fee": "0.0000000000000000000000000001",
        }
    )
    assert parsed.total_fee == Decimal("10000000000000000000000000000")


def test_legacy_fill_constructor_derives_total_fee() -> None:
    fill = PerpsFill(
        trade_id=PerpsTradeId(1),
        order_id=PerpsOrderId(2),
        instrument_id=PerpsInstrumentId(3),
        side="long",
        price=Decimal("100"),
        quantity=Decimal("1"),
        taker=True,
        fee=Decimal("0.1"),
        fee_asset="USDC",
        previous_size=Decimal(0),
        previous_entry_price=Decimal(0),
        pnl=Decimal(0),
        liquidation=False,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert fill.total_fee == Decimal("0.1")


def test_earnings_report_constructors_use_python_field_names() -> None:
    assert list(inspect.signature(PerpsBuilderEarningsSnapshot).parameters) == [
        "start",
        "end",
        "as_of_sequence",
    ]
    assert "assets" in inspect.signature(PerpsBuilderEarningsSummary).parameters


def test_earnings_empty_page_retains_snapshot_and_continuations_are_independent() -> None:
    async def run() -> None:
        calls: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            cursor = request.url.params.get("cursor")
            calls.append(cursor)
            return httpx.Response(
                200,
                json={
                    "data": [],
                    "more": cursor is None,
                    **({"cursor": "next"} if cursor is None else {}),
                    "start_timestamp": 1000,
                    "end_timestamp": 2000,
                    "as_of_sequence": 100,
                },
            )

        api = AsyncTransport(
            base_url="https://perps.test",
            client=httpx.AsyncClient(
                base_url="https://perps.test", transport=httpx.MockTransport(handler)
            ),
        )
        try:
            paginator = builders.list_earnings(api)
            first = await paginator.first_page()
            assert isinstance(first, PerpsBuilderEarningsPage)
            assert isinstance(first.snapshot, PerpsBuilderEarningsSnapshot)
            left = [page async for page in paginator]
            right = [page async for page in paginator]
            assert left == right and len(left) == 2
            assert all(p.snapshot == first.snapshot for p in left)
            assert (
                await paginator.from_cursor(first.next_cursor).first_page()
            ).snapshot == first.snapshot
            assert (await paginator.from_cursor(None).first_page()).snapshot is None
            assert [p async for p in paginator.from_cursor(None)] == []
            assert calls == [None, None, "next", None, "next", "next"]
        finally:
            await api.close()

    asyncio.run(run())


def test_earnings_repeated_cursor_is_rejected() -> None:
    async def run() -> None:
        api = AsyncTransport(
            base_url="https://perps.test",
            client=httpx.AsyncClient(
                base_url="https://perps.test",
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        200,
                        json={
                            "data": [],
                            "more": True,
                            "cursor": "same",
                            "start_timestamp": 1000,
                            "end_timestamp": 2000,
                            "as_of_sequence": 100,
                        },
                    )
                ),
            ),
        )
        try:
            with pytest.raises(UnexpectedResponseError, match="cursor"):
                await builders.list_earnings(api).from_cursor("same").first_page()
        finally:
            await api.close()

    asyncio.run(run())
