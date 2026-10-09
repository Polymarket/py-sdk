"""Reference and settlement metadata for outcome assets."""

import re
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.data.common import optional_decimal_from_number
from polymarket.models.types import ClobAssetId, ConditionId, EventId, TokenId


class TokenModule(StrEnum):
    """Contract family that issued an outcome asset."""

    V1_CTF = "v1_ctf"
    BINARY = "binary"
    NEG_RISK = "neg_risk"
    COMBO = "combo"


class TokenReference(BaseModel):
    """Outcome asset reference facts and settlement metadata.

    Nullable fields are always present. Outcome labels and settlement metadata
    may lag by up to a minute. The market's order-book slot can differ from the
    on-chain outcome slot. ``event_id`` selects the lowest associated event ID.
    """

    asset_id: ClobAssetId = Field(validation_alias="token_id")
    condition_id: ConditionId
    structural_condition_id: ConditionId | None
    module: TokenModule
    outcome_index: int = Field(strict=True, ge=-32768, le=32767)
    clob_index: int | None = Field(strict=True, ge=-32768, le=32767)
    outcome: str | None = Field(strict=True)
    opposite_asset_id: ClobAssetId | None = Field(validation_alias="opposite_token_id")
    resolved: bool = Field(strict=True)
    final_price: Decimal | None
    title: str | None = Field(strict=True)
    market_slug: str | None = Field(strict=True)
    closed: bool | None = Field(strict=True)
    neg_risk: bool | None = Field(strict=True)
    neg_risk_market_id: ConditionId | None
    question_index: int | None = Field(strict=True, ge=-2147483648, le=2147483647)
    event_id: EventId | None
    event_slug: str | None = Field(strict=True)

    @field_validator("asset_id", "opposite_asset_id", mode="before")
    @classmethod
    def _parse_asset(cls, value: object) -> ClobAssetId | None:
        if value is None:
            return None
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,78}", value) is None:
            raise ValueError("Expected a decimal outcome asset ID")
        return TokenId(value)

    @field_validator("condition_id", "structural_condition_id", "neg_risk_market_id", mode="before")
    @classmethod
    def _parse_condition(cls, value: object) -> ConditionId | None:
        if value is None:
            return None
        if not isinstance(value, str) or re.fullmatch(r"0x[0-9a-fA-F]{64}", value) is None:
            raise ValueError("Expected a 32-byte hex condition ID")
        return ConditionId(value)

    @field_validator("event_id", mode="before")
    @classmethod
    def _parse_event(cls, value: object) -> EventId | None:
        if value is None:
            return None
        if type(value) is int:
            integer = value
        elif isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value) is not None:
            # Accept the canonical string value when round-tripping an SDK model.
            integer = int(value)
        else:
            raise ValueError("Expected an integer event ID")
        if not -2147483648 <= integer <= 2147483647:
            raise ValueError("Expected a 32-bit event ID")
        return EventId(str(integer))

    @field_validator("final_price", mode="before")
    @classmethod
    def _parse_final_price(cls, value: object) -> Decimal | None:
        decimal = optional_decimal_from_number(value)
        if decimal is None:
            return None
        if not decimal.is_finite():
            raise ValueError("Expected a finite payout rate")
        return decimal


__all__ = ["TokenModule", "TokenReference"]
