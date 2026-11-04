"""Directional instruments and collateral-return candidates."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from polymarket.models.types import ConditionId, DirectionalEventId, PositionId


class DirectionalInstrumentKind(StrEnum):
    LINE = "line"
    BUCKET = "bucket"
    VOID = "void"


class DirectionalSide(StrEnum):
    ABOVE = "above"
    BELOW = "below"
    YES = "yes"
    NO = "no"


class ThresholdSide(StrEnum):
    ABOVE = "above"
    BELOW = "below"


ThresholdSideInput = Literal["above", "below"] | ThresholdSide


@dataclass(frozen=True, slots=True)
class DecodedPositionId:
    """A directional position. Indices are ordinal boundaries, not scalar values."""

    module_id: Literal[4]
    event_id: DirectionalEventId
    condition_id: ConditionId
    bucket_count: int
    kind: DirectionalInstrumentKind
    index: int
    side: DirectionalSide


@dataclass(frozen=True, slots=True)
class DirectionalBucketPositions:
    """Complementary YES/NO positions for a real bucket or Void."""

    condition_id: ConditionId
    yes_position_id: PositionId
    no_position_id: PositionId


@dataclass(frozen=True, slots=True)
class DirectionalThresholdPositions:
    """Complementary ABOVE/BELOW positions at one ordinal line."""

    condition_id: ConditionId
    above_position_id: PositionId
    below_position_id: PositionId


@dataclass(frozen=True, slots=True)
class DirectionalPair:
    """An independently mergeable pair; amounts are six-decimal base units.

    Candidates may share inventory. Rediscover after each confirmed merge.
    """

    event_id: DirectionalEventId
    low_line: int
    high_line: int
    above_position_id: PositionId
    below_position_id: PositionId
    amount: int
    expected_pusd: int


__all__ = [
    "DecodedPositionId",
    "DirectionalBucketPositions",
    "DirectionalInstrumentKind",
    "DirectionalPair",
    "DirectionalSide",
    "DirectionalThresholdPositions",
    "ThresholdSide",
    "ThresholdSideInput",
]
