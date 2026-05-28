from __future__ import annotations

from pydantic import Field, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import EpochMsOrIsoTimestamp


class ApiKeyCreds(BaseModel):
    key: str = Field(validation_alias="apiKey")
    passphrase: str = Field(repr=False)
    secret: str = Field(repr=False)


class BuilderApiKeyInfo(BaseModel):
    key: str
    created_at: EpochMsOrIsoTimestamp = Field(default=None, validation_alias="createdAt")
    revoked_at: EpochMsOrIsoTimestamp = Field(default=None, validation_alias="revokedAt")

    @model_validator(mode="before")
    @classmethod
    def _accept_key_string(cls, value: object) -> object:
        if isinstance(value, str):
            return {"key": value}
        return value


__all__ = ["ApiKeyCreds", "BuilderApiKeyInfo"]
