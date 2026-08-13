"""Perps deposit and withdrawal models."""

from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    _coerce_decimalish,  # pyright: ignore[reportPrivateUsage]
    _parse_epoch_ms,  # pyright: ignore[reportPrivateUsage]
    _parse_tx_hash,  # pyright: ignore[reportPrivateUsage]
    _require_epoch_ms,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.perps.types import (
    PerpsDepositStatus,
    PerpsWithdrawalId,
    PerpsWithdrawalStatus,
)


class PerpsDeposit(BaseModel):
    """One deposit into the Perps account."""

    hash: str
    asset: str
    amount: Decimal
    status: PerpsDepositStatus
    from_address: str = Field(validation_alias="from")
    to: str
    confirmations: int
    required_confirmations: int
    created_at: datetime = Field(validation_alias="created_timestamp")
    confirmed_at: datetime | None = Field(default=None, validation_alias="confirmed_timestamp")

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_created_at(cls, value: object) -> object:
        return _require_epoch_ms(value)

    @field_validator("confirmed_at", mode="before")
    @classmethod
    def _parse_confirmed_at(cls, value: object) -> object:
        return _parse_epoch_ms(value)


class PerpsDepositUpdate(BaseModel):
    """Streaming status update for one Perps deposit."""

    hash: str | None = None
    asset: str
    amount: Decimal
    status: PerpsDepositStatus

    @field_validator("hash", mode="before")
    @classmethod
    def _parse_hash(cls, value: object) -> object:
        return _parse_tx_hash(value)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsWithdrawal(BaseModel):
    """One withdrawal from the Perps account."""

    withdrawal_id: PerpsWithdrawalId = Field(validation_alias="withdraw_id")
    asset: str
    amount: Decimal
    fee: Decimal
    status: PerpsWithdrawalStatus
    to: str
    hash: str | None = None
    confirmations: int
    required_confirmations: int
    created_at: datetime = Field(validation_alias="created_timestamp")
    confirmed_at: datetime | None = Field(default=None, validation_alias="confirmed_timestamp")

    @field_validator("amount", "fee", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("hash", mode="before")
    @classmethod
    def _parse_hash(cls, value: object) -> object:
        return _parse_tx_hash(value)

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_created_at(cls, value: object) -> object:
        return _require_epoch_ms(value)

    @field_validator("confirmed_at", mode="before")
    @classmethod
    def _parse_confirmed_at(cls, value: object) -> object:
        return _parse_epoch_ms(value)


class PerpsWithdrawalUpdate(BaseModel):
    """Streaming status update for one Perps withdrawal."""

    withdrawal_id: PerpsWithdrawalId = Field(validation_alias="withdraw_id")
    asset: str
    amount: Decimal
    fee: Decimal
    status: PerpsWithdrawalStatus
    to: str
    hash: str | None = None

    @field_validator("amount", "fee", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("hash", mode="before")
    @classmethod
    def _parse_hash(cls, value: object) -> object:
        return _parse_tx_hash(value)


__all__ = [
    "PerpsDeposit",
    "PerpsDepositUpdate",
    "PerpsWithdrawal",
    "PerpsWithdrawalUpdate",
]
