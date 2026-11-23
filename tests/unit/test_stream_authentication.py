"""Credentials for new authenticated connections when renewal fails."""

import asyncio
import time

import pytest
from _bearer import fake_access_token

from polymarket import BearerCredentials
from polymarket._internal.actions.identity import IssuedTokens
from polymarket._internal.auth_session import AsyncAuthSession
from polymarket._internal.streams.authentication import SocketAuthentication
from polymarket.errors import RateLimitError, RequestRejectedError, TransportError

SIGNER = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"


def _prepare_with_failing_renewal(error: Exception) -> BaseException | None:
    async def refresh(_: BearerCredentials) -> IssuedTokens:
        raise error

    async def authenticate(_: str) -> None:
        return None

    async def run() -> BaseException | None:
        # The saved access token has expired, so a new connection needs a renewal.
        expired = fake_access_token(sub=SIGNER, exp=int(time.time()) - 60)
        session = AsyncAuthSession(
            credentials=BearerCredentials(access_token=expired, refresh_token="refresh"),
            expires_in=None,
            refresh=refresh,
        )
        authentication = SocketAuthentication(
            session=session,
            authenticate=authenticate,
            expired=lambda: None,
            fail=lambda _: None,
        )
        try:
            with pytest.raises(Exception) as raised:
                await authentication.prepare()
            return raised.value
        finally:
            session.close()

    return asyncio.run(run())


def test_a_renewal_that_fails_for_now_lets_the_connection_retry() -> None:
    error = _prepare_with_failing_renewal(RateLimitError("rate limited", retry_after=60))

    assert isinstance(error, TransportError)


def test_a_rejected_renewal_still_ends_the_connection() -> None:
    error = _prepare_with_failing_renewal(
        RequestRejectedError("rejected", status=401, code="invalid_refresh_token")
    )

    assert isinstance(error, RequestRejectedError)
    assert error.code == "invalid_refresh_token"
