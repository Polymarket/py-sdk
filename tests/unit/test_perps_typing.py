"""Static Perps typing examples checked by pyright."""

from __future__ import annotations

from collections.abc import Callable
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
    PerpsCancelOrderErrorCode,
    PerpsCancelOrderRejection,
    PerpsCancelOrderResult,
    PerpsCancelOrderSuccess,
    PerpsCancelRetryOptions,
    PerpsOrderRequest,
    PerpsPositionDeleveragedNotification,
    PerpsPostOrderAck,
)
from polymarket.perps import PerpsOrderPlacement, PerpsSession

if TYPE_CHECKING:

    async def _check_registration_typing(
        public: AsyncPublicClient, secure: AsyncSecureClient
    ) -> None:
        address = "0x1111111111111111111111111111111111111111"
        assert_type(await public.fetch_perps_registration(address=address), bool)
        assert_type(await secure.fetch_perps_registration(address=address), bool)

    _registration_typing_check = _check_registration_typing

    assert_type(
        PerpsOrderRequest(
            instrument_id=1,
            side="BUY",
            quantity="1",
            price="100",
            time_in_force="gtd",
            gtd_expiry=1_893_456_000_123,
            post_only=True,
        ),
        PerpsOrderRequest,
    )
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
        page = await session.list_notifications().first_page()
        for entry in page.items:
            if entry.notification.type == "position_deleveraged":
                assert_type(entry.notification, PerpsPositionDeleveragedNotification)
                assert_type(entry.notification.pnl, Decimal)
        async for event in session:
            if event.type == "notification" and event.payload.type == "position_deleveraged":
                assert_type(event.payload, PerpsPositionDeleveragedNotification)
                assert_type(event.payload.price, Decimal)

        assert_type(
            await session.place_order(
                instrument_id=1,
                side="BUY",
                quantity="1",
                price="100",
                time_in_force="gtd",
                gtd_expiry=1_893_456_000_123,
                post_only=True,
            ),
            PerpsOrderPlacement,
        )
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
            await session.cancel_order(
                order_id=1,
                retry=PerpsCancelRetryOptions(max_attempts=2, max_elapsed_s=1.0),
            ),
            PerpsCancelOrderResult,
        )
        assert_type(
            await session.cancel_order(client_order_id="aabbccddeeff00112233445566778899"),
            PerpsCancelOrderResult,
        )
        assert_type(
            await session.cancel_orders(order_ids=[1, 2], retry=False),
            tuple[PerpsCancelOrderResult, ...],
        )
        result = await session.cancel_order(order_id=1)
        if result.status == "err":
            assert_type(result, PerpsCancelOrderRejection)
            assert_type(result.error, PerpsCancelOrderErrorCode | str)
        else:
            assert_type(result, PerpsCancelOrderSuccess)
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
