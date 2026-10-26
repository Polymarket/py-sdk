from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NotRequired, TypeAlias, TypedDict

from polymarket.models.clob.relayer import TransactionOutcome

if TYPE_CHECKING:
    from polymarket._internal.eoa.rpc import JsonRpcClient, SyncJsonRpcClient
    from polymarket.clients._transport import AsyncTransport, SyncTransport


class MergeV2PositionRequest(TypedDict):
    """Polymarket V2 position merge request used by batch merge workflows."""

    position_id: str
    amount: NotRequired[int | Literal["max"]]


MergeComboPositionRequest: TypeAlias = MergeV2PositionRequest
"""Deprecated alias for :class:`MergeV2PositionRequest`."""


class MergeMarketConditionRequest(TypedDict):
    """Market position merge request identified by condition id."""

    condition_id: str
    amount: NotRequired[int | Literal["max"]]


class MergeMarketIdRequest(TypedDict):
    """Market position merge request identified by market id."""

    market_id: str
    amount: NotRequired[int | Literal["max"]]


MergeMarketPositionRequest: TypeAlias = MergeMarketConditionRequest | MergeMarketIdRequest
MergePositionRequest: TypeAlias = MergeV2PositionRequest | MergeMarketPositionRequest


@dataclass(frozen=True, slots=True)
class GaslessTransactionHandle:
    """Async handle for a relayed gasless transaction."""

    transaction_id: str
    transaction_hash: str | None
    _relayer: AsyncTransport = field(repr=False)
    _max_polls: int
    _poll_delay_s: float

    async def wait(self) -> TransactionOutcome:
        """Wait until the transaction reaches a terminal outcome."""
        from polymarket._internal.actions.relayer.poll import poll_until_terminal

        return await poll_until_terminal(
            self._relayer,
            transaction_id=self.transaction_id,
            fallback_hash=self.transaction_hash,
            max_polls=self._max_polls,
            poll_delay_s=self._poll_delay_s,
        )


@dataclass(frozen=True, slots=True)
class EoaTransactionHandle:
    """Async handle for a directly broadcast EOA transaction."""

    transaction_hash: str
    _rpc: JsonRpcClient = field(repr=False)
    _max_polls: int
    _poll_delay_s: float

    @property
    def transaction_id(self) -> None:
        """Return None because EOA transactions do not have relayer ids."""
        return None

    async def wait(self) -> TransactionOutcome:
        """Wait until the transaction reaches a terminal outcome."""
        from polymarket._internal.eoa.broadcast import wait_for_receipt

        return await wait_for_receipt(
            self._rpc,
            transaction_hash=self.transaction_hash,
            max_polls=self._max_polls,
            poll_delay_s=self._poll_delay_s,
        )


@dataclass(frozen=True, slots=True)
class DeprecatedTransactionHandle:
    """Compatibility handle for workflows that now wait internally."""

    transaction_hash: None = None
    transaction_id: None = None

    async def wait(self) -> None:
        """Return immediately; retained for backward compatibility."""
        return None


@dataclass(frozen=True, slots=True)
class SyncGaslessTransactionHandle:
    """Synchronous handle for a relayed gasless transaction."""

    transaction_id: str
    transaction_hash: str | None
    _relayer: SyncTransport = field(repr=False)
    _max_polls: int
    _poll_delay_s: float

    def wait(self) -> TransactionOutcome:
        """Wait until the transaction reaches a terminal outcome."""
        from polymarket._internal.actions.relayer.poll import poll_until_terminal_sync

        return poll_until_terminal_sync(
            self._relayer,
            transaction_id=self.transaction_id,
            fallback_hash=self.transaction_hash,
            max_polls=self._max_polls,
            poll_delay_s=self._poll_delay_s,
        )


@dataclass(frozen=True, slots=True)
class SyncEoaTransactionHandle:
    """Synchronous handle for a directly broadcast EOA transaction."""

    transaction_hash: str
    _rpc: SyncJsonRpcClient = field(repr=False)
    _max_polls: int
    _poll_delay_s: float

    @property
    def transaction_id(self) -> None:
        """Return None because EOA transactions do not have relayer ids."""
        return None

    def wait(self) -> TransactionOutcome:
        """Wait until the transaction reaches a terminal outcome."""
        from polymarket._internal.eoa.broadcast import wait_for_receipt_sync

        return wait_for_receipt_sync(
            self._rpc,
            transaction_hash=self.transaction_hash,
            max_polls=self._max_polls,
            poll_delay_s=self._poll_delay_s,
        )


@dataclass(frozen=True, slots=True)
class SyncDeprecatedTransactionHandle:
    """Synchronous compatibility handle for workflows that now wait internally."""

    transaction_hash: None = None
    transaction_id: None = None

    def wait(self) -> None:
        """Return immediately; retained for backward compatibility."""
        return None


TransactionHandle: TypeAlias = GaslessTransactionHandle | EoaTransactionHandle
"""Async transaction handle returned by async wallet methods."""

SyncTransactionHandle: TypeAlias = SyncGaslessTransactionHandle | SyncEoaTransactionHandle
"""Synchronous transaction handle returned by sync wallet methods."""


__all__ = [
    "EoaTransactionHandle",
    "GaslessTransactionHandle",
    "MergeComboPositionRequest",
    "MergeMarketConditionRequest",
    "MergeMarketIdRequest",
    "MergeMarketPositionRequest",
    "MergePositionRequest",
    "MergeV2PositionRequest",
    "DeprecatedTransactionHandle",
    "SyncDeprecatedTransactionHandle",
    "SyncEoaTransactionHandle",
    "SyncGaslessTransactionHandle",
    "SyncTransactionHandle",
    "TransactionHandle",
]
