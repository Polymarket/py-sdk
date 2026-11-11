from __future__ import annotations

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


__all__ = ["ApiKey", "BearerCredentials", "BuilderApiKey", "RelayerApiKey"]
