from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TypeAlias, cast

from eth_utils.address import to_checksum_address

from polymarket.errors import UserInputError
from polymarket.types import EvmAddress


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


@dataclass(frozen=True, slots=True)
class PlatformApiKey:
    """An application's Platform API Key.

    It identifies the application on sign-in and on every request the client
    sends, and is bound to the sessions it opens. Keep it on the server: never
    ship it to browsers or other untrusted clients.
    """

    key: str = field(repr=False)

    def __init__(self, key: str) -> None:
        if not isinstance(key, str) or _PRINTABLE_ASCII.fullmatch(key) is None:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise UserInputError("Platform API Key must be non-empty printable ASCII.")
        object.__setattr__(self, "key", key)

    def __repr__(self) -> str:
        return "PlatformApiKey(key=<redacted>)"

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card

        return card("PlatformApiKey  ·  redacted", rows=[("key", "***")])


_PRINTABLE_ASCII = re.compile(r"[\x21-\x7e]+")


@dataclass(frozen=True, slots=True, kw_only=True)
class BearerCredentials:
    """Session credentials for a secure client.

    Both tokens are secrets. Store them securely to restore the session later
    without a new wallet signature.
    """

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)

    def __repr__(self) -> str:
        return "BearerCredentials(access_token=<redacted>, refresh_token=<redacted>)"

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card

        return card(
            "BearerCredentials  ·  redacted",
            rows=[("access_token", "***"), ("refresh_token", "***")],
        )


__all__ = ["ApiKey", "BearerCredentials", "BuilderApiKey", "PlatformApiKey", "RelayerApiKey"]
