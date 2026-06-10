"""RFQ market catalog models."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from pydantic import Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.gamma.common import parse_decimal, parse_string_sequence
from polymarket.models.types import (
    CtfConditionId,
    MarketId,
    PositionId,
    validate_ctf_condition_id,
)


class ComboMarketOutcome(BaseModel):
    """One side of a Combo market."""

    label: str
    position_id: PositionId = Field(validation_alias="positionId")
    price: Decimal

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> Decimal:
        return parse_decimal(value)


class ComboMarketOutcomes(BaseModel):
    """Binary Combo market outcomes."""

    yes: ComboMarketOutcome
    no: ComboMarketOutcome


class ComboMarket(BaseModel):
    """Market available for Combos."""

    id: MarketId
    condition_id: CtfConditionId
    slug: str
    title: str
    outcomes: ComboMarketOutcomes
    image: str
    volume: Decimal
    tags: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def _normalize_response(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = cast(dict[str, object], data)
        raw_outcomes = payload.get("outcomes")
        if not isinstance(raw_outcomes, list):
            return payload
        outcomes = cast(list[object], raw_outcomes)

        raw_position_ids = payload.get("position_ids")
        raw_prices = payload.get("outcome_prices")
        if not isinstance(raw_position_ids, list):
            raise ValueError("expected position_ids to be an array")
        position_ids = cast(list[object], raw_position_ids)
        if not isinstance(raw_prices, list):
            raise ValueError("expected outcome_prices to be an array")
        prices = cast(list[object], raw_prices)
        if len(outcomes) != 2:
            raise ValueError(f"expected binary combo market outcomes, got {len(outcomes)}")
        if len(position_ids) != len(outcomes):
            raise ValueError("expected position_ids and outcomes to have matching lengths")
        if len(prices) != len(outcomes):
            raise ValueError("expected outcome_prices and outcomes to have matching lengths")

        return {
            **payload,
            "outcomes": {
                "yes": {
                    "label": outcomes[0],
                    "positionId": position_ids[0],
                    "price": prices[0],
                },
                "no": {
                    "label": outcomes[1],
                    "positionId": position_ids[1],
                    "price": prices[1],
                },
            },
        }

    @field_validator("condition_id", mode="before")
    @classmethod
    def _parse_condition_id(cls, value: object) -> CtfConditionId:
        return validate_ctf_condition_id(value)

    @field_validator("volume", mode="before")
    @classmethod
    def _parse_volume(cls, value: object) -> Decimal:
        return parse_decimal(value)

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, value: object) -> tuple[str, ...]:
        return parse_string_sequence(value)


__all__ = ["ComboMarket", "ComboMarketOutcome", "ComboMarketOutcomes"]
