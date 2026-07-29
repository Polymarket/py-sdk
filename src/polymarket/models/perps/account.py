"""Perps account models."""

from collections.abc import Sequence
from typing import Annotated, cast

from pydantic import AliasChoices, BeforeValidator, Field, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import PerpsTimestamp, _Decimal
from polymarket.models.perps.types import PerpsEntityId, PerpsInstrumentId

# Proxy key expiries above this magnitude are nanoseconds; convert to ms.
_MAX_EPOCH_MS = 2**53 - 1


class PerpsBalance(BaseModel):
    """One asset balance in the Perps account."""

    asset: str
    balance: _Decimal
    value: _Decimal


class PerpsAutoCancelStatus(BaseModel):
    """Current auto-cancel state for the account.

    ``deadline`` is the armed cancellation time in epoch milliseconds, or
    ``0`` when no schedule is armed. ``triggered`` counts today's fires,
    ``daily_limit`` is the maximum triggers allowed per UTC day, and
    ``next_reset`` is the epoch-ms time when the daily counter resets.
    """

    deadline: int
    triggered: int
    daily_limit: int
    next_reset: int


class PerpsAccountStats(BaseModel):
    """Rolling 7-day trading statistics for the Perps account."""

    volume_7d: _Decimal
    taker_volume_7d: _Decimal
    maker_volume_7d: _Decimal
    account_maker_share_7d: _Decimal
    entity_maker_share_7d: _Decimal | None = None
    entity_id: PerpsEntityId | None = None
    entity_name: str | None = None


class PerpsPosition(BaseModel):
    """One open Perps position."""

    instrument_id: PerpsInstrumentId
    symbol: str
    size: _Decimal
    entry_price: _Decimal
    leverage: int
    cross: bool
    initial_margin: _Decimal
    maintenance_margin: _Decimal
    position_value: _Decimal
    liquidation_price: _Decimal
    unrealized_pnl: _Decimal
    return_on_equity: _Decimal
    cumulative_funding: _Decimal


class PerpsMarginSummary(BaseModel):
    """Account-wide margin totals."""

    total_account_value: _Decimal
    total_initial_margin: _Decimal
    total_maintenance_margin: _Decimal
    total_position_value: _Decimal


class PerpsPortfolio(BaseModel):
    """Portfolio snapshot for the Perps account."""

    positions: tuple[PerpsPosition, ...]
    margin: PerpsMarginSummary
    withdrawable: _Decimal
    in_liquidation: bool
    timestamp: PerpsTimestamp


class PerpsFundingPayment(BaseModel):
    """One funding payment applied to a position."""

    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    size: _Decimal = Field(validation_alias=AliasChoices("size", "sz"))
    funding_rate: _Decimal = Field(validation_alias=AliasChoices("funding_rate", "fr"))
    funding_asset: str = Field(validation_alias=AliasChoices("funding_asset", "fua"))
    funding: _Decimal = Field(validation_alias=AliasChoices("funding", "fund"))
    timestamp: PerpsTimestamp = Field(validation_alias=AliasChoices("timestamp", "ts"))


class PerpsAccountConfig(BaseModel):
    """Leverage configuration for one instrument."""

    instrument_id: PerpsInstrumentId
    leverage: int
    cross: bool


class PerpsEquityPoint(BaseModel):
    """One account equity observation."""

    timestamp: PerpsTimestamp
    equity: _Decimal

    @model_validator(mode="before")
    @classmethod
    def _from_tuple(cls, data: object) -> object:
        if not isinstance(data, (list, tuple)):
            return data
        entries = cast("Sequence[object]", data)
        if len(entries) != 2:
            return list(entries)
        return {"timestamp": entries[0], "equity": entries[1]}


class PerpsPnlPoint(BaseModel):
    """One account profit-and-loss observation."""

    timestamp: PerpsTimestamp
    pnl: _Decimal

    @model_validator(mode="before")
    @classmethod
    def _from_tuple(cls, data: object) -> object:
        if not isinstance(data, (list, tuple)):
            return data
        entries = cast("Sequence[object]", data)
        if len(entries) != 2:
            return list(entries)
        return {"timestamp": entries[0], "pnl": entries[1]}


def _normalize_proxy_expiry(value: object) -> object:
    if isinstance(value, bool) or not isinstance(value, int):
        return value
    if value > _MAX_EPOCH_MS:
        return value // 1_000_000
    return value


class PerpsProxyKey(BaseModel):
    """One delegated Perps session key registered for the account."""

    proxy: str
    label: str | None = None
    expires_at: Annotated[PerpsTimestamp, BeforeValidator(_normalize_proxy_expiry)] = Field(
        validation_alias="expiry"
    )


class PerpsCredentialsInfo(BaseModel):
    """Delegated session keys registered for a signer account."""

    address: str
    keys: tuple[PerpsProxyKey, ...]


__all__ = [
    "PerpsAccountConfig",
    "PerpsAccountStats",
    "PerpsAutoCancelStatus",
    "PerpsBalance",
    "PerpsCredentialsInfo",
    "PerpsEquityPoint",
    "PerpsFundingPayment",
    "PerpsMarginSummary",
    "PerpsPnlPoint",
    "PerpsPortfolio",
    "PerpsPosition",
    "PerpsProxyKey",
]
