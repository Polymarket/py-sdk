from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Self, cast

from pydantic import Field, field_validator

from polymarket.errors import UnexpectedResponseError
from polymarket.models.base import BaseModel
from polymarket.models.data.common import (
    ResolutionMarketType,
    ResolutionReporter,
    ResolutionSource,
    ResolutionStatus,
    datetime_from_epoch_or_iso,
    decimal_from_number,
    optional_decimal_from_number,
    optional_text,
)
from polymarket.models.types import (
    ConditionId,
    QuestionId,
    validate_optional_condition_id_response,
)
from polymarket.types import TransactionHash


class Resolution(BaseModel):
    """Resolution lifecycle and per-outcome payouts in USDC per share."""

    question_id: QuestionId | None = None
    condition_id: ConditionId | None = None
    status: ResolutionStatus
    extended_review: bool
    was_disputed: bool
    question_rules_updated: bool = Field(validation_alias="new_version_q")
    proposed_price: Decimal | None = None
    reproposed_price: Decimal | None = None
    price: Decimal | None = None
    transaction_hash: TransactionHash | None = None
    log_index: int | None = None
    last_updated_at: datetime = Field(validation_alias="last_update_timestamp")
    market_type: ResolutionMarketType | None = None
    payouts: tuple[Decimal, Decimal] | None = None
    resolution_source: ResolutionSource | None = None
    reporter: ResolutionReporter | None = None
    was_arbitrated: bool | None = None
    resolved_block: int | None = None
    resolved_at: datetime | None = None

    _validate_optional_condition_id_response = field_validator("condition_id", mode="before")(
        validate_optional_condition_id_response
    )

    _optional_decimal_from_number = field_validator(
        "proposed_price", "reproposed_price", "price", mode="before"
    )(optional_decimal_from_number)

    _optional_text = field_validator("transaction_hash", "log_index", mode="before")(optional_text)

    _datetime_from_epoch_or_iso = field_validator("last_updated_at", mode="before")(
        datetime_from_epoch_or_iso
    )

    @field_validator("proposed_price", "reproposed_price", "price", mode="before")
    @classmethod
    def _unset_price(cls, value: object) -> object:
        return None if value in ("69", 69) else value

    @classmethod
    def parse_response(cls, data: object) -> Self:
        if not isinstance(data, dict):
            return super().parse_response(data)
        response = dict(cast(dict[str, object], data))
        if "payouts" in response:
            try:
                response["payouts"] = _parse_payouts_e6(response["payouts"])
            except ValueError as error:
                raise UnexpectedResponseError(
                    f"{cls.__name__} response did not match expected shape"
                ) from error
        return super().parse_response(response)


def _parse_payouts_e6(value: object) -> tuple[Decimal, Decimal] | None:
    if value is None:
        return None
    if not isinstance(value, list | tuple):
        raise ValueError("Expected a payout pair")
    items = cast(list[object] | tuple[object, ...], value)
    if len(items) != 2:
        raise ValueError("Expected a payout pair")
    amounts = tuple(decimal_from_number(item) for item in items)
    if not all(amount.is_finite() for amount in amounts):
        raise ValueError("Expected finite payouts")
    return amounts[0] / 1_000_000, amounts[1] / 1_000_000


__all__ = ["Resolution"]
