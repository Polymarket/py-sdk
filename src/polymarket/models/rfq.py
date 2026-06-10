from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from pydantic import field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.types import (
    ComboConditionId,
    MarketId,
    PositionId,
)


class ComboMarketOutcome(BaseModel):
    """One outcome in a Combo market catalog entry."""

    label: str
    position_id: PositionId
    price: Decimal

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> Decimal:
        return _parse_decimal(value)


class ComboMarketOutcomes(BaseModel):
    """Binary Combo market outcomes."""

    yes: ComboMarketOutcome
    no: ComboMarketOutcome


class ComboMarket(BaseModel):
    """A market available for Combos."""

    id: MarketId
    condition_id: ComboConditionId
    slug: str
    title: str
    outcomes: ComboMarketOutcomes
    image: str
    volume: float
    tags: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def _normalize_combo_market(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = cast(dict[str, Any], value)
        if "outcomes" in data and isinstance(data.get("outcomes"), dict):
            return data

        outcomes = _parse_string_sequence(data.get("outcomes"))
        position_ids = _parse_string_sequence(data.get("position_ids"))
        outcome_prices = tuple(
            _parse_decimal(item) for item in _parse_sequence(data.get("outcome_prices"))
        )

        if len(outcomes) != 2:
            msg = f"Expected binary combo market outcomes, received {len(outcomes)}"
            raise ValueError(msg)
        if len(position_ids) != len(outcomes):
            msg = "Expected position_ids and outcomes to have matching lengths."
            raise ValueError(msg)
        if len(outcome_prices) != len(outcomes):
            msg = "Expected outcome_prices and outcomes to have matching lengths."
            raise ValueError(msg)

        return {
            "id": data.get("id"),
            "condition_id": data.get("condition_id"),
            "slug": data.get("slug"),
            "title": data.get("title"),
            "outcomes": {
                "yes": {
                    "label": outcomes[0],
                    "position_id": position_ids[0],
                    "price": outcome_prices[0],
                },
                "no": {
                    "label": outcomes[1],
                    "position_id": position_ids[1],
                    "price": outcome_prices[1],
                },
            },
            "image": data.get("image"),
            "volume": data.get("volume"),
            "tags": data.get("tags"),
        }

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: object) -> object:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return str(value)
        return value

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ComboConditionId:
        if not isinstance(value, str):
            msg = f"Expected a Combo condition ID string, received: {value}"
            raise ValueError(msg)
        return ComboConditionId(value)


def _parse_sequence(value: object) -> tuple[Any, ...]:
    if value is None:
        return ()

    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            msg = "expected a JSON array"
            raise ValueError(msg)
        return tuple(cast(list[Any], parsed))

    if isinstance(value, list | tuple):
        return tuple(cast(list[Any] | tuple[Any, ...], value))

    msg = "expected a sequence"
    raise ValueError(msg)


def _parse_string_sequence(value: object) -> tuple[str, ...]:
    items = _parse_sequence(value)
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            msg = f"expected a string, got {type(item).__name__}"
            raise ValueError(msg)
        result.append(item)
    return tuple(result)


def _parse_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        msg = f"invalid decimal: {value!r}"
        raise ValueError(msg) from error


__all__ = ["ComboMarket", "ComboMarketOutcome", "ComboMarketOutcomes"]
