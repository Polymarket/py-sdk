"""Bearer session lifecycle: renewal, recovery, wallet binding, and logout.

One session owns token adoption, renewal scheduling, and change notification
for a secure client. Renewal starts shortly before the access token expires and
is scheduled from the lifetime the server returns, not from the local clock.
Concurrent consumers share one renewal. Transient failures keep the session and
retry with backoff; only a definite rejection or an invalid renewal ends it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from typing import Protocol

from polymarket._internal.actions.identity import (
    AccessTokenClaims,
    AccessTokenGrant,
    IssuedTokens,
    parse_access_token_claims,
    parse_issued_claims,
    same_session_identity,
)
from polymarket.auth import BearerCredentials
from polymarket.errors import (
    RateLimitError,
    RequestRejectedError,
    TransportError,
    UnexpectedResponseError,
)
from polymarket.types import EvmAddress

CredentialsChanged = Callable[[BearerCredentials], None]
Clock = Callable[[], float]

# Renewal starts this long before the access token expires.
RENEWAL_LEAD_SECONDS = 30.0
# Upper bound for the backoff between renewals after transient failures.
MAX_RETRY_DELAY_SECONDS = 30.0
_RENEWAL_ATTEMPTS = 3
# A longer server-requested delay is left to the session retry timer.
_MAX_INLINE_RETRY_AFTER_SECONDS = 5.0

_CLOSED_MESSAGE = "The authenticated session is closed."
_STOPPED_MESSAGE = "Session renewal stopped."


def is_transient_renewal_failure(error: BaseException) -> bool:
    """Failures that leave the refresh session usable once the cause clears."""
    return isinstance(error, TransportError | RateLimitError) or (
        isinstance(error, RequestRejectedError) and error.status >= 500
    )


def _retry_after_seconds(error: BaseException) -> float | None:
    if isinstance(error, RateLimitError | RequestRejectedError):
        return error.retry_after
    return None


def _attempt_delay(attempt: int, error: BaseException) -> float:
    return max(0.25 * 2**attempt, _retry_after_seconds(error) or 0.0)


def _retry_delay(retries: int, error: BaseException) -> float:
    backoff = min(MAX_RETRY_DELAY_SECONDS, 1.0 * 2 ** (retries - 1))
    return max(backoff, _retry_after_seconds(error) or 0.0)


def _inline_retry_allowed(attempt: int, error: BaseException) -> bool:
    if not is_transient_renewal_failure(error) or attempt == _RENEWAL_ATTEMPTS - 1:
        return False
    retry_after = _retry_after_seconds(error)
    return retry_after is None or retry_after <= _MAX_INLINE_RETRY_AFTER_SECONDS


class _SessionState:
    """Token state and the policy checks shared by the sync and async sessions."""

    def __init__(
        self, *, credentials: BearerCredentials, expires_in: int | None, clock: Clock
    ) -> None:
        self.clock = clock
        self.credentials = credentials
        self.claims = parse_access_token_claims(credentials.access_token)
        # Token ``exp`` minus the local expiry derived from ``expires_in``, in
        # seconds. It absorbs the difference between the local and server clocks.
        self.clock_offset = 0.0
        if expires_in is not None:
            self.clock_offset = self._clock_offset(self.claims, expires_in)
        self.retries = 0
        self.failure: BaseException | None = None
        self.closed = False

    def expires_at(self, access_token: str) -> float:
        claims = (
            self.claims
            if access_token == self.credentials.access_token
            else parse_access_token_claims(access_token)
        )
        return claims.exp - self.clock_offset

    def remaining(self) -> float:
        return self.expires_at(self.credentials.access_token) - self.clock()

    def renewal_delay(self) -> float:
        return max(0.0, self.remaining() - RENEWAL_LEAD_SECONDS)

    def assert_active(self) -> None:
        if self.closed:
            raise TransportError(_CLOSED_MESSAGE)
        if self.failure is not None:
            raise self.failure

    def adopt_renewal(self, tokens: IssuedTokens) -> None:
        claims = parse_issued_claims(tokens.access_token)
        if tokens.expires_in <= RENEWAL_LEAD_SECONDS or not same_session_identity(
            self.claims, claims
        ):
            raise UnexpectedResponseError(
                "Session renewal returned a different identity or an unusable expiry."
            )
        self._adopt(tokens.credentials, claims, tokens.expires_in)

    def adopt_wallet_binding(self, grant: AccessTokenGrant, wallet: EvmAddress) -> None:
        claims = parse_issued_claims(grant.access_token)
        if (
            grant.expires_in <= RENEWAL_LEAD_SECONDS
            or claims.sub.lower() != self.claims.sub.lower()
            or claims.client_id != self.claims.client_id
            or claims.wallet is None
            or claims.wallet.lower() != wallet.lower()
        ):
            raise UnexpectedResponseError(
                "The wallet binding returned a different session identity."
            )
        self._adopt(
            BearerCredentials(
                access_token=grant.access_token,
                refresh_token=self.credentials.refresh_token,
            ),
            claims,
            grant.expires_in,
        )

    def _adopt(
        self, credentials: BearerCredentials, claims: AccessTokenClaims, expires_in: int
    ) -> None:
        self.credentials = credentials
        self.claims = claims
        self.clock_offset = self._clock_offset(claims, expires_in)
        self.retries = 0

    def _clock_offset(self, claims: AccessTokenClaims, expires_in: int) -> float:
        return claims.exp - (self.clock() + expires_in)


def _renewal_for_revocation(identity: AccessTokenClaims, tokens: IssuedTokens) -> BearerCredentials:
    if not same_session_identity(identity, parse_issued_claims(tokens.access_token)):
        raise UnexpectedResponseError("Logout renewal returned a different session identity.")
    return tokens.credentials


def _is_expired_access_token(error: BaseException) -> bool:
    return (
        isinstance(error, RequestRejectedError)
        and error.status == 401
        and error.code == "expired_access_token"
    )


class TimerHandle(Protocol):
    def cancel(self) -> None: ...


class _TimerHandle:
    def __init__(self, delay: float, callback: Callable[[], None]) -> None:
        self._timer = threading.Timer(delay, callback)
        # A pending renewal must never keep the interpreter alive on its own.
        self._timer.daemon = True
        self._timer.start()

    def cancel(self) -> None:
        self._timer.cancel()


TimerFactory = Callable[[float, Callable[[], None]], TimerHandle]


class SyncAuthSession:
    """Bearer session for the synchronous client.

    A daemon timer renews the session in the background, so an idle client keeps
    its session while the process runs. Requests also check expiry before they
    are sent, which covers suspended or forked processes.
    """

    def __init__(
        self,
        *,
        credentials: BearerCredentials,
        expires_in: int | None,
        refresh: Callable[[BearerCredentials], IssuedTokens],
        on_credentials_changed: CredentialsChanged | None = None,
        logger: logging.Logger | None = None,
        clock: Clock = time.time,
        timer_factory: TimerFactory = _TimerHandle,
    ) -> None:
        self._state = _SessionState(credentials=credentials, expires_in=expires_in, clock=clock)
        self._refresh = refresh
        self._on_credentials_changed = on_credentials_changed
        self._logger = logger
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._refreshing: Future[BearerCredentials] | None = None
        self._timer: TimerHandle | None = None

    @property
    def credentials(self) -> BearerCredentials:
        return self._state.credentials

    @property
    def claims(self) -> AccessTokenClaims:
        return self._state.claims

    def assert_active(self) -> None:
        with self._lock:
            self._state.assert_active()

    def start(self) -> None:
        """Arm background renewal for the current access token."""
        with self._lock:
            self._schedule_locked()

    def ready(self) -> BearerCredentials:
        """Return credentials for a request, waiting for a renewal when one is due or running."""
        with self._lock:
            state = self._state
            state.assert_active()
            remaining = state.remaining()
            # A renewal in flight may be replacing a token the server already rejected.
            if self._refreshing is None and remaining > RENEWAL_LEAD_SECONDS:
                return state.credentials
            # A scheduled retry owns renewal while the current access token is still valid.
            if state.retries > 0 and self._refreshing is None and remaining > 0:
                return state.credentials
        try:
            return self.refresh()
        except Exception:
            with self._lock:
                state = self._state
                if state.closed or state.failure is not None or state.remaining() <= 0:
                    raise
                return state.credentials

    def recover(self, previous_access_token: str) -> None:
        """Renew after the server rejected ``previous_access_token`` as expired."""
        with self._lock:
            self._state.assert_active()
            join = (
                self._refreshing is not None
                or previous_access_token == self._state.credentials.access_token
            )
        if join:
            self.refresh()

    def refresh(self) -> BearerCredentials:
        """Renew now, or join the renewal already in progress."""
        with self._lock:
            self._state.assert_active()
            future = self._refreshing
            owner = future is None
            if future is None:
                # Install the shared renewal before any refresh callback runs.
                future = Future[BearerCredentials]()
                self._refreshing = future
                self._cancel_timer_locked()
        if owner:
            self._run_renewal(future)
        return future.result()

    def bind_wallet(self, wallet: EvmAddress, upgrade: Callable[[str], AccessTokenGrant]) -> None:
        """Bind ``wallet`` to a session without a wallet and adopt the bound access token."""
        with self._lock:
            self._state.assert_active()
            access_token = self._state.credentials.access_token
        grant = upgrade(access_token)
        with self._lock:
            self._state.assert_active()
            self._state.adopt_wallet_binding(grant, wallet)
            self._schedule_locked()
            credentials = self._state.credentials
        self._notify(credentials)

    def logout(self, revoke: Callable[[str], None]) -> None:
        """Revoke the session. Tokens renewed for revocation are never adopted or reported."""
        with self._lock:
            credentials = self._state.credentials
            identity = self._state.claims
            expired = self._state.remaining() <= 0
        # Stop ordinary renewal before acquiring any token needed solely for revocation.
        # A cached renewal failure does not prevent revocation with a valid access token.
        self.close()
        if expired:
            credentials = _renewal_for_revocation(identity, self._refresh(credentials))
        try:
            revoke(credentials.access_token)
        except RequestRejectedError as error:
            if not _is_expired_access_token(error):
                raise
            # The token can expire in flight. Replay this explicit rejection once.
            credentials = _renewal_for_revocation(identity, self._refresh(credentials))
            revoke(credentials.access_token)

    def close(self) -> None:
        with self._lock:
            self._state.closed = True
            self._state.retries = 0
            self._cancel_timer_locked()
        self._stopped.set()

    def _run_renewal(self, future: Future[BearerCredentials]) -> None:
        try:
            credentials = self._renew()
        except BaseException as error:
            with self._lock:
                if not self._state.closed and isinstance(error, Exception):
                    if is_transient_renewal_failure(error):
                        self._retry_later_locked(error)
                    else:
                        self._state.failure = error
                        self._cancel_timer_locked()
                if self._refreshing is future:
                    self._refreshing = None
            future.set_exception(error)
            if not isinstance(error, Exception):
                raise
            return
        with self._lock:
            if self._refreshing is future:
                self._refreshing = None
        future.set_result(credentials)
        self._notify(credentials)

    def _renew(self) -> BearerCredentials:
        tokens: IssuedTokens | None = None
        for attempt in range(_RENEWAL_ATTEMPTS):
            with self._lock:
                self._state.assert_active()
                current = self._state.credentials
            try:
                tokens = self._refresh(current)
                break
            except Exception as error:
                self.assert_active()
                if not _inline_retry_allowed(attempt, error):
                    raise
                if self._stopped.wait(_attempt_delay(attempt, error)):
                    raise TransportError(_STOPPED_MESSAGE) from None
        if tokens is None:
            raise TransportError("Session renewal failed.")
        with self._lock:
            self._state.assert_active()
            self._state.adopt_renewal(tokens)
            self._schedule_locked()
            return self._state.credentials

    def _notify(self, credentials: BearerCredentials) -> None:
        # Persistence is advisory: its failure must not discard adopted credentials.
        if self._on_credentials_changed is None:
            return
        try:
            self._on_credentials_changed(credentials)
        except Exception:
            if self._logger is not None:
                self._logger.warning("polymarket credentials listener failed", exc_info=True)

    def _on_timer(self) -> None:
        # Failures are recorded on the session and surface on the next request.
        with contextlib.suppress(Exception):
            self.refresh()

    def _schedule_locked(self) -> None:
        self._cancel_timer_locked()
        if self._state.closed or self._state.failure is not None:
            return
        self._timer = self._timer_factory(self._state.renewal_delay(), self._on_timer)

    def _retry_later_locked(self, error: BaseException) -> None:
        self._state.retries += 1
        self._cancel_timer_locked()
        self._timer = self._timer_factory(_retry_delay(self._state.retries, error), self._on_timer)

    def _cancel_timer_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


class AsyncAuthSession:
    """Bearer session for the async client.

    Background renewal runs on the event loop, so realtime connections receive
    renewed access tokens without reconnecting.
    """

    def __init__(
        self,
        *,
        credentials: BearerCredentials,
        expires_in: int | None,
        refresh: Callable[[BearerCredentials], Awaitable[IssuedTokens]],
        on_credentials_changed: CredentialsChanged | None = None,
        logger: logging.Logger | None = None,
        clock: Clock = time.time,
    ) -> None:
        self._state = _SessionState(credentials=credentials, expires_in=expires_in, clock=clock)
        self._refresh = refresh
        self._on_credentials_changed = on_credentials_changed
        self._logger = logger
        self._stopped = asyncio.Event()
        self._refreshing: asyncio.Task[BearerCredentials] | None = None
        self._timer: asyncio.TimerHandle | None = None
        self._background: set[asyncio.Task[None]] = set()
        self._change_listeners: list[Callable[[BearerCredentials], None]] = []
        self._failure_listeners: list[Callable[[BaseException], None]] = []

    @property
    def credentials(self) -> BearerCredentials:
        return self._state.credentials

    @property
    def claims(self) -> AccessTokenClaims:
        return self._state.claims

    @property
    def failure(self) -> BaseException | None:
        return self._state.failure

    def expires_at(self, access_token: str) -> float:
        """Local time, in seconds, at which ``access_token`` expires."""
        return self._state.expires_at(access_token)

    def time_until_expiry(self, access_token: str) -> float:
        """Seconds until ``access_token`` expires on the local clock."""
        return self._state.expires_at(access_token) - self._state.clock()

    def assert_active(self) -> None:
        self._state.assert_active()

    def start(self) -> None:
        """Arm background renewal for the current access token."""
        self._schedule()

    def on_change(self, listener: Callable[[BearerCredentials], None]) -> Callable[[], None]:
        """Listen for adopted credentials. Returns a function that removes the listener."""
        self._change_listeners.append(listener)
        return lambda: _discard(self._change_listeners, listener)

    def on_failure(self, listener: Callable[[BaseException], None]) -> Callable[[], None]:
        """Listen for the failure that ends the session. Transient failures are not reported."""
        self._failure_listeners.append(listener)
        return lambda: _discard(self._failure_listeners, listener)

    async def ready(self) -> BearerCredentials:
        """Return credentials for a request, waiting for a renewal when one is due or running."""
        state = self._state
        state.assert_active()
        remaining = state.remaining()
        # A renewal in flight may be replacing a token the server already rejected.
        if self._refreshing is None and remaining > RENEWAL_LEAD_SECONDS:
            return state.credentials
        # A scheduled retry owns renewal while the current access token is still valid.
        if state.retries > 0 and self._refreshing is None and remaining > 0:
            return state.credentials
        try:
            return await self.refresh()
        except Exception:
            if state.closed or state.failure is not None or state.remaining() <= 0:
                raise
            return state.credentials

    async def recover(self, previous_access_token: str) -> None:
        """Renew after the server rejected ``previous_access_token`` as expired."""
        self._state.assert_active()
        if (
            self._refreshing is not None
            or previous_access_token == self._state.credentials.access_token
        ):
            await self.refresh()

    async def refresh(self) -> BearerCredentials:
        """Renew now, or join the renewal already in progress."""
        self._state.assert_active()
        task = self._refreshing
        if task is None:
            self._cancel_timer()
            # Install the shared renewal before any refresh callback runs.
            task = asyncio.get_running_loop().create_task(self._run_renewal())
            self._refreshing = task
        # Cancelling one waiter does not cancel a renewal shared with others.
        return await asyncio.shield(task)

    async def bind_wallet(
        self, wallet: EvmAddress, upgrade: Callable[[str], Awaitable[AccessTokenGrant]]
    ) -> None:
        """Bind ``wallet`` to a session without a wallet and adopt the bound access token."""
        self._state.assert_active()
        grant = await upgrade(self._state.credentials.access_token)
        self._state.assert_active()
        self._state.adopt_wallet_binding(grant, wallet)
        self._schedule()
        self._notify(self._state.credentials)

    async def logout(self, revoke: Callable[[str], Awaitable[None]]) -> None:
        """Revoke the session. Tokens renewed for revocation are never adopted or reported."""
        credentials = self._state.credentials
        identity = self._state.claims
        expired = self._state.remaining() <= 0
        # Stop ordinary renewal before acquiring any token needed solely for revocation.
        # A cached renewal failure does not prevent revocation with a valid access token.
        self.close()
        if expired:
            credentials = _renewal_for_revocation(identity, await self._refresh(credentials))
        try:
            await revoke(credentials.access_token)
        except RequestRejectedError as error:
            if not _is_expired_access_token(error):
                raise
            # The token can expire in flight. Replay this explicit rejection once.
            credentials = _renewal_for_revocation(identity, await self._refresh(credentials))
            await revoke(credentials.access_token)

    def close(self) -> None:
        self._state.closed = True
        self._state.retries = 0
        self._cancel_timer()
        self._stopped.set()
        self._change_listeners.clear()
        self._failure_listeners.clear()

    async def _run_renewal(self) -> BearerCredentials:
        task = asyncio.current_task()
        try:
            credentials = await self._renew()
        except Exception as error:
            if not self._state.closed:
                if is_transient_renewal_failure(error):
                    self._retry_later(error)
                else:
                    self._end(error)
            raise
        finally:
            if self._refreshing is task:
                self._refreshing = None
        self._notify(credentials)
        return credentials

    async def _renew(self) -> BearerCredentials:
        tokens: IssuedTokens | None = None
        for attempt in range(_RENEWAL_ATTEMPTS):
            self._state.assert_active()
            try:
                tokens = await self._refresh(self._state.credentials)
                break
            except Exception as error:
                self._state.assert_active()
                if not _inline_retry_allowed(attempt, error):
                    raise
                if await self._wait_stopped(_attempt_delay(attempt, error)):
                    raise TransportError(_STOPPED_MESSAGE) from None
        if tokens is None:
            raise TransportError("Session renewal failed.")
        self._state.assert_active()
        self._state.adopt_renewal(tokens)
        self._schedule()
        return self._state.credentials

    async def _wait_stopped(self, delay: float) -> bool:
        try:
            await asyncio.wait_for(self._stopped.wait(), delay)
        except TimeoutError:
            return False
        return True

    def _notify(self, credentials: BearerCredentials) -> None:
        for listener in tuple(self._change_listeners):
            listener(credentials)
        # Persistence is advisory: its failure must not discard adopted credentials.
        if self._on_credentials_changed is None:
            return
        try:
            self._on_credentials_changed(credentials)
        except Exception:
            if self._logger is not None:
                self._logger.warning("polymarket credentials listener failed", exc_info=True)

    def _end(self, error: BaseException) -> None:
        self._state.failure = error
        self._cancel_timer()
        for listener in tuple(self._failure_listeners):
            listener(error)

    def _schedule(self) -> None:
        self._cancel_timer()
        if self._state.closed or self._state.failure is not None:
            return
        self._arm(self._state.renewal_delay())

    def _retry_later(self, error: BaseException) -> None:
        self._state.retries += 1
        self._cancel_timer()
        self._arm(_retry_delay(self._state.retries, error))

    def _arm(self, delay: float) -> None:
        loop = asyncio.get_running_loop()
        self._timer = loop.call_later(delay, self._on_timer)

    def _on_timer(self) -> None:
        self._timer = None
        task = asyncio.get_running_loop().create_task(self._background_refresh())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _background_refresh(self) -> None:
        # Failures are recorded on the session and surface on the next request.
        with contextlib.suppress(Exception):
            await self.refresh()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


class DeferredCredentialsListener:
    """Hold back credential notifications for a new session until client creation succeeds.

    Only the latest pair is kept. A failed creation never reports its session.
    """

    def __init__(
        self,
        listener: CredentialsChanged | None,
        *,
        publish: bool,
        logger: logging.Logger | None = None,
    ) -> None:
        self._listener = listener
        self._publish = publish
        self._logger = logger
        self._pending: BearerCredentials | None = None
        self._lock = threading.Lock()

    def __call__(self, credentials: BearerCredentials) -> None:
        with self._lock:
            if not self._publish:
                self._pending = credentials
                return
        if self._listener is not None:
            self._listener(credentials)

    def publish(self) -> None:
        with self._lock:
            self._publish = True
            pending, self._pending = self._pending, None
        if pending is None or self._listener is None:
            return
        try:
            self._listener(pending)
        except Exception:
            if self._logger is not None:
                self._logger.warning("polymarket credentials listener failed", exc_info=True)


def _discard(items: list[Callable[..., None]], item: Callable[..., None]) -> None:
    if item in items:
        items.remove(item)


__all__ = [
    "MAX_RETRY_DELAY_SECONDS",
    "RENEWAL_LEAD_SECONDS",
    "AsyncAuthSession",
    "CredentialsChanged",
    "DeferredCredentialsListener",
    "SyncAuthSession",
    "is_transient_renewal_failure",
]
