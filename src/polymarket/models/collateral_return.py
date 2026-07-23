from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    _DecimalFromE6String,  # pyright: ignore[reportPrivateUsage]
    _DecimalFromString,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.types import (
    ComboConditionId,
    PositionId,
    validate_optional_combo_condition_id,
)
from polymarket.types import EvmAddress, HexString


class CollateralReturnOperationKind(StrEnum):
    """Known operation kinds in a collateral return plan.

    Plans may include kinds not listed here; ``CollateralReturnOperation.kind``
    falls back to a plain string for unknown kinds so newer plans keep parsing.
    """

    SPLIT = "split"
    MERGE = "merge"
    REDEEM = "redeem"
    SPLIT_ON_CONDITION = "split_on_condition"
    MERGE_ON_CONDITION = "merge_on_condition"
    SPLIT_ON_EVENT = "split_on_event"
    MERGE_ON_EVENT = "merge_on_event"
    CONVERT_ON_EVENT = "convert_on_event"
    EXTRACT = "extract"
    INJECT = "inject"
    CONVERT_TO_YES_BASKET = "convert_to_yes_basket"
    MERGE_FROM_YES_BASKET = "merge_from_yes_basket"
    COMPRESS = "compress"


class CollateralReturnOperation(BaseModel):
    """One position operation a collateral return plan performs."""

    kind: CollateralReturnOperationKind | str
    condition_id: ComboConditionId | None = None
    event_id: HexString | None = None
    position_id: PositionId | None = None
    condition_index: int = 0
    amount: _DecimalFromE6String

    @field_validator("kind", mode="before")
    @classmethod
    def _coerce_known_kind(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return CollateralReturnOperationKind(value)
            except ValueError:
                return value
        return value

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ComboConditionId | None:
        return validate_optional_combo_condition_id(value)


class CollateralReturnPositionAmount(BaseModel):
    """A position and the amount of it a plan touches."""

    position_id: PositionId
    amount: _DecimalFromE6String


class CollateralReturnPositionSummary(BaseModel):
    """Net position impact of executing a collateral return plan."""

    consumed: tuple[CollateralReturnPositionAmount, ...] = ()
    created: tuple[CollateralReturnPositionAmount, ...] = ()


class CollateralReturnRouterCall(BaseModel):
    """The exact on-chain call that executes a collateral return plan."""

    to: EvmAddress
    data: HexString


class CollateralReturnPlan(BaseModel):
    """An executable plan that returns redundant position value as collateral.

    The plan is an inspectable artifact: review ``collateral_returned`` and
    ``position_summary`` before executing it with
    ``execute_collateral_return_plan``. Execution submits ``router_call``
    exactly as planned; nothing is recomputed client-side.

    When ``truncated`` is True the plan covers only one executable chunk.
    Execute it, wait for the transaction to confirm, then request a fresh plan
    for the remainder.
    """

    plan_hash: HexString
    wallet: EvmAddress
    chain_id: int
    block_number: int
    starting_collateral: _DecimalFromString = Field(validation_alias="starting_pusd")
    collateral_returned: _DecimalFromString = Field(validation_alias="net_pusd_out")
    final_collateral: _DecimalFromString = Field(validation_alias="final_pusd")
    required_collateral: _DecimalFromString = Field(validation_alias="required_pusd_input")
    required_positions: tuple[CollateralReturnPositionAmount, ...] = ()
    position_summary: CollateralReturnPositionSummary = Field(
        default_factory=CollateralReturnPositionSummary
    )
    operations: tuple[CollateralReturnOperation, ...] = ()
    truncated: bool = False
    router_call: CollateralReturnRouterCall


__all__ = [
    "CollateralReturnOperation",
    "CollateralReturnOperationKind",
    "CollateralReturnPlan",
    "CollateralReturnPositionAmount",
    "CollateralReturnPositionSummary",
    "CollateralReturnRouterCall",
]
