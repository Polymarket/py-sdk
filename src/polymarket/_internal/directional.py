"""Module-4 identifier validation, derivation and inventory baskets."""

import re
from dataclasses import dataclass
from typing import Literal

from polymarket.errors import UserInputError
from polymarket.models.directional import (
    DecodedPositionId,
    DirectionalBucketPositions,
    DirectionalInstrumentKind,
    DirectionalSide,
    DirectionalThresholdPositions,
    ThresholdSideInput,
)
from polymarket.models.types import ConditionId, DirectionalEventId, PositionId

UINT256_MAX = (1 << 256) - 1
_RESERVED_MASK = ((1 << 64) - 1) << 40


def normalize_directional_event_id(event_id: str) -> DirectionalEventId:
    if (
        type(event_id) is not str
        or re.fullmatch(r"0x(?:[a-fA-F0-9]{58}|[a-fA-F0-9]{64})", event_id) is None
    ):
        raise UserInputError("Expected a bytes29 directional event ID or zero-padded bytes32")
    if len(event_id) == 66 and not event_id.endswith("000000"):
        raise UserInputError("Directional event ID must have zero padding")
    event_id = event_id[:60].lower()
    value = int(event_id + "000000", 16)
    bucket_count = (value >> 104) & 0xFFFF
    if value >> 248 != 4 or value & _RESERVED_MASK or not 2 <= bucket_count <= 0x7FFF:
        raise UserInputError(
            "Expected a directional event ID with valid bucket count and reserved bits"
        )
    return DirectionalEventId(event_id)


def bucket_count_of(event_id: DirectionalEventId) -> int:
    return (int(event_id + "000000", 16) >> 104) & 0xFFFF


def normalize_directional_condition_id(condition_id: str) -> ConditionId:
    if (
        type(condition_id) is not str
        or re.fullmatch(r"0x(?:[a-fA-F0-9]{62}|[a-fA-F0-9]{64})", condition_id) is None
    ):
        raise UserInputError("Expected a bytes31 directional condition ID or zero-padded bytes32")
    if len(condition_id) == 66 and not condition_id.endswith("00"):
        raise UserInputError("Directional condition ID must have a zero outcome byte")
    normalized = condition_id[:64].lower()
    event_id = normalize_directional_event_id(normalized[:60])
    count = bucket_count_of(event_id)
    descriptor = int(normalized[60:], 16)
    if descriptor & 0x8000:
        if not 1 <= (descriptor & 0x7FFF) < count:
            raise UserInputError("Expected a threshold line below the real-bucket count")
    elif descriptor > count:
        raise UserInputError("Expected a real bucket index or the Void index")
    return ConditionId(normalized)


def decode_position_id(position_id: str) -> DecodedPositionId:
    """Decode a decimal directional position ID locally.

    Raises UserInputError for malformed identifiers or other modules.
    """
    if type(position_id) is not str or re.fullmatch(r"(?:0|[1-9][0-9]{0,77})", position_id) is None:
        raise UserInputError("Expected a decimal directional position ID")
    value = int(position_id)
    if value > UINT256_MAX or value & 0xFF not in (0, 1):
        raise UserInputError("Expected a uint256 directional YES/NO position ID")
    condition_id = normalize_directional_condition_id(f"0x{value:064x}"[:64])
    event_id = DirectionalEventId(condition_id[:60])
    count = bucket_count_of(event_id)
    descriptor = int(condition_id[60:], 16)
    if descriptor & 0x8000:
        kind = DirectionalInstrumentKind.LINE
        index = descriptor & 0x7FFF
        side = DirectionalSide.ABOVE if value & 0xFF == 0 else DirectionalSide.BELOW
    else:
        kind = (
            DirectionalInstrumentKind.VOID
            if descriptor == count
            else DirectionalInstrumentKind.BUCKET
        )
        index = descriptor
        side = DirectionalSide.YES if value & 0xFF == 0 else DirectionalSide.NO
    return DecodedPositionId(4, event_id, condition_id, count, kind, index, side)


def derive_outcome_position_id(condition_id: ConditionId, outcome: Literal[0, 1]) -> PositionId:
    return PositionId(str((int(condition_id, 16) << 8) | outcome))


def derive_directional_bucket_positions(
    *, event_id: str, bucket_index: int
) -> DirectionalBucketPositions:
    """Derive bucket YES/NO IDs locally. Index B identifies Void.

    Raises UserInputError for an invalid event or bucket index.
    """
    event = normalize_directional_event_id(event_id)
    if type(bucket_index) is not int or not 0 <= bucket_index <= bucket_count_of(event):
        raise UserInputError("bucket_index must identify a real bucket or Void")
    condition = ConditionId(f"{event}{bucket_index:04x}")
    return DirectionalBucketPositions(
        condition,
        derive_outcome_position_id(condition, 0),
        derive_outcome_position_id(condition, 1),
    )


def derive_directional_threshold_positions(
    *, event_id: str, line: int
) -> DirectionalThresholdPositions:
    """Derive threshold ABOVE/BELOW IDs locally, using an ordinal line.

    Raises UserInputError for an invalid event or line.
    """
    event = normalize_directional_event_id(event_id)
    if type(line) is not int or not 1 <= line < bucket_count_of(event):
        raise UserInputError("line must be between 1 and the real-bucket count minus 1")
    condition = ConditionId(f"{event}{0x8000 | line:04x}")
    return DirectionalThresholdPositions(
        condition,
        derive_outcome_position_id(condition, 0),
        derive_outcome_position_id(condition, 1),
    )


@dataclass(frozen=True, slots=True)
class DirectionalPairContext:
    event_id: DirectionalEventId
    low_line: int
    high_line: int
    above_position_id: PositionId
    below_position_id: PositionId


def validate_directional_pair(position_id_a: str, position_id_b: str) -> DirectionalPairContext:
    a, b = decode_position_id(position_id_a), decode_position_id(position_id_b)
    if (
        a.kind != DirectionalInstrumentKind.LINE
        or b.kind != DirectionalInstrumentKind.LINE
        or a.event_id != b.event_id
        or a.side == b.side
    ):
        raise UserInputError(
            "Expected ABOVE and BELOW threshold positions in the same directional event"
        )
    above, below = (a, b) if a.side == DirectionalSide.ABOVE else (b, a)
    if above.index >= below.index:
        raise UserInputError("Expected ABOVE on a lower threshold than BELOW")
    return DirectionalPairContext(
        above.event_id,
        above.index,
        below.index,
        PositionId(position_id_a if above is a else position_id_b),
        PositionId(position_id_a if below is a else position_id_b),
    )


def validate_directional_amount(amount: int | Literal["max"]) -> None:
    if amount != "max" and (type(amount) is not int or not 0 < amount <= UINT256_MAX):
        raise UserInputError("amount must be a positive uint256 integer in base units or 'max'")


def bucket_yes_ids(event_id: DirectionalEventId, start: int, end: int) -> list[PositionId]:
    return [
        derive_outcome_position_id(ConditionId(f"{event_id}{i:04x}"), 0) for i in range(start, end)
    ]


def threshold_basket_ids(
    event_id: DirectionalEventId, line: int, side: ThresholdSideInput
) -> list[PositionId]:
    count = bucket_count_of(event_id)
    if side == "above":
        return bucket_yes_ids(event_id, line, count)
    if side == "below":
        return [*bucket_yes_ids(event_id, 0, line), *bucket_yes_ids(event_id, count, count + 1)]
    raise UserInputError("side must be 'above' or 'below'")
