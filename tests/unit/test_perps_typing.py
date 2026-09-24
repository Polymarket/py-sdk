"""Static Perps typing examples checked by pyright."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from types import CoroutineType
from typing import TYPE_CHECKING, Any, assert_type

from polymarket import AsyncPublicClient, AsyncSecureClient
from polymarket.models.perps import (
    PerpsBuilderApproval,
    PerpsBuilderAttribution,
    PerpsBuilderEarningsPage,
    PerpsBuilderEarningsPaginator,
    PerpsBuilderEarningsSummary,
    PerpsBuilderFillsEvent,
    PerpsBuilderStatus,
    PerpsCancelOrderResult,
    PerpsFill,
    PerpsInstrumentId,
    PerpsOrderId,
    PerpsOrderRequest,
    PerpsPostOrderAck,
    PerpsTradeId,
)
from polymarket.perps import PerpsOrderPlacement, PerpsSession
from polymarket.streams import SubscriptionHandle

if TYPE_CHECKING:
    assert_type(
        PerpsOrderRequest(
            instrument_id=1,
            price="100",
            quantity="1",
            side="BUY",
            time_in_force="gtc",
        ),
        PerpsOrderRequest,
    )
    assert_type(
        PerpsOrderRequest(
            instrument_id=1,
            quantity="1",
            reduce_only=True,
            side="BUY",
            time_in_force="ioc",
        ),
        PerpsOrderRequest,
    )

    async def _check_session_typing(session: PerpsSession) -> None:
        assert_type(
            await session.place_order(
                instrument_id=1,
                price="100",
                quantity="1",
                reduce_only=True,
                side="BUY",
                time_in_force="gtc",
            ),
            PerpsOrderPlacement,
        )
        assert_type(
            await session.cancel_order(order_id=1),
            PerpsCancelOrderResult,
        )
        assert_type(
            await session.cancel_order(client_order_id="aabbccddeeff00112233445566778899"),
            PerpsCancelOrderResult,
        )
        assert_type(
            await session.cancel_orders(order_ids=[1, 2]),
            tuple[PerpsCancelOrderResult, ...],
        )
        assert_type(
            await session.post_orders(
                [
                    PerpsOrderRequest(
                        instrument_id=1,
                        price="100",
                        quantity="1",
                        side="BUY",
                        time_in_force="gtc",
                    )
                ]
            ),
            tuple[PerpsPostOrderAck, ...],
        )

    _session_typing_check: Callable[[PerpsSession], CoroutineType[Any, Any, None]] = (
        _check_session_typing
    )

if TYPE_CHECKING:

    async def _check_builder_typing(
        client: AsyncSecureClient,
        public: AsyncPublicClient,
        session: PerpsSession,
        terms: PerpsBuilderAttribution,
    ) -> None:
        assert_type(await client.open_perps_session(builder_attribution=terms), PerpsSession)
        assert_type(
            await public.fetch_perps_builder_status(address=terms.address), PerpsBuilderStatus
        )
        assert_type(
            await client.fetch_perps_builder_status(address=terms.address), PerpsBuilderStatus
        )
        assert_type(await session.approve_builder_fee(), PerpsBuilderApproval)
        assert_type(await session.fetch_builder_approvals(), tuple[PerpsBuilderApproval, ...])
        assert_type(session.list_builder_earnings(), PerpsBuilderEarningsPaginator)
        assert_type(await session.list_builder_earnings().first_page(), PerpsBuilderEarningsPage)
        async for page in session.list_builder_earnings():
            assert_type(page, PerpsBuilderEarningsPage)
        assert_type(await session.fetch_builder_earnings_summary(), PerpsBuilderEarningsSummary)
        assert_type(
            await session.subscribe_builder_fills(), SubscriptionHandle[PerpsBuilderFillsEvent]
        )

    _builder_typing_check = _check_builder_typing


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
    assert_type(fill.total_fee, Decimal)
    assert fill.total_fee == Decimal("0.1")
