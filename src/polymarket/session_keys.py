"""Scoped session-key authorization types."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NotRequired, TypeAlias, TypedDict

from polymarket.models.clob.relayer import TransactionOutcome
from polymarket.types import EvmAddress


class SessionKeyKnownScope(StrEnum):
    """Known venue authorizations attached to session-key grants.

    Session-key authorization also accepts newer scopes as plain strings; see
    :data:`SessionKeyScope`.
    """

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


SessionKeyScope: TypeAlias = SessionKeyKnownScope | str
"""A session-key scope.

Known scopes are enumerated in :class:`SessionKeyKnownScope`. Newly introduced
scopes remain usable as plain strings before an SDK release enumerates them.
"""


class AuthorizeSessionKeyRequest(TypedDict):
    """Reusable keyword arguments for authorizing a scoped session key."""

    address: str
    """Public EVM address of the externally managed session signer."""

    scopes: Sequence[SessionKeyScope]
    """Non-empty requested scopes. Newer scopes may be strings; ``ALL`` must appear alone."""

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
    """Granted venue scopes, including newer values not yet known to this SDK."""

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
    "SessionKeyKnownScope",
    "SessionKeyScope",
]
