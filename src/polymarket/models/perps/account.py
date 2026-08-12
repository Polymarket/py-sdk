"""Perps account models."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import cast

from pydantic import AliasChoices, Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    _coerce_decimalish,  # pyright: ignore[reportPrivateUsage]
    _parse_auto_cancel_deadline,  # pyright: ignore[reportPrivateUsage]
    _require_epoch_ms,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.perps.types import (
    PerpsEntityId,
    PerpsFundingPaymentId,
    PerpsInstrumentId,
)

# Proxy key expiries above this magnitude are nanoseconds; convert to ms.
_MAX_EPOCH_MS = 2**53 - 1


class PerpsBalance(BaseModel):
    """One asset balance in the Perps account."""

    asset: str
    balance: Decimal
    value: Decimal

    @field_validator("balance", "value", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsAutoCancelStatus(BaseModel):
    """Current auto-cancel state for the account.

    ``deadline`` is the armed cancellation time, or ``None`` when no schedule
    is armed. ``triggered`` counts today's fires, ``daily_limit`` is the
    maximum triggers allowed per UTC day, and ``next_reset`` is when the
    daily counter resets.
    """

    deadline: datetime | None
    triggered: int
    daily_limit: int
    next_reset: datetime

    @field_validator("deadline", mode="before")
    @classmethod
    def _parse_deadline(cls, value: object) -> object:
        return _parse_auto_cancel_deadline(value)

    @field_validator("next_reset", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsAccountStats(BaseModel):
    """Rolling 7-day trading statistics for the Perps account."""

    volume_7d: Decimal
    taker_volume_7d: Decimal
    maker_volume_7d: Decimal
    account_maker_share_7d: Decimal
    entity_maker_share_7d: Decimal | None = None
    entity_id: PerpsEntityId | None = None
    entity_name: str | None = None

    @field_validator(
        "volume_7d",
        "taker_volume_7d",
        "maker_volume_7d",
        "account_maker_share_7d",
        "entity_maker_share_7d",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsPosition(BaseModel):
    """One open Perps position."""

    instrument_id: PerpsInstrumentId
    symbol: str
    size: Decimal
    entry_price: Decimal
    leverage: int
    cross: bool
    initial_margin: Decimal
    maintenance_margin: Decimal
    position_value: Decimal
    liquidation_price: Decimal
    unrealized_pnl: Decimal
    return_on_equity: Decimal
    cumulative_funding: Decimal

    @field_validator(
        "size",
        "entry_price",
        "initial_margin",
        "maintenance_margin",
        "position_value",
        "liquidation_price",
        "unrealized_pnl",
        "return_on_equity",
        "cumulative_funding",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsMarginSummary(BaseModel):
    """Account-wide margin totals."""

    total_account_value: Decimal
    total_initial_margin: Decimal
    total_maintenance_margin: Decimal
    total_position_value: Decimal

    @field_validator(
        "total_account_value",
        "total_initial_margin",
        "total_maintenance_margin",
        "total_position_value",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsPortfolio(BaseModel):
    """Portfolio snapshot for the Perps account."""

    positions: tuple[PerpsPosition, ...]
    margin: PerpsMarginSummary
    withdrawable: Decimal
    in_liquidation: bool
    timestamp: datetime

    @field_validator("withdrawable", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsFundingPayment(BaseModel):
    """One funding payment applied to a position."""

    id: PerpsFundingPaymentId
    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    size: Decimal = Field(validation_alias=AliasChoices("size", "sz"))
    funding_rate: Decimal = Field(validation_alias=AliasChoices("funding_rate", "fr"))
    funding_asset: str = Field(validation_alias=AliasChoices("funding_asset", "fua"))
    funding: Decimal = Field(validation_alias=AliasChoices("funding", "fund"))
    timestamp: datetime = Field(validation_alias=AliasChoices("timestamp", "ts"))

    @field_validator("size", "funding_rate", "funding", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsAccountConfig(BaseModel):
    """Leverage configuration for one instrument."""

    instrument_id: PerpsInstrumentId
    leverage: int
    cross: bool


class PerpsEquityPoint(BaseModel):
    """One account equity observation."""

    timestamp: datetime
    equity: Decimal

    @model_validator(mode="before")
    @classmethod
    def _from_tuple(cls, data: object) -> object:
        if not isinstance(data, (list, tuple)):
            return data
        entries = cast("Sequence[object]", data)
        if len(entries) != 2:
            return list(entries)
        return {"timestamp": entries[0], "equity": entries[1]}

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)

    @field_validator("equity", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsPnlPoint(BaseModel):
    """One account profit-and-loss observation."""

    timestamp: datetime
    pnl: Decimal

    @model_validator(mode="before")
    @classmethod
    def _from_tuple(cls, data: object) -> object:
        if not isinstance(data, (list, tuple)):
            return data
        entries = cast("Sequence[object]", data)
        if len(entries) != 2:
            return list(entries)
        return {"timestamp": entries[0], "pnl": entries[1]}

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)

    @field_validator("pnl", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


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
    expires_at: datetime = Field(validation_alias="expiry")

    @field_validator("expires_at", mode="before")
    @classmethod
    def _parse_expiry(cls, value: object) -> object:
        return _require_epoch_ms(_normalize_proxy_expiry(value))


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
