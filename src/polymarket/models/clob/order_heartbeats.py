from typing import Literal

from pydantic import Field

from polymarket.models.base import BaseModel


class OrderHeartbeat(BaseModel):
    """Acknowledgement containing the ID to send with the next order heartbeat."""

    heartbeat_id: str = Field(min_length=1, strict=True)


class LegacyOrderHeartbeat(BaseModel):
    """Acknowledgement for a legacy order heartbeat."""

    status: Literal["ok"]


class OrderHeartbeatMismatchResponse(BaseModel):
    """Rejection carrying the currently expected order heartbeat ID."""

    error_msg: Literal["Invalid Heartbeat ID"]
    heartbeat_id: str = Field(strict=True)
