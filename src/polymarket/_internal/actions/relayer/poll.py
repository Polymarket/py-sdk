from __future__ import annotations

import asyncio
import time
from typing import cast

from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import TimeoutError, TransactionFailedError, UnexpectedResponseError
from polymarket.models.clob.relayer import (
    GaslessTransaction,
    RelayerTransactionState,
    TransactionOutcome,
)
from polymarket.types import TransactionHash

_TERMINAL_SUCCESS = (RelayerTransactionState.CONFIRMED,)
_TERMINAL_FAILURE = (RelayerTransactionState.FAILED, RelayerTransactionState.INVALID)


async def fetch_gasless_transaction(
    relayer: AsyncTransport, *, transaction_id: str
) -> GaslessTransaction:
    data = await relayer.get_json(f"/v1/wallets/transactions/{transaction_id}")
    return GaslessTransaction.parse_response(data)


def fetch_gasless_transaction_sync(
    relayer: SyncTransport, *, transaction_id: str
) -> GaslessTransaction:
    data = relayer.get_json(f"/v1/wallets/transactions/{transaction_id}")
    return GaslessTransaction.parse_response(data)


async def poll_until_terminal(
    relayer: AsyncTransport,
    *,
    transaction_id: str,
    fallback_hash: str | None,
    max_polls: int,
    poll_delay_s: float,
) -> TransactionOutcome:
    for _ in range(max_polls):
        tx = await fetch_gasless_transaction(relayer, transaction_id=transaction_id)
        outcome = _terminal_outcome(tx, transaction_id=transaction_id, fallback_hash=fallback_hash)
        if outcome is not None:
            return outcome
        await asyncio.sleep(poll_delay_s)
    raise TimeoutError(
        f"Timed out waiting for transaction {transaction_id} after "
        f"{max_polls} polls ({max_polls * poll_delay_s:.0f}s)"
    )


def poll_until_terminal_sync(
    relayer: SyncTransport,
    *,
    transaction_id: str,
    fallback_hash: str | None,
    max_polls: int,
    poll_delay_s: float,
) -> TransactionOutcome:
    for _ in range(max_polls):
        tx = fetch_gasless_transaction_sync(relayer, transaction_id=transaction_id)
        outcome = _terminal_outcome(tx, transaction_id=transaction_id, fallback_hash=fallback_hash)
        if outcome is not None:
            return outcome
        time.sleep(poll_delay_s)
    raise TimeoutError(
        f"Timed out waiting for transaction {transaction_id} after "
        f"{max_polls} polls ({max_polls * poll_delay_s:.0f}s)"
    )


def _terminal_outcome(
    tx: GaslessTransaction, *, transaction_id: str, fallback_hash: str | None
) -> TransactionOutcome | None:
    if tx.state in _TERMINAL_SUCCESS:
        tx_hash = tx.transaction_hash or fallback_hash
        if tx_hash is None:
            raise UnexpectedResponseError(
                f"Transaction {transaction_id} settled without a transaction hash"
            )
        return TransactionOutcome(
            transaction_hash=cast(TransactionHash, tx_hash),
            transaction_id=tx.transaction_id,
        )
    if tx.state in _TERMINAL_FAILURE:
        raise TransactionFailedError(
            tx.error_msg or f"Transaction {transaction_id} reached terminal state {tx.state}"
        )
    return None


__all__ = [
    "fetch_gasless_transaction",
    "fetch_gasless_transaction_sync",
    "poll_until_terminal",
    "poll_until_terminal_sync",
]
