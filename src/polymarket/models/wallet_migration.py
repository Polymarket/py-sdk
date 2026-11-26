"""Wallet migration models."""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.types import EvmAddress, HexString

_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
_DIGEST = re.compile(r"0x[0-9a-fA-F]{64}")


class WalletMigrationState(StrEnum):
    """Known states of a wallet migration and of a leftover sweep.

    A later release can add states, so ``state`` fields are plain strings.
    """

    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    SMART_WALLET_DEPLOYMENT_IN_PROGRESS = "SMART_WALLET_DEPLOYMENT_IN_PROGRESS"
    REQUIRES_FUNDS_TRANSFERS = "REQUIRES_FUNDS_TRANSFERS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WalletMigrationNextAction(StrEnum):
    """The next step of a wallet migration or of a leftover sweep."""

    NONE = "none"
    START = "start"
    SIGN = "sign"
    EXECUTE = "execute"


class WalletMigrationSweepShape(StrEnum):
    """How the account signs a sweep."""

    PROXY = "proxy"
    SAFE = "safe"
    SAFE_CREATE = "safe-create"


class WalletMigrationBlockerCode(StrEnum):
    """Known reasons that stop a wallet migration or a leftover sweep.

    A later release can add codes, so ``code`` fields are plain strings.
    """

    MULTIPLE_ACCOUNTS = "MULTIPLE_ACCOUNTS"
    UNSUPPORTED_WALLET = "UNSUPPORTED_WALLET"
    TOO_MANY_POSITIONS = "TOO_MANY_POSITIONS"
    LEGACY_FUNDS = "LEGACY_FUNDS"
    SIBLING_FUNDED = "SIBLING_FUNDED"
    DESTINATION_IN_USE = "DESTINATION_IN_USE"
    PROFILE_RESTRICTED = "PROFILE_RESTRICTED"


def _empty_list(value: object) -> object:
    return [] if value is None else value


def _optional_address(value: object) -> object:
    if value == "":
        return None
    if isinstance(value, str) and _ADDRESS.fullmatch(value) is None:
        raise ValueError("expected a 20-byte hex address")
    return value


def _next_action(value: object) -> object:
    if isinstance(value, dict):
        return cast(dict[str, Any], value).get("type")
    return value


