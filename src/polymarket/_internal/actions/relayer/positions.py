from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from eth_abi.abi import encode as abi_encode
from eth_utils.crypto import keccak

from polymarket._internal.protocol import (
    DecodedV2OutcomePositionId,
    decode_v2_outcome_position_id,
)
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.data.portfolio import Position
from polymarket.models.gamma.market import Market
from polymarket.models.types import (
    ClobAssetId,
    ComboConditionId,
    ConditionId,
    MarketId,
    PositionId,
    to_combo_condition_id,
    to_condition_id,
)
from polymarket.types import EvmAddress

_TOKEN_DECIMALS = 1_000_000
_UINT256_MAX = (1 << 256) - 1
_UINT256_BYTE_LENGTH = 32
_COMBINATORIAL_MODULE_ID = 3
_MAX_COMBO_LEGS = 50

BinaryPositions = tuple[Position | None, Position | None]
CanonicalComboLegs = tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ComboPositionContext:
    condition_id: ComboConditionId
    position_ids: tuple[PositionId, PositionId]


@dataclass(frozen=True, slots=True)
class MarketPositionContext:
    protocol: Literal["ctf", "v2"]
    market_id: MarketId
    condition_id: ConditionId
    position_erc1155_address: EvmAddress
    token_ids: tuple[ClobAssetId, ClobAssetId]
    neg_risk: bool | None = None
    adapter_address: EvmAddress | None = None

    @property
    def outcome_ids(self) -> tuple[ClobAssetId, ClobAssetId]:
        return self.token_ids


DecodedComboOutcomePositionId = DecodedV2OutcomePositionId


@dataclass(frozen=True, slots=True)
class BatchMergePositionRequest:
    kind: Literal["combo", "market"]
    amount: int | Literal["max"]
    position_id: str | None = None
    condition_id: str | None = None
    market_id: str | None = None


def parse_market_id(market_id: str) -> int:
    try:
        parsed = Decimal(market_id.strip())
    except (InvalidOperation, ValueError) as error:
        raise UserInputError(f"Market ID must be an integer, received {market_id}") from error
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        raise UserInputError(f"Market ID must be an integer, received {market_id}")
    return int(parsed)


def normalize_market_position_context(
    market: Market,
    *,
    context: str,
    collateral_adapter: EvmAddress,
    neg_risk_collateral_adapter: EvmAddress,
    conditional_tokens: EvmAddress,
    neg_risk_adapter: EvmAddress,
    position_manager: EvmAddress,
) -> MarketPositionContext:
    condition_id = market.condition_id
    if condition_id is None:
        raise UnexpectedResponseError(f"Missing condition ID for {context}")

    yes_token_id = market.outcomes.yes.token_id
    no_token_id = market.outcomes.no.token_id
    if (yes_token_id is None) != (no_token_id is None):
        raise UnexpectedResponseError(f"Incomplete market token IDs for {context}")
    if yes_token_id is not None and no_token_id is not None:
        neg_risk = market.state.neg_risk
        if neg_risk is None:
            raise UnexpectedResponseError(f"Missing negative-risk flag for {context}")
        return MarketPositionContext(
            protocol="ctf",
            market_id=market.id,
            condition_id=condition_id,
            neg_risk=neg_risk,
            adapter_address=neg_risk_collateral_adapter if neg_risk else collateral_adapter,
            position_erc1155_address=neg_risk_adapter if neg_risk else conditional_tokens,
            token_ids=(yes_token_id, no_token_id),
        )

    yes_position_id = market.outcomes.yes.position_id
    no_position_id = market.outcomes.no.position_id
    if (yes_position_id is None) != (no_position_id is None):
        raise UnexpectedResponseError(f"Incomplete market position IDs for {context}")
    if yes_position_id is not None and no_position_id is not None:
        return MarketPositionContext(
            protocol="v2",
            market_id=market.id,
            condition_id=condition_id,
            position_erc1155_address=position_manager,
            token_ids=(yes_position_id, no_position_id),
        )
    raise UnexpectedResponseError(f"Missing tradeable outcome IDs for {context}")


