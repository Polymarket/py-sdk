"""Experimental Perps builder attribution, consent, and earnings.

These APIs may change in a breaking way in any release, including patch releases.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from pydantic import Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import _require_epoch_ms
from polymarket.models.perps.types import PerpsInstrumentId, PerpsOrderId, PerpsTradeId
from polymarket.models.types import OrderSide
from polymarket.pagination import AsyncPaginator, Page
from polymarket.types import EvmAddress


class PerpsBuilderAttribution(BaseModel):
    """Experimental: builder receiving fees and the fraction of executed notional."""

    address: str
    fee_rate: Decimal

    @field_validator("address", mode="before")
    @classmethod
    def _address(cls, value: object) -> object:
        from eth_utils.address import is_address

        if not isinstance(value, str) or not is_address(value):
            raise ValueError("address must be an EVM address")
        return value

    @field_validator("fee_rate")
    @classmethod
    def _rate(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or not Decimal(0) <= value <= Decimal("0.001"):
            raise ValueError("fee_rate must be between 0 and 0.001 (10 bps)")
        if int(value.as_tuple().exponent) < -28:
            raise ValueError("fee_rate must have at most 28 decimal places")
        return value


class PerpsBuilderStatus(BaseModel):
    """Experimental: builder availability and the platform fee cap."""

    address: EvmAddress
    registered: bool
    enabled: bool
    admission_enabled: bool
    max_fee_rate: Decimal


class PerpsBuilderApproval(BaseModel):
    """Experimental: saved builder fee consent, including a revoked version."""

    trader: EvmAddress
    builder: EvmAddress
    max_fee_rate: Decimal
    approval_version: int = Field(gt=0)
    timestamp: datetime
    sequence: int = Field(ge=0)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsLiquidityRole(StrEnum):
    """Experimental: whether a fill supplied or took liquidity."""

    MAKER = "maker"
    TAKER = "taker"


class PerpsBuilderEarning(BaseModel):
    """Experimental: one builder fee receipt, identified by earning_id."""

    earning_id: str = Field(min_length=1)
    trade_id: PerpsTradeId
    order_id: PerpsOrderId
    instrument_id: PerpsInstrumentId
    trader: EvmAddress
    side: OrderSide
    liquidity_role: PerpsLiquidityRole
    price: Decimal
    quantity: Decimal
    client_order_id: str | None = None
    timestamp: datetime
    sequence: int = Field(ge=0)
    notional: Decimal
    fee_asset: str
    fee: Decimal
    builder_fee: Decimal
    total_fee: Decimal
    fee_rate: Decimal

    @model_validator(mode="before")
    @classmethod
    def _side(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(cast(dict[str, Any], value))
        if "buy" in data:
            if not isinstance(data["buy"], bool):
                raise ValueError("buy must be a bool")
            data["liquidity_role"] = data["side"]
            data["side"] = "BUY" if data["buy"] else "SELL"
        return data

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsBuilderEarningsSnapshot(BaseModel):
    """Experimental: fixed reporting window and indexed sequence cutoff."""

    start: datetime = Field(validation_alias="start_timestamp")
    end: datetime = Field(validation_alias="end_timestamp")
    as_of_sequence: int = Field(ge=0)

    @field_validator("start", "end", mode="before")
    @classmethod
    def _timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsBuilderEarningsAsset(BaseModel):
    """Experimental: earnings totals for one fee asset."""

    fee_asset: str
    fill_count: int = Field(ge=0)
    notional: Decimal
    builder_fee: Decimal


class PerpsBuilderEarningsSummary(BaseModel):
    """Experimental: earnings at a fixed cutoff and the current approval count."""

    assets: tuple[PerpsBuilderEarningsAsset, ...] = Field(validation_alias="data")
    trader_count: int = Field(ge=0)
    active_approval_count: int = Field(ge=0)
    snapshot: PerpsBuilderEarningsSnapshot

    @model_validator(mode="before")
    @classmethod
    def _snapshot(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(cast(dict[str, Any], value))
        if "snapshot" not in data:
            data["snapshot"] = PerpsBuilderEarningsSnapshot.model_validate(data)
        return data


@dataclass(frozen=True, slots=True)
class PerpsBuilderEarningsPage(Page[PerpsBuilderEarning]):
    """Experimental: receipts and their reporting snapshot, even on empty pages."""

    snapshot: PerpsBuilderEarningsSnapshot | None = None


class PerpsBuilderEarningsPaginator(AsyncPaginator[PerpsBuilderEarning]):
    """Experimental: reusable earnings pagination retaining each page's snapshot."""

    def __init__(
        self,
        fetch: Callable[[str | None], Awaitable[PerpsBuilderEarningsPage]],
        initial_cursor: str | None = None,
    ) -> None:
        super().__init__(fetch=fetch, initial_cursor=initial_cursor)
        self._fetch_page = fetch

    def __aiter__(self) -> AsyncIterator[PerpsBuilderEarningsPage]:
        return self._iter_pages()

    async def first_page(self) -> PerpsBuilderEarningsPage:
        return await self._fetch_page(self._initial_cursor)

    def from_cursor(self, cursor: str | None) -> "PerpsBuilderEarningsPaginator":
        if cursor is None:
            return _EmptyBuilderEarningsPaginator()
        return PerpsBuilderEarningsPaginator(self._fetch_page, initial_cursor=cursor)

    async def _iter_pages(self) -> AsyncIterator[PerpsBuilderEarningsPage]:
        cursor = self._initial_cursor
        while True:
            page = await self._fetch_page(cursor)
            yield page
            if not page.has_more:
                return
            cursor = page.next_cursor


class _EmptyBuilderEarningsPaginator(PerpsBuilderEarningsPaginator):
    def __init__(self) -> None:
        super().__init__(_empty_page)

    async def _iter_pages(self) -> AsyncIterator[PerpsBuilderEarningsPage]:
        return
        yield


async def _empty_page(_cursor: str | None) -> PerpsBuilderEarningsPage:
    return PerpsBuilderEarningsPage(items=(), has_more=False)
