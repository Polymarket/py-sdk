"""Crypto market configuration catalog."""

from pydantic import Field

from polymarket.models.base import BaseModel


class CryptoMarketConfig(BaseModel):
    """A supported crypto market asset, duration, and averaging configuration."""

    id: str
    asset: str
    duration: str
    twap_enabled: bool = Field(validation_alias="twapEnabled")
    twap_lookback_seconds: int | None = Field(default=None, validation_alias="twapLookbackSeconds")


__all__ = ["CryptoMarketConfig"]