def expect_binary_positions(positions: Sequence[Position]) -> BinaryPositions:
    if not positions:
        raise UserInputError("You have no positions")
    if len(positions) > 2:
        raise UnexpectedResponseError(f"Expected at most two positions, got {len(positions)}")

    yes_position: Position | None = None
    no_position: Position | None = None
    for position in positions:
        if position.outcome_index not in (0, 1):
            raise UnexpectedResponseError(
                f"Unexpected outcomeIndex {position.outcome_index} for condition "
                f"{position.condition_id}"
            )
        if position.outcome_index == 0:
            if yes_position is not None:
                raise UnexpectedResponseError(
                    f"Duplicate YES position for condition {position.condition_id}"
                )
            yes_position = position
        else:
            if no_position is not None:
                raise UnexpectedResponseError(
                    f"Duplicate NO position for condition {position.condition_id}"
                )
            no_position = position

    return yes_position, no_position


def expect_negative_risk_flag(positions: BinaryPositions) -> bool:
    yes_position, no_position = positions
    first = yes_position if yes_position is not None else no_position
    assert first is not None
    condition_id = first.condition_id
    if first.negative_risk is None:
        raise UnexpectedResponseError(f"Missing negativeRisk flag for condition {condition_id}")
    if yes_position is not None and no_position is not None:
        if yes_position.negative_risk is None or no_position.negative_risk is None:
            raise UnexpectedResponseError(f"Missing negativeRisk flag for condition {condition_id}")
        if yes_position.negative_risk != no_position.negative_risk:
            raise UnexpectedResponseError(f"Mixed negativeRisk flags for condition {condition_id}")
    return first.negative_risk


def resolve_binary_positions_condition_id(positions: BinaryPositions) -> str:
    yes_position, no_position = positions
    first = yes_position if yes_position is not None else no_position
    assert first is not None
    return first.condition_id


def _derive_binary_position_amounts(positions: BinaryPositions) -> tuple[int, int]:
    yes_position, no_position = positions
    return (
        _to_position_amount(yes_position, expected_outcome_index=0),
        _to_position_amount(no_position, expected_outcome_index=1),
    )


def calculate_max_merge_amount(positions: BinaryPositions) -> int:
    yes_amount, no_amount = _derive_binary_position_amounts(positions)
    return min(yes_amount, no_amount)


def resolve_merge_amount(
    positions: BinaryPositions,
    requested: int | Literal["max"],
) -> int:
    max_amount = calculate_max_merge_amount(positions)
    condition_id = resolve_binary_positions_condition_id(positions)
    if max_amount == 0:
        raise UserInputError(
            f"You have no complementary positions to merge for condition {condition_id}"
        )
    if requested == "max":
        return max_amount
    if requested <= 0:
        raise UserInputError("Merge amount must be positive")
    if requested > max_amount:
        raise UserInputError(
            f"Requested merge amount {requested} exceeds the maximum mergeable "
            f"amount {max_amount} for condition {condition_id}"
        )
    return requested


def resolve_merge_amount_from_balances(
    condition_id: str,
    balances: Sequence[int],
    requested: int | Literal["max"],
) -> int:
    max_amount = calculate_max_merge_amount_from_balances(balances)
    if max_amount == 0:
        raise UserInputError(
            f"You have no complementary positions to merge for condition {condition_id}"
        )
    if requested == "max":
        return max_amount
    if requested <= 0:
        raise UserInputError("Merge amount must be positive")
    if requested > max_amount:
        raise UserInputError(
            f"Requested merge amount {requested} exceeds the maximum mergeable "
            f"amount {max_amount} for condition {condition_id}"
        )
    return requested


def calculate_max_merge_amount_from_balances(balances: Sequence[int]) -> int:
    if len(balances) != 2:
        raise UnexpectedResponseError(f"Expected two position balances, got {len(balances)}")
    yes_amount, no_amount = balances
    return min(yes_amount, no_amount)


def canonicalize_combo_legs(legs: Sequence[str]) -> CanonicalComboLegs:
    if not 1 <= len(legs) <= _MAX_COMBO_LEGS:
        raise UserInputError(f"Combo legs must include 1 to {_MAX_COMBO_LEGS} position IDs")

    positions: list[tuple[int, str]] = []
    for leg in legs:
        value = _parse_position_id(leg)
        encoded = f"{value:0{_UINT256_BYTE_LENGTH * 2}x}"
        module_id = int(encoded[:2], 16)
        outcome_index = int(encoded[-2:], 16)
        if module_id not in (1, 2) or outcome_index > 1:
            raise UserInputError("Combo legs must be binary or neg-risk YES/NO position IDs")
        positions.append((value, encoded[:-2]))

    positions.sort(key=lambda item: item[0])
    for index in range(1, len(positions)):
        previous_value, previous_condition = positions[index - 1]
        current_value, current_condition = positions[index]
        if previous_value == current_value:
            raise UserInputError("Combo legs must not contain duplicate position IDs")
        if previous_condition == current_condition:
            raise UserInputError("Combo legs must not contain both outcomes for the same condition")

    return tuple(value for value, _ in positions)


