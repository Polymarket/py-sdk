"""Credentials for new authenticated connections when renewal fails."""

import asyncio
import time

import pytest
from _bearer import fake_access_token

from polymarket import BearerCredentials
from polymarket._internal.actions.identity import AccessTokenGrant, IssuedTokens
from polymarket._internal.auth_session import AsyncAuthSession
from polymarket._internal.streams.authentication import SocketAuthentication
from polymarket.errors import RateLimitError, RequestRejectedError, TransportError
from polymarket.types import EvmAddress

SIGNER = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"
WALLET = "0x00000000000000000000000000000000000000aa"
OTHER_WALLET = "0x00000000000000000000000000000000000000bb"


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


def test_a_connection_keeps_its_wallet_when_the_session_binds_another() -> None:
    now = int(time.time())
    opened = fake_access_token(sub=SIGNER, wallet=WALLET, exp=now + 900)
    rebound = fake_access_token(sub=SIGNER, wallet=OTHER_WALLET, exp=now + 900)
    sent: list[str] = []

    async def refresh(_: BearerCredentials) -> IssuedTokens:
        raise AssertionError("No renewal is due.")

    async def authenticate(access_token: str) -> None:
        sent.append(access_token)

    async def bind(_: str) -> AccessTokenGrant:
        return AccessTokenGrant(access_token=rebound, expires_in=900)

    async def run() -> None:
        session = AsyncAuthSession(
            credentials=BearerCredentials(access_token=opened, refresh_token="refresh"),
            expires_in=900,
            refresh=refresh,
        )
        authentication = SocketAuthentication(
            session=session,
            authenticate=authenticate,
            expired=lambda: None,
            fail=lambda _: None,
        )
        try:
            authentication.accepted((await authentication.prepare()).access_token)
            await session.bind_wallet(EvmAddress(OTHER_WALLET), bind)
            # A late acknowledgement of the first token, then the queued work runs.
            authentication.accepted(opened)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            # A reconnect needs a token for the connection's own wallet.
            with pytest.raises(TransportError, match="another wallet"):
                await authentication.prepare()
        finally:
            authentication.stop()
            session.close()

    asyncio.run(run())

    assert sent == []
