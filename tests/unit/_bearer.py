"""Offline session credentials for building secure clients in tests."""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import Awaitable, Callable

from eth_account import Account

from polymarket import BearerCredentials
from polymarket._internal.actions.identity import IssuedTokens
from polymarket._internal.auth_session import AsyncAuthSession

TEST_TRADING_IDENTITY = "test-key"


def fake_access_token(**claims: object) -> str:
    """Build an unsigned access token carrying ``claims``. ``None`` claims are omitted."""

    def segment(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    payload = {name: value for name, value in claims.items() if value is not None}
    # A unique identifier keeps tokens issued within the same second distinct.
    payload.setdefault("jti", uuid.uuid4().hex)
    return f"{segment({'alg': 'none', 'typ': 'JWT'})}.{segment(payload)}.signature"


def bearer_credentials_for(
    private_key: str,
    *,
    wallet: str | None = None,
    clob_api_key: str | None = TEST_TRADING_IDENTITY,
    client_id: str | None = None,
    expires_in: int = 3600,
    refresh_token: str = "test-refresh-token",
) -> BearerCredentials:
    """Session credentials whose access token belongs to the signer of ``private_key``."""
    signer = Account.from_key(private_key).address
    return BearerCredentials(
        access_token=fake_access_token(
            sub=signer,
            wallet=wallet,
            clob_api_key=clob_api_key,
            client_id=client_id,
            exp=int(time.time()) + expires_in,
        ),
        refresh_token=refresh_token,
    )


def async_test_session(
    private_key: str = "0x" + "11" * 32,
    *,
    expires_in: int = 3600,
    renew: Callable[[BearerCredentials], Awaitable[IssuedTokens]] | None = None,
) -> AsyncAuthSession:
    """An offline session. Renewal issues fresh tokens for the same identity unless overridden."""

    async def issue_fresh(current: BearerCredentials) -> IssuedTokens:
        renewed = bearer_credentials_for(
            private_key, expires_in=3600, refresh_token=current.refresh_token
        )
        return IssuedTokens(
            access_token=renewed.access_token,
            refresh_token=renewed.refresh_token,
            expires_in=3600,
        )

    return AsyncAuthSession(
        credentials=bearer_credentials_for(private_key, expires_in=expires_in),
        expires_in=expires_in,
        refresh=renew or issue_fresh,
    )