def _decimal(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    return value


class WalletMigrationManifestEntry(BaseModel):
    """One asset class that a wallet holds."""

    asset_class: str = Field(validation_alias="assetClass")
    kind: str
    contract: str
    count: int
    raw_balance: str | None = Field(default=None, validation_alias="rawBalance")


class WalletMigrationBlocker(BaseModel):
    """A reason that stops a wallet migration or a leftover sweep."""

    code: str
    """The blocker code. Compare it with :class:`WalletMigrationBlockerCode`."""
    message: str
    """A plain-language message to show."""
    address: str | None = None
    limit: int | None = None
    assets: list[WalletMigrationManifestEntry] = Field(
        default_factory=list[WalletMigrationManifestEntry]
    )

    @field_validator("assets", mode="before")
    @classmethod
    def _assets(cls, value: object) -> object:
        return _empty_list(value)


class WalletMigration(BaseModel):
    """The wallet migration of an account."""

    state: str
    """The migration state. Compare it with :class:`WalletMigrationState`."""
    deposit_wallet: EvmAddress | None = Field(default=None, validation_alias="depositWallet")
    failed_reason: str | None = Field(default=None, validation_alias="failedReason")
    trading_paused: bool = Field(validation_alias="tradingPaused")
    cancelable: bool
    manifest: list[WalletMigrationManifestEntry]
    next_action: WalletMigrationNextAction = Field(validation_alias="nextAction")
    sweep_submitted: bool = Field(default=False, validation_alias="sweepSubmitted")

    @field_validator("deposit_wallet", mode="before")
    @classmethod
    def _deposit_wallet(cls, value: object) -> object:
        return _optional_address(value)

    @field_validator("manifest", mode="before")
    @classmethod
    def _manifest(cls, value: object) -> object:
        return _empty_list(value)

    @field_validator("next_action", mode="before")
    @classmethod
    def _next_action(cls, value: object) -> object:
        return _next_action(value)


class WalletMigrationPreview(BaseModel):
    """What a wallet migration would move, and each blocker that stops it."""

    manifest: list[WalletMigrationManifestEntry]
    position_count: int | None = Field(default=None, validation_alias="positionCount")
    markets_traded: int | None = Field(default=None, validation_alias="marketsTraded")
    blockers: list[WalletMigrationBlocker]

    @field_validator("manifest", "blockers", mode="before")
    @classmethod
    def _lists(cls, value: object) -> object:
        return _empty_list(value)


class WalletSweepSummary(BaseModel):
    """The last leftover sweep of an account."""

    state: str
    failed_reason: str | None = Field(default=None, validation_alias="failedReason")
    sweep_submitted: bool = Field(default=False, validation_alias="sweepSubmitted")


class WalletLeftovers(BaseModel):
    """What the old wallet of a migrated account still holds."""

    has_leftovers: bool = Field(validation_alias="hasLeftovers")
    legacy_wallet: EvmAddress | None = Field(default=None, validation_alias="legacyWallet")
    deposit_wallet: EvmAddress | None = Field(default=None, validation_alias="depositWallet")
    manifest: list[WalletMigrationManifestEntry]
    position_count: int | None = Field(default=None, validation_alias="positionCount")
    cash_usd: Decimal = Field(validation_alias="cashUsd")
    positions_value_usd: Decimal | None = Field(default=None, validation_alias="positionsValueUsd")
    amount_usd: Decimal = Field(validation_alias="amountUsd")
    amount_complete: bool = Field(validation_alias="amountComplete")
    blockers: list[WalletMigrationBlocker]
    last_sweep: WalletSweepSummary | None = Field(default=None, validation_alias="lastSweep")
    sweep_available: bool = Field(validation_alias="sweepAvailable")

    @field_validator("legacy_wallet", "deposit_wallet", mode="before")
    @classmethod
    def _addresses(cls, value: object) -> object:
        return _optional_address(value)

    @field_validator("manifest", "blockers", mode="before")
    @classmethod
    def _lists(cls, value: object) -> object:
        return _empty_list(value)

    @field_validator("cash_usd", "positions_value_usd", "amount_usd", mode="before")
    @classmethod
    def _amounts(cls, value: object) -> object:
        return _decimal(value)


class WalletMigrationSweep(BaseModel):
    """A sweep that the account signs."""

    digest: HexString
    shape: WalletMigrationSweepShape
    typed_data: dict[str, Any] | None = Field(default=None, validation_alias="typedData")

    @field_validator("digest", mode="before")
    @classmethod
    def _digest(cls, value: object) -> object:
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            raise ValueError("expected a 32-byte hex digest")
        return value


class WalletMigrationStep(BaseModel):
    """One step of a wallet migration or of a leftover sweep."""

    state: str
    deposit_wallet: EvmAddress | None = Field(default=None, validation_alias="depositWallet")
    failed_reason: str | None = Field(default=None, validation_alias="failedReason")
    next_action: WalletMigrationNextAction = Field(validation_alias="nextAction")
    sweep: WalletMigrationSweep | None = None
    sweep_submitted: bool = Field(default=False, validation_alias="sweepSubmitted")

    @field_validator("deposit_wallet", mode="before")
    @classmethod
    def _deposit_wallet(cls, value: object) -> object:
        return _optional_address(value)

    @field_validator("next_action", mode="before")
    @classmethod
    def _next_action(cls, value: object) -> object:
        return _next_action(value)


__all__ = [
    "WalletLeftovers",
    "WalletMigration",
    "WalletMigrationBlocker",
    "WalletMigrationBlockerCode",
    "WalletMigrationManifestEntry",
    "WalletMigrationNextAction",
    "WalletMigrationPreview",
    "WalletMigrationState",
    "WalletMigrationStep",
    "WalletMigrationSweep",
    "WalletMigrationSweepShape",
    "WalletSweepSummary",
]
