from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias, cast
from urllib.parse import urlsplit

from eth_utils.address import to_checksum_address

from polymarket.errors import UserInputError
from polymarket.types import EvmAddress


@dataclass(frozen=True, slots=True, kw_only=True)
class BearerCredentials:
    """Complete session credentials. Store both values after every refresh."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value and not any(c.isspace() for c in value)  # pyright: ignore[reportUnnecessaryIsInstance]
            for value in (self.access_token, self.refresh_token)
        ):
            raise UserInputError("Bearer credentials require non-empty token strings")

    def __repr__(self) -> str:
        return "BearerCredentials(access_token=<redacted>, refresh_token=<redacted>)"


@dataclass(frozen=True, slots=True, kw_only=True)
class PlatformApiKey:
    """Server-held application attribution key. Never place it in browser configuration."""

    key: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key or any(c.isspace() for c in self.key):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise UserInputError("Platform API Key must be a non-empty key without whitespace")

    def __repr__(self) -> str:
        return "PlatformApiKey(key=<redacted>)"


@dataclass(frozen=True, slots=True, kw_only=True)
class RemotePlatformApiKey:
    """Challenge-only proxy configuration; contains no application secret.

    Python requires an absolute HTTP(S) URL. The URL is the complete endpoint;
    no path is appended. Login, refresh and logout go directly to the gateway.
    """

    url: str

    def __post_init__(self) -> None:
        try:
            parsed = urlsplit(self.url)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise UserInputError(
                "Challenge proxy URL must be absolute HTTP(S), without userinfo or fragment"
            ) from None


@dataclass(frozen=True, slots=True)
class BuilderApiKey:
    key: str = field(repr=False)
    secret: str = field(repr=False)
    passphrase: str = field(repr=False)

    def __repr__(self) -> str:
        return "BuilderApiKey(key=<redacted>, secret=<redacted>, passphrase=<redacted>)"

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card

        return card(
            "BuilderApiKey  ·  redacted",
            rows=[("key", "***"), ("secret", "***"), ("passphrase", "***")],
        )


@dataclass(frozen=True, slots=True)
class RelayerApiKey:
    key: str = field(repr=False)
    address: EvmAddress

    def __init__(self, *, key: str, address: str) -> None:
        try:
            normalized = cast(EvmAddress, to_checksum_address(address))
        except ValueError as error:
            raise UserInputError(f"Invalid relayer address: {error}") from error
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "address", normalized)

    def __repr__(self) -> str:
        return f"RelayerApiKey(key=<redacted>, address={self.address!r})"

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card

        return card(
            f"RelayerApiKey  ·  {self.address}",
            rows=[("key", "***"), ("address", self.address)],
        )


ApiKey: TypeAlias = BuilderApiKey | RelayerApiKey


__all__ = [
    "BearerCredentials",
    "ApiKey",
    "BuilderApiKey",
    "RelayerApiKey",
    "PlatformApiKey",
    "RemotePlatformApiKey",
]
