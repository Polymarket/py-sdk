from __future__ import annotations

from pydantic import Field

from polymarket.models.base import BaseModel


class ApiKeyCreds(BaseModel):
    key: str = Field(validation_alias="apiKey", repr=False)
    passphrase: str = Field(repr=False)
    secret: str = Field(repr=False)

    def __repr__(self) -> str:
        return "ApiKeyCreds(key=<redacted>, passphrase=<redacted>, secret=<redacted>)"

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card

        return card(
            "ApiKeyCreds  ·  redacted",
            rows=[("key", "***"), ("passphrase", "***"), ("secret", "***")],
        )


__all__ = ["ApiKeyCreds"]
