from decimal import Decimal

from pydantic import Field

from polymarket.models.base import BaseModel


class RateLimitTierDetails(BaseModel):
    name: str | None = None
    volume_threshold: int | None = Field(default=None, strict=True)
    cancel_rate_per_sec: int | None = Field(default=None, strict=True)
    order_rate_per_sec: int | None = Field(default=None, strict=True)
    order_burst: int | None = Field(default=None, strict=True)
    cancel_burst: int | None = Field(default=None, strict=True)
    allow_negative: bool | None = Field(default=None, strict=True)


class RateLimitTier(BaseModel):
    tier: str
    usdc_volume: Decimal | None = None
    next_tier_threshold: int | None = Field(default=None, strict=True)
    period: int = Field(strict=True)
    tier_details: RateLimitTierDetails


__all__ = ["RateLimitTier", "RateLimitTierDetails"]
