from __future__ import annotations

import asyncio
import time
from typing import cast

from polymarket._internal.actions.account import (
    build_list_account_trades_request,
    parse_account_trades_page,
)
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import TimeoutError, TransactionFailedError
from polymarket.models.clob.account import ClobTrade
from polymarket.models.clob.order_response import AcceptedOrder
from polymarket.types import TransactionHash

DEFAULT_SETTLEMENT_TIMEOUT_S = 30.0
_SETTLEMENT_POLL_DELAY_S = 0.25


def _is_trade_settled(trade: ClobTrade) -> bool:
    # A trade is settled once execution reached a terminal outcome: its
    # transaction is confirmed on-chain, or it failed and never will be.
    # Earlier statuses are not terminal: a transaction hash observed before
    # confirmation can still be replaced if the transaction is retried.
    return trade.status in ("CONFIRMED", "FAILED")


def _is_failed_trade(trade: ClobTrade) -> bool:
    return trade.status == "FAILED"


def _pending_trade_ids(
    trade_ids: tuple[str, ...], settled: dict[str, ClobTrade]
) -> tuple[str, ...]:
    return tuple(trade_id for trade_id in trade_ids if trade_id not in settled)


def _record_settled_trades(
    trades: tuple[ClobTrade, ...],
    trade_ids: tuple[str, ...],
    settled: dict[str, ClobTrade],
) -> None:
    for trade in trades:
        if trade.id in trade_ids and _is_trade_settled(trade):
            settled[trade.id] = trade


def _raise_settlement_timeout(trade_ids: tuple[str, ...], settled: dict[str, ClobTrade]) -> None:
    unsettled = ", ".join(_pending_trade_ids(trade_ids, settled))
    raise TimeoutError(f"Timed out waiting for trades to settle: {unsettled}")


def _collect_settlement_hashes(
    order: AcceptedOrder,
    trade_ids: tuple[str, ...],
    settled: dict[str, ClobTrade],
) -> tuple[TransactionHash, ...]:
    trades = tuple(settled[trade_id] for trade_id in trade_ids if trade_id in settled)
    if trades and all(_is_failed_trade(trade) for trade in trades):
        raise TransactionFailedError(
            f"Every fill of order {order.order_id} failed execution: {', '.join(trade_ids)}"
        )
    hashes = dict.fromkeys(
        trade.transaction_hash for trade in trades if not _is_failed_trade(trade)
    )
    return tuple(cast(TransactionHash, tx_hash) for tx_hash in hashes)


def wait_for_order_fill_settlement_sync(
    secure_clob: SyncTransport,
    order: AcceptedOrder,
    *,
    timeout_s: float = DEFAULT_SETTLEMENT_TIMEOUT_S,
) -> tuple[TransactionHash, ...]:
    trade_ids = tuple(dict.fromkeys(order.trade_ids))
    if not trade_ids:
        return tuple(order.transactions_hashes)

    settled: dict[str, ClobTrade] = {}
    deadline = time.monotonic() + timeout_s

    while True:
        for trade_id in _pending_trade_ids(trade_ids, settled):
            path, params = build_list_account_trades_request(id=trade_id)
            page = parse_account_trades_page(secure_clob.get_json(path, params=params))
            _record_settled_trades(page.items, trade_ids, settled)

        if len(settled) == len(trade_ids):
            break
        if time.monotonic() >= deadline:
            _raise_settlement_timeout(trade_ids, settled)
        time.sleep(_SETTLEMENT_POLL_DELAY_S)

    return _collect_settlement_hashes(order, trade_ids, settled)


async def wait_for_order_fill_settlement(
    secure_clob: AsyncTransport,
    order: AcceptedOrder,
    *,
    timeout_s: float = DEFAULT_SETTLEMENT_TIMEOUT_S,
) -> tuple[TransactionHash, ...]:
    trade_ids = tuple(dict.fromkeys(order.trade_ids))
    if not trade_ids:
        return tuple(order.transactions_hashes)

    settled: dict[str, ClobTrade] = {}
    deadline = time.monotonic() + timeout_s

    while True:
        for trade_id in _pending_trade_ids(trade_ids, settled):
            path, params = build_list_account_trades_request(id=trade_id)
            page = parse_account_trades_page(await secure_clob.get_json(path, params=params))
            _record_settled_trades(page.items, trade_ids, settled)

        if len(settled) == len(trade_ids):
            break
        if time.monotonic() >= deadline:
            _raise_settlement_timeout(trade_ids, settled)
        await asyncio.sleep(_SETTLEMENT_POLL_DELAY_S)

    return _collect_settlement_hashes(order, trade_ids, settled)


__all__ = [
    "DEFAULT_SETTLEMENT_TIMEOUT_S",
    "wait_for_order_fill_settlement",
    "wait_for_order_fill_settlement_sync",
]
