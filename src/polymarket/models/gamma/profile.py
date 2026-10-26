"""Public profile models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from pydantic import Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.gamma.common import parse_optional_datetime, parse_optional_decimal
from polymarket.types import EvmAddress


class PublicProfileUser(BaseModel):
    id: str
    community_mod: bool | None = Field(default=None, validation_alias="communityMod")
    creator: bool | None = None
    mod: bool | None = None


class PublicProfile(BaseModel):
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    wallet: EvmAddress | None = Field(default=None, validation_alias="wallet")
    profile_image: str | None = Field(default=None, validation_alias="profileImage")
    display_username_public: bool | None = Field(
        default=None,
        validation_alias="displayUsernamePublic",
    )
    bio: str | None = None
    pseudonym: str | None = None
    name: str | None = None
    users: tuple[PublicProfileUser, ...] | None = None
    x_username: str | None = Field(default=None, validation_alias="xUsername")
    verified_badge: bool | None = Field(default=None, validation_alias="verifiedBadge")
    taker_tier: int | None = Field(default=None, validation_alias="takerTier")
    taker_tier_name: str | None = Field(default=None, validation_alias="takerTierName")
    weighted_volume: Decimal | None = Field(default=None, validation_alias="weightedVolume")

    @field_validator("weighted_volume", mode="before")
    @classmethod
    def _parse_weighted_volume(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize_profile(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = dict(cast(dict[str, Any], value))
        if "wallet" not in data:
            data["wallet"] = data.get("proxyWallet")
        return data

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


__all__ = ["PublicProfile", "PublicProfileUser"]
