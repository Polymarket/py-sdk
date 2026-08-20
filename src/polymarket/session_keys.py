"""Scoped session-key authorization types."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NotRequired, TypedDict

from polymarket.models.clob.relayer import TransactionOutcome
from polymarket.types import EvmAddress


class SessionKeyScope(StrEnum):
    """Venue authorization attached to a session-key grant."""

    ALL = "ALL"
    """All current and future venues. Cannot be combined with another scope.

    Authorization does not imply that every venue is already available through
    session-key client actions in this SDK version.
    """

    CLOB = "CLOB"
    """Central limit order book trading."""

    COMBOSRFQ = "COMBOSRFQ"
    """Combos request-for-quote authorization.

    Session-key combo actions are not yet supported by this SDK version.
    """

    BLOCKTRADE = "BLOCKTRADE"
    """Block-trading authorization.

    The SDK does not yet expose block-trading actions.
    """


class AuthorizeSessionKeyRequest(TypedDict):
    """Reusable keyword arguments for authorizing a scoped session key."""

    address: str
    """Public EVM address of the externally managed session signer."""

    scopes: Sequence[SessionKeyScope]
    """Non-empty requested scopes. ``ALL`` must appear alone."""

    valid_until: datetime
    """Timezone-aware future expiry, normalized to UTC by the SDK."""

    idempotency_key: NotRequired[str | None]
    """Stable key to reuse when retrying the same logical authorization."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizedSessionKey:
    """Normalized request metadata after authorization transaction confirmation.

    This snapshot does not report a separate discovery or readiness status.
    """

    address: EvmAddress
    """Public EVM address of the externally managed session signer."""

    scopes: tuple[SessionKeyScope, ...]
    """Granted venue scopes in canonical enum order."""

    valid_until: datetime
    """Timezone-aware UTC expiry."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizeSessionKeyResult:
    """Result returned after the authorization transaction is confirmed."""

    operation_id: str
    """Identifier assigned to the accepted authorization operation."""

    session_key: AuthorizedSessionKey
    """Session-key metadata associated with the confirmed authorization."""

    transaction: TransactionOutcome
    """Confirmed transaction that applied the authorization."""


__all__ = [
    "AuthorizedSessionKey",
    "AuthorizeSessionKeyRequest",
    "AuthorizeSessionKeyResult",
    "SessionKeyScope",
]
