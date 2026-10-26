"""Experimental position snapshots; may change in patch releases."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps.types import PerpsInstrumentId, PerpsSide


@dataclass(frozen=True, kw_only=True)
class PerpsPositionSnapshotFill:
    """Select a fill by instrument, decimal u64 trade ID and UTC time or epoch milliseconds."""

    instrument_id: int
    trade_id: str
    timestamp: datetime | int


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 18446744073709:
        raise ValueError("expected non-negative epoch milliseconds within u64 nanoseconds")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)


class PerpsPositionSnapshotCandle(BaseModel):
    """Chart coordinate and approximate OHLC prices."""

    position: float
    open: float
    high: float
    low: float
    close: float


class PerpsPositionSnapshotMarker(BaseModel):
    """A size increase or decrease at a chart coordinate."""

    position: float
    kind: Literal["increase", "decrease"]


class PerpsPositionSnapshotChart(BaseModel):
    """Bounded candles and position-change markers."""

    candles: tuple[PerpsPositionSnapshotCandle, ...] = Field(max_length=22)
    markers: tuple[PerpsPositionSnapshotMarker, ...] = Field(max_length=256)


class PerpsPositionSnapshot(BaseModel):
    """One position cycle valued at captured state or immediately after a fill.

    Financial values are exact. Owner-only leverage and PnL percentage can be
    unavailable even for the owner when historical leverage was not captured.
    """

    position_cycle_id: str
    side: PerpsSide
    started_at: datetime
    as_of_at: datetime
    is_closed: bool
    size_after: Decimal
    entry_price: Decimal
    as_of_price: Decimal
    pnl: Decimal
    pnl_percent: Decimal | None
    leverage: int | None = Field(ge=0)
    chart: PerpsPositionSnapshotChart

    @field_validator("started_at", "as_of_at", mode="before")
    @classmethod
    def _timestamps(cls, value: object) -> datetime:
        return _parse_timestamp(value)


class _PositionSnapshotIdentity(BaseModel):
    instrument_id: PerpsInstrumentId = Field(ge=0, le=4294967295)
    trade_id: str | None = None

    @field_validator("trade_id")
    @classmethod
    def _trade_id(cls, value: str | None) -> str | None:
        if value is not None and (
            re.fullmatch(r"0|[1-9][0-9]{0,19}", value) is None or int(value) > 2**64 - 1
        ):
            raise ValueError("expected canonical decimal u64 trade ID")
        return value


class PerpsPositionSnapshotSuccess(_PositionSnapshotIdentity):
    """A successful selection, containing its snapshot."""

    status: Literal["ok"]
    snapshot: PerpsPositionSnapshot


class PerpsPositionSnapshotFailure(_PositionSnapshotIdentity):
    """A selection without a snapshot. Inspect status before deciding to retry."""

    status: Literal[
        "not_found",
        "history_pending",
        "history_limit",
        "resource_limit",
        "temporarily_unavailable",
        "unavailable",
    ]

    @model_validator(mode="before")
    @classmethod
    def _no_snapshot(cls, value: object) -> object:
        if isinstance(value, dict) and "snapshot" in value:
            raise ValueError("only ok results contain a snapshot")
        return cast(object, value)


PerpsPositionSnapshotResult: TypeAlias = Annotated[
    PerpsPositionSnapshotSuccess | PerpsPositionSnapshotFailure, Field(discriminator="status")
]


class PerpsPositionSnapshots(BaseModel):
    """Ordered selections and the completed-history horizon; no pagination."""

    history_as_of_at: datetime
    active: tuple[PerpsPositionSnapshotResult, ...]
    history: tuple[PerpsPositionSnapshotResult, ...]

    @field_validator("history_as_of_at", mode="before")
    @classmethod
    def _timestamp(cls, value: object) -> datetime:
        return _parse_timestamp(value)

    @field_validator("history")
    @classmethod
    def _history_ids(
        cls, value: tuple[PerpsPositionSnapshotResult, ...]
    ) -> tuple[PerpsPositionSnapshotResult, ...]:
        if any(item.trade_id is None for item in value):
            raise ValueError("historical snapshots require trade_id")
        return value
