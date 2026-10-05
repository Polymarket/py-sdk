"""Static Perps typing examples checked by pyright."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
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
    PerpsBuilderFillEvent,
    PerpsBuilderStatus,
    PerpsCancelOrderResult,
    PerpsInternalTransfer,
    PerpsInternalTransferId,
    PerpsOrderRequest,
    PerpsPostOrderAck,
)
from polymarket.pagination import AsyncPaginator
from polymarket.perps import PerpsOrderPlacement, PerpsSession

if TYPE_CHECKING:

    async def _check_transfer_typing(client: AsyncSecureClient, session: PerpsSession) -> None:
        assert_type(
            await client.transfer_perps_collateral(
                recipient="0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
                amount=Decimal("250.50"),
                label="rebalance-001",
            ),
            PerpsInternalTransferId,
        )
        assert_type(
            await client.transfer_perps_collateral(
                recipient="0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
                amount="250.50",
            ),
            PerpsInternalTransferId,
        )
        pages = session.list_internal_transfers(start=0)
        assert_type(pages, AsyncPaginator[PerpsInternalTransfer])
        async for page in pages:
            for transfer in page.items:
                assert_type(transfer.amount, Decimal)
                assert_type(transfer.created_at, datetime)
                assert_type(transfer.transfer_id, PerpsInternalTransferId)

    _transfer_typing_check = _check_transfer_typing

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
        assert_type(
            await client.open_perps_session(builder_attribution=terms.address), PerpsSession
        )
        assert_type(await client.open_perps_session(include_builder_fills=True), PerpsSession)
        assert_type(
            await public.fetch_perps_builder_status(address=terms.address), PerpsBuilderStatus
        )
        assert_type(
            await client.fetch_perps_builder_status(address=terms.address), PerpsBuilderStatus
        )
        assert_type(
            await session.approve_builder_fee(
                builder_address=terms.address, max_fee_rate=terms.fee_rate
            ),
            PerpsBuilderApproval,
        )
        assert_type(await session.revoke_builder_fee(), PerpsBuilderApproval)
        assert_type(await session.fetch_builder_approvals(), tuple[PerpsBuilderApproval, ...])
        assert_type(session.list_builder_earnings(), PerpsBuilderEarningsPaginator)
        assert_type(await session.list_builder_earnings().first_page(), PerpsBuilderEarningsPage)
        async for page in session.list_builder_earnings():
            assert_type(page, PerpsBuilderEarningsPage)
        assert_type(await session.fetch_builder_earnings_summary(), PerpsBuilderEarningsSummary)
        async for event in session:
            if event.type == "builder_fill":
                assert_type(event, PerpsBuilderFillEvent)

    _builder_typing_check = _check_builder_typing
