"""Perps account notification models."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    _coerce_decimalish,  # pyright: ignore[reportPrivateUsage]
    _parse_epoch_ms,  # pyright: ignore[reportPrivateUsage]
    _require_epoch_ms,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.perps.types import (
    PerpsInstrumentId,
    PerpsMarginType,
    PerpsNotificationId,
    PerpsNotificationOrderType,
    PerpsSide,
)
from polymarket.pagination import AsyncPaginator, Page


class PerpsPositionChangeNotification(BaseModel):
    """A fill opened, increased, or reduced a position.

    ``order_type`` reports the kind of order whose execution produced the
    fill: a TP/SL-triggered order reports the trigger that fired it, an
    aggressor submitted without a limit price is ``market``, and everything
    else, including a maker's resting order, is ``limit``.
    """

    id: PerpsNotificationId
    type: Literal["position_opened", "position_increased", "position_reduced"]
    instrument_id: PerpsInstrumentId
    side: PerpsSide
    size: Decimal
    avg_price: Decimal
    leverage: int
    order_type: PerpsNotificationOrderType | None = None

    @field_validator("size", "avg_price", mode="before")
    @classmethod
    def _validate_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsPositionClosedNotification(BaseModel):
    """A fill closed a position."""

    id: PerpsNotificationId
    type: Literal["position_closed"]
    instrument_id: PerpsInstrumentId
    side: PerpsSide
    size: Decimal
    avg_price: Decimal
    pnl: Decimal
    order_type: PerpsNotificationOrderType | None = None

    @field_validator("size", "avg_price", "pnl", mode="before")
    @classmethod
    def _validate_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsLimitOrderCanceledNotification(BaseModel):
    """A resting limit order was canceled."""

    id: PerpsNotificationId
    type: Literal["limit_order_canceled"]
    instrument_id: PerpsInstrumentId
    side: PerpsSide
    size: Decimal
    price: Decimal

    @field_validator("size", "price", mode="before")
    @classmethod
    def _validate_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsIsolatedLiquidationWarningNotification(BaseModel):
    """An isolated-margin position is approaching its liquidation price."""

    id: PerpsNotificationId
    type: Literal["liquidation_warning"]
    margin_type: Literal["isolated"]
    instrument_id: PerpsInstrumentId
    mark_price: Decimal
    liquidation_price: Decimal = Field(validation_alias="liq_price")

    @field_validator("mark_price", "liquidation_price", mode="before")
    @classmethod
    def _validate_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsCrossLiquidationWarningNotification(BaseModel):
    """The cross-margin account is approaching liquidation."""

    id: PerpsNotificationId
    type: Literal["liquidation_warning"]
    margin_type: Literal["cross"]
    mark_price: Decimal
    affected_instruments: tuple[PerpsInstrumentId, ...]

    @field_validator("mark_price", mode="before")
    @classmethod
    def _validate_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


PerpsLiquidationWarningNotification = Annotated[
    PerpsIsolatedLiquidationWarningNotification | PerpsCrossLiquidationWarningNotification,
    Field(discriminator="margin_type"),
]


class PerpsPositionLiquidatedNotification(BaseModel):
    """A position was partially or fully liquidated."""

    id: PerpsNotificationId
    type: Literal["position_liquidated"]
    instrument_id: PerpsInstrumentId
    side: PerpsSide
    size_closed: Decimal
    pnl: Decimal | None
    margin_type: PerpsMarginType
    via_backstop: bool

    @field_validator("size_closed", "pnl", mode="before")
    @classmethod
    def _validate_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


PerpsNotification = Annotated[
    PerpsPositionChangeNotification
    | PerpsPositionClosedNotification
    | PerpsLimitOrderCanceledNotification
    | PerpsLiquidationWarningNotification
    | PerpsPositionLiquidatedNotification,
    Field(discriminator="type"),
]


class PerpsNotificationEntry(BaseModel):
    """One notification with its account-scoped read state."""

    notification: PerpsNotification
    read_at: datetime | None = None
    timestamp: datetime = Field(validation_alias="ts")

    @field_validator("read_at", mode="before")
    @classmethod
    def _validate_read_at(cls, value: object) -> object:
        return _parse_epoch_ms(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


@dataclass(frozen=True, slots=True)
class PerpsNotificationsPage(Page[PerpsNotificationEntry]):
    """One page of notifications, newest first, with read-state metadata.

    ``unread`` and ``durable_source_seq`` reflect the account state observed
    when the page was fetched. The synthetic empty page produced by
    continuing past the final page reports both as ``0``.
    """

    unread: int = 0
    durable_source_seq: int = 0


class PerpsNotificationsPaginator(AsyncPaginator[PerpsNotificationEntry]):
    """Async paginator whose pages carry notification read-state metadata."""

    def __init__(
        self,
        fetch: Callable[[str | None], Awaitable[PerpsNotificationsPage]],
        initial_cursor: str | None = None,
    ) -> None:
        super().__init__(fetch=fetch, initial_cursor=initial_cursor)
        self._fetch_page = fetch

    async def first_page(self) -> PerpsNotificationsPage:
        return await self._fetch_page(self._initial_cursor)

    def from_cursor(self, cursor: str | None) -> PerpsNotificationsPaginator:
        if cursor is None:
            return _EmptyNotificationsPaginator()
        return PerpsNotificationsPaginator(self._fetch_page, initial_cursor=cursor)


class _EmptyNotificationsPaginator(PerpsNotificationsPaginator):
    def __init__(self) -> None:
        super().__init__(fetch=_empty_notifications_page, initial_cursor=None)

    def from_cursor(self, cursor: str | None) -> PerpsNotificationsPaginator:
        if cursor is None:
            return self
        return PerpsNotificationsPaginator(self._fetch_page, initial_cursor=cursor)

    async def _iter_pages(self) -> AsyncIterator[PerpsNotificationsPage]:
        return
        yield  # pragma: no cover - forces this method to be an async generator


async def _empty_notifications_page(_cursor: str | None) -> PerpsNotificationsPage:
    return PerpsNotificationsPage(items=(), has_more=False)


__all__ = [
    "PerpsCrossLiquidationWarningNotification",
    "PerpsIsolatedLiquidationWarningNotification",
    "PerpsLimitOrderCanceledNotification",
    "PerpsLiquidationWarningNotification",
    "PerpsNotification",
    "PerpsNotificationEntry",
    "PerpsNotificationsPage",
    "PerpsNotificationsPaginator",
    "PerpsPositionChangeNotification",
    "PerpsPositionClosedNotification",
    "PerpsPositionLiquidatedNotification",
]
