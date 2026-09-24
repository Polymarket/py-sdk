"""Static Perps typing examples checked by pyright."""

from __future__ import annotations

from collections.abc import Callable
from types import CoroutineType
from typing import TYPE_CHECKING, Any, assert_type

from polymarket.models.perps import (
    PerpsCancelOrderErrorCode,
    PerpsCancelOrderRejection,
    PerpsCancelOrderResult,
    PerpsCancelOrderSuccess,
    PerpsCancelRetryOptions,
    PerpsOrderRequest,
    PerpsPostOrderAck,
)
from polymarket.perps import PerpsOrderPlacement, PerpsSession

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
            assert_type(result.error, PerpsCancelOrderErrorCode)
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
