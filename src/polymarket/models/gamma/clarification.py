"""Market clarification models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.gamma.common import parse_optional_datetime
from polymarket.models.types import EventId, MarketId, QuestionId
from polymarket.types import EvmAddress, TransactionHash


class MarketClarificationState(StrEnum):
    """Lifecycle state of a clarification as it is scheduled and posted on-chain."""

    PENDING = "pending"
    QUEUED = "queued"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MarketClarification(BaseModel):
    id: int
    market_id: MarketId | None = Field(default=None, validation_alias="marketId")
    event_id: EventId | None = Field(default=None, validation_alias="eventId")
    question_id: QuestionId | None = Field(default=None, validation_alias="questionId")
    content: str | None = None
    state: MarketClarificationState | None = None
    clear_book: bool | None = Field(default=None, validation_alias="clearBook")
    notify_discord: bool | None = Field(default=None, validation_alias="notifyDiscord")
    show_in_frontend: bool | None = Field(default=None, validation_alias="showInFrontend")
    adapter_address: EvmAddress | None = Field(default=None, validation_alias="adapterAddress")
    neg_risk_request_id: str | None = Field(default=None, validation_alias="negRiskRequestId")
    tx_hash: TransactionHash | None = Field(default=None, validation_alias="txHash")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    queued_at: datetime | None = Field(default=None, validation_alias="queuedAt")
    scheduled_for: datetime | None = Field(default=None, validation_alias="scheduledFor")
    tx_timestamp: datetime | None = Field(default=None, validation_alias="txTimestamp")

    @model_validator(mode="before")
    @classmethod
    def _normalize_ids(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = dict(cast(dict[str, Any], value))
        for key in ("marketId", "eventId"):
            if data.get(key) is not None:
                data[key] = str(data[key])
        return data

    @field_validator("created_at", "queued_at", "scheduled_for", "tx_timestamp", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


__all__ = ["MarketClarification", "MarketClarificationState"]