def derive_combo_position_context(legs: CanonicalComboLegs) -> ComboPositionContext:
    encoded_legs = abi_encode(["uint256[]"], [list(legs)])
    base_hash = keccak(abi_encode(["uint256", "bytes"], [_COMBINATORIAL_MODULE_ID, encoded_legs]))
    condition_id = to_combo_condition_id(f"0x03{base_hash.hex()[32:]}{'0' * 28}")
    return ComboPositionContext(
        condition_id=condition_id,
        position_ids=derive_combo_outcome_position_ids(condition_id),
    )


def derive_combo_outcome_position_ids(condition_id: str) -> tuple[PositionId, PositionId]:
    normalized_condition_id = to_condition_id(condition_id)
    if len(normalized_condition_id) != 64:
        raise UserInputError("Protocol v2 condition ID must be a 31-byte hex string")
    return (
        PositionId(str(int(f"{normalized_condition_id}00", 16))),
        PositionId(str(int(f"{normalized_condition_id}01", 16))),
    )


def decode_combo_outcome_position_id(position_id: str) -> DecodedComboOutcomePositionId:
    """Deprecated alias for :func:`decode_v2_outcome_position_id`."""

    return decode_v2_outcome_position_id(PositionId(position_id))


def normalize_batch_merge_position_request(
    request: Mapping[str, object],
) -> BatchMergePositionRequest:
    identifiers = [key for key in ("position_id", "condition_id", "market_id") if key in request]
    if len(identifiers) != 1:
        raise UserInputError(
            "Each merge request must include exactly one of position_id, condition_id, or market_id"
        )

    identifier = identifiers[0]
    value = request[identifier]
    if not isinstance(value, str):
        raise UserInputError(f"{identifier} must be a string")

    raw_amount = request.get("amount", "max")
    if raw_amount != "max" and (isinstance(raw_amount, bool) or not isinstance(raw_amount, int)):
        raise UserInputError("amount must be an int or 'max'")
    amount = cast(int | Literal["max"], raw_amount)

    if identifier == "position_id":
        return BatchMergePositionRequest(kind="combo", position_id=value, amount=amount)
    if identifier == "condition_id":
        return BatchMergePositionRequest(kind="market", condition_id=value, amount=amount)
    return BatchMergePositionRequest(kind="market", market_id=value, amount=amount)


def _to_position_amount(position: Position | None, *, expected_outcome_index: Literal[0, 1]) -> int:
    if position is None:
        return 0
    if position.outcome_index != expected_outcome_index:
        raise UnexpectedResponseError(
            f"Expected outcomeIndex {expected_outcome_index}, got {position.outcome_index}"
        )
    if position.size is None:
        return 0
    if not position.size.is_finite():
        raise UnexpectedResponseError(f"Position size must be a finite number, got {position.size}")
    if position.size < 0:
        raise UnexpectedResponseError("Position size must be non-negative")
    return int(position.size * Decimal(_TOKEN_DECIMALS))


def _parse_position_id(position_id: str) -> int:
    if not position_id.strip():
        raise UserInputError("Position ID must be a uint256 value")
    try:
        value = int(position_id.strip())
    except ValueError as error:
        raise UserInputError("Position ID must be a uint256 value") from error
    if value < 0 or value > _UINT256_MAX:
        raise UserInputError("Position ID must be a uint256 value")
    return value


__all__ = [
    "BinaryPositions",
    "BatchMergePositionRequest",
    "CanonicalComboLegs",
    "ComboPositionContext",
    "DecodedComboOutcomePositionId",
    "DecodedV2OutcomePositionId",
    "MarketPositionContext",
    "calculate_max_merge_amount",
    "calculate_max_merge_amount_from_balances",
    "canonicalize_combo_legs",
    "decode_combo_outcome_position_id",
    "decode_v2_outcome_position_id",
    "derive_combo_outcome_position_ids",
    "derive_combo_position_context",
    "expect_binary_positions",
    "expect_negative_risk_flag",
    "normalize_batch_merge_position_request",
    "normalize_market_position_context",
    "parse_market_id",
    "resolve_binary_positions_condition_id",
    "resolve_merge_amount",
    "resolve_merge_amount_from_balances",
]
