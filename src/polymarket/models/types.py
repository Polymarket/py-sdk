"""Model-specific Polymarket domain types."""

from typing import Literal, NewType, TypeAlias

OrderSide: TypeAlias = Literal["BUY", "SELL"]

ApiKey = NewType("ApiKey", str)
BestLineId = NewType("BestLineId", str)
CategoryId = NewType("CategoryId", str)
ChatId = NewType("ChatId", str)
ClobRewardId = NewType("ClobRewardId", str)
CollectionId = NewType("CollectionId", str)
CommentId = NewType("CommentId", str)
ComboActivityId = NewType("ComboActivityId", str)
ComboConditionId = NewType("ComboConditionId", str)
ConditionId = NewType("ConditionId", str)
CtfConditionId = ConditionId
"""Deprecated alias for ConditionId. Use ConditionId for new code."""
EventCreatorId = NewType("EventCreatorId", str)
EventExternalPartnerMappingId = NewType("EventExternalPartnerMappingId", int)
EventId = NewType("EventId", str)
ImageOptimizationId = NewType("ImageOptimizationId", str)
InternalUserId = NewType("InternalUserId", str)
MarketId = NewType("MarketId", str)
OrderId = NewType("OrderId", str)
PartnerId = NewType("PartnerId", int)
PositionId = NewType("PositionId", str)
QuestionId = NewType("QuestionId", str)
ResolutionRequestId = NewType("ResolutionRequestId", str)
SeriesId = NewType("SeriesId", str)
SportId = NewType("SportId", int)
TagId = NewType("TagId", str)
TeamId = NewType("TeamId", int)
TemplateId = NewType("TemplateId", str)
TokenId = NewType("TokenId", str)
ClobAssetId: TypeAlias = TokenId | PositionId


def to_condition_id(value: str) -> ConditionId:
    if not _is_hex_string(value) or len(value) not in (64, 66):
        raise TypeError(f"Expected a 31-byte or 32-byte hex string, received: {value}")
    return ConditionId(value)


def to_ctf_condition_id(value: str) -> CtfConditionId:
    """Deprecated alias for :func:`to_condition_id`."""

    return to_condition_id(value)


def to_combo_condition_id(value: str) -> ComboConditionId:
    if not _is_hex_string(value):
        raise TypeError(f"Expected a protocol v2 combo condition ID, received: {value}")

    normalized = value.lower()
    if len(normalized) == 64 and normalized.startswith("0x03"):
        return ComboConditionId(normalized)
    if (
        len(normalized) == 66
        and normalized.startswith("0x03")
        and normalized.endswith(("00", "01"))
    ):
        return ComboConditionId(normalized[:-2])

    raise TypeError(f"Expected a protocol v2 combo condition ID, received: {value}")


def validate_condition_id(value: object) -> ConditionId:
    if not isinstance(value, str):
        raise ValueError(f"Expected a 31-byte or 32-byte hex string, received: {value}")
    try:
        return to_condition_id(value)
    except TypeError as error:
        raise ValueError(str(error)) from error


def validate_optional_condition_id(value: object) -> ConditionId | None:
    if value is None:
        return None
    return validate_condition_id(value)


def validate_condition_id_response(value: object) -> ConditionId:
    """Validate a condition ID returned by an API without inferring its protocol."""

    if not isinstance(value, str) or not _is_hex_string(value):
        raise ValueError(f"Expected a hex condition ID, received: {value}")
    return ConditionId(value)


def validate_optional_condition_id_response(value: object) -> ConditionId | None:
    if value is None:
        return None
    return validate_condition_id_response(value)


def validate_ctf_condition_id(value: object) -> CtfConditionId:
    """Deprecated alias for :func:`validate_condition_id`."""

    return validate_condition_id(value)


def validate_optional_ctf_condition_id(value: object) -> CtfConditionId | None:
    """Deprecated alias for :func:`validate_optional_condition_id`."""

    return validate_optional_condition_id(value)


def validate_combo_condition_id(value: object) -> ComboConditionId:
    if not isinstance(value, str):
        raise ValueError(f"Expected a protocol v2 combo condition ID, received: {value}")
    try:
        return to_combo_condition_id(value)
    except TypeError as error:
        raise ValueError(str(error)) from error


def validate_optional_combo_condition_id(value: object) -> ComboConditionId | None:
    if value is None:
        return None
    return validate_combo_condition_id(value)


def _is_hex_string(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
    except ValueError:
        return False
    return True


__all__ = [
    "ApiKey",
    "BestLineId",
    "CategoryId",
    "ChatId",
    "ClobRewardId",
    "CollectionId",
    "CommentId",
    "ComboActivityId",
    "ComboConditionId",
    "ClobAssetId",
    "ConditionId",
    "CtfConditionId",
    "EventCreatorId",
    "EventExternalPartnerMappingId",
    "EventId",
    "ImageOptimizationId",
    "InternalUserId",
    "MarketId",
    "OrderId",
    "OrderSide",
    "PartnerId",
    "PositionId",
    "QuestionId",
    "ResolutionRequestId",
    "SeriesId",
    "SportId",
    "TagId",
    "TeamId",
    "TemplateId",
    "TokenId",
    "to_combo_condition_id",
    "to_condition_id",
    "to_ctf_condition_id",
    "validate_combo_condition_id",
    "validate_condition_id",
    "validate_condition_id_response",
    "validate_ctf_condition_id",
    "validate_optional_combo_condition_id",
    "validate_optional_condition_id",
    "validate_optional_condition_id_response",
    "validate_optional_ctf_condition_id",
]
