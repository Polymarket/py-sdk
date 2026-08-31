"""Protocol-version inference and protocol v2 identifier helpers."""

import re
from dataclasses import dataclass
from typing import Literal

from polymarket.errors import UserInputError
from polymarket.models.types import ClobAssetId, ConditionId, PositionId, to_condition_id

_UINT256_MAX = (1 << 256) - 1
_UINT256_BYTE_LENGTH = 32
_V2_RESERVED_BITS_MASK = ((1 << 64) - 1) << 40
_SUPPORTED_V2_MODULE_IDS = frozenset((1, 2, 3))
_POSITION_ID_PATTERN = re.compile(r"(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|[0-9]+)\Z")


@dataclass(frozen=True, slots=True)
class DecodedV2OutcomePositionId:
    condition_id: ConditionId
    outcome_index: Literal[0, 1]


def is_v2_position_id(asset_id: ClobAssetId | str) -> bool:
    """Return whether an asset occupies the protocol v2 position-ID namespace."""

    try:
        return (_parse_position_id(asset_id) & _V2_RESERVED_BITS_MASK) == 0
    except UserInputError:
        return False


def decode_v2_outcome_position_id(position_id: PositionId | str) -> DecodedV2OutcomePositionId:
    """Decode a protocol v2 YES/NO position ID."""

    value = _parse_position_id(position_id)
    encoded = f"{value:0{_UINT256_BYTE_LENGTH * 2}x}"
    module_id = int(encoded[:2], 16)
    outcome_index = int(encoded[-2:], 16)
    if module_id not in _SUPPORTED_V2_MODULE_IDS:
        raise UserInputError("Position ID must use a supported protocol v2 module")
    if outcome_index not in (0, 1):
        raise UserInputError("Protocol v2 position ID must be a YES/NO position ID")
    return DecodedV2OutcomePositionId(
        condition_id=to_condition_id(f"0x{encoded[:-2]}"),
        outcome_index=outcome_index,
    )


def _parse_position_id(position_id: str) -> int:
    raw = position_id.strip()
    if _POSITION_ID_PATTERN.fullmatch(raw) is None:
        raise UserInputError("Position ID must be a uint256 value")
    prefix = raw[:2].lower()
    base = {"0x": 16, "0b": 2, "0o": 8}.get(prefix, 10)
    value = int(raw, base)
    if value < 0 or value > _UINT256_MAX:
        raise UserInputError("Position ID must be a uint256 value")
    return value


__all__ = [
    "DecodedV2OutcomePositionId",
    "decode_v2_outcome_position_id",
    "is_v2_position_id",
]
