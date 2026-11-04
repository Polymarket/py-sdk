"""Shared directional balance policy and candidate discovery."""

from collections.abc import Sequence
from typing import Literal

from polymarket._internal.directional import decode_position_id, validate_directional_amount
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.data.portfolio import Position
from polymarket.models.directional import (
    DirectionalInstrumentKind,
    DirectionalPair,
    DirectionalSide,
)
from polymarket.models.types import DirectionalEventId, PositionId


def resolve_directional_amount(
    assets: Sequence[str], balances: Sequence[int], amount: int | Literal["max"]
) -> int:
    validate_directional_amount(amount)
    if not assets or len(assets) != len(balances):
        raise UnexpectedResponseError("Expected one balance per required directional asset")
    maximum = min(balances)
    limiting = assets[balances.index(maximum)]
    if maximum == 0:
        raise UserInputError(f"You have no balance of required asset {limiting}")
    if amount == "max":
        return maximum
    if amount > maximum:
        raise UserInputError(
            f"Requested amount {amount} exceeds available balance {maximum} of {limiting}"
        )
    return amount


def collect_directional_candidates(
    positions: Sequence[Position], event_id: DirectionalEventId | None
) -> list[PositionId]:
    candidates: list[PositionId] = []
    for holding in positions:
        try:
            position = decode_position_id(holding.asset_id)
        except UserInputError:
            continue
        if position.kind == DirectionalInstrumentKind.LINE and (
            event_id is None or position.event_id == event_id
        ):
            candidates.append(PositionId(holding.asset_id))
    return candidates


def directional_pairs_from_balances(
    position_ids: Sequence[PositionId], balances: Sequence[int]
) -> tuple[DirectionalPair, ...]:
    if len(position_ids) != len(balances):
        raise UnexpectedResponseError("Expected one balance per directional position")
    above: list[tuple[PositionId, int]] = []
    below: list[tuple[PositionId, int]] = []
    for position_id, balance in zip(position_ids, balances, strict=True):
        if balance <= 0:
            continue
        position = decode_position_id(position_id)
        if position.kind != DirectionalInstrumentKind.LINE:
            continue
        if position.side == DirectionalSide.ABOVE:
            above.append((position_id, balance))
        else:
            below.append((position_id, balance))
    pairs: list[DirectionalPair] = []
    for low_id, low_balance in above:
        low = decode_position_id(low_id)
        for high_id, high_balance in below:
            high = decode_position_id(high_id)
            if low.event_id == high.event_id and low.index < high.index:
                amount = min(low_balance, high_balance)
                pairs.append(
                    DirectionalPair(
                        low.event_id, low.index, high.index, low_id, high_id, amount, amount
                    )
                )
    return tuple(pairs)
