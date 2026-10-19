"""One private bearer session per client, shared by HTTP, timers and sockets."""

import asyncio
import contextlib
import contextvars
import inspect
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeAlias

from polymarket._internal.gateway_auth import parse_tokens, token_claims
from polymarket.auth import BearerCredentials
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import RateLimitError, RequestRejectedError, TransportError, UserInputError

CredentialsCallback: TypeAlias = Callable[[BearerCredentials], Awaitable[None] | None]
REFRESH_BUFFER_S = 30.0
MAX_ATTEMPTS = 3
_CALLBACK_SESSION: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "polymarket_callback_session", default=None
)


def _delay(credentials: BearerCredentials) -> float:
    remaining = float(token_claims(credentials)["exp"]) - time.time()
    return max(0.1, remaining - min(REFRESH_BUFFER_S, remaining / 2))


def _transient(error: Exception) -> bool:
    return isinstance(error, TransportError | RateLimitError) or (
        isinstance(error, RequestRejectedError) and (error.status >= 500 or error.status == 429)
    )


def _check_identity(before: BearerCredentials, after: BearerCredentials) -> None:
    old, new = token_claims(before), token_claims(after)
    if any(
        old.get(key) != new.get(key)
        for key in ("sub", "client_id", "wallet", "signature_type", "clob_api_key", "iss", "aud")
    ):
        raise UserInputError("Refreshed credentials changed the session identity")


async def _await_callback(result: Awaitable[None], session: object) -> None:
    token = _CALLBACK_SESSION.set(session)
    try:
        await result
    finally:
        _CALLBACK_SESSION.reset(token)


def _sync_callback(
    callback: CredentialsCallback, credentials: BearerCredentials, session: object
) -> None:
    result = callback(credentials)
    if inspect.isawaitable(result):
        # Only bridge application callbacks, never the sync HTTP transport. A separate
        # thread also permits a sync client used by a caller with an active event loop.
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(asyncio.run, _await_callback(result, session)).result()


class SyncGatewaySession:
    def __init__(
        self,
        credentials: BearerCredentials,
        transport: SyncTransport,
        callback: CredentialsCallback | None = None,
        validate_initial: Callable[[BearerCredentials], None] | None = None,
    ) -> None:
        token_claims(credentials)
        self.credentials = credentials
        self.transport = transport
        self._callback = callback
        self._validate_initial = validate_initial
        self._condition = threading.Condition(threading.RLock())
        self._stop = threading.Event()
        self._refreshing = False
        self._owner: int | None = None
        self._error: Exception | None = None
        self._worker: threading.Thread | None = None
        self._deadline = time.monotonic() + _delay(credentials)

    def start(self) -> None:
        with self._condition:
            self._assert_open()
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="polymarket-auth", daemon=True
                )
                self._worker.start()

    def _assert_open(self) -> None:
        if self._stop.is_set():
            raise RuntimeError("Authentication session is closed")
        if self._error is not None:
            raise self._error

    def ensure_valid(self) -> BearerCredentials:
        with self._condition:
            self._assert_open()
            current = self.credentials
        if token_claims(current)["exp"] - time.time() <= REFRESH_BUFFER_S:
            return self.refresh(current.access_token)
        return current

    def refresh(self, previous_token: str) -> BearerCredentials:
        with self._condition:
            self._assert_open()
            if self.credentials.access_token != previous_token:
                return self.credentials
            if self._refreshing:
                if self._owner == threading.get_ident() or _CALLBACK_SESSION.get() is self:
                    return self.credentials
                self._condition.wait_for(lambda: not self._refreshing or self._stop.is_set())
                self._assert_open()
                return self.credentials
            self._refreshing = True
            self._owner = threading.get_ident()
            before = self.credentials
        try:
            updated = before
            for attempt in range(MAX_ATTEMPTS):
                try:
                    value = self.transport.post_json(
                        "/v1/auth/refresh", json={"refresh_token": before.refresh_token}
                    )
                    updated = parse_tokens(value)
                    _check_identity(before, updated)
                    break
                except Exception as error:
                    if not _transient(error) or attempt == MAX_ATTEMPTS - 1:
                        raise
                    if self._stop.wait(0.25 * 2**attempt):
                        raise RuntimeError("Authentication session is closed") from None
            if self._validate_initial is not None:
                self._validate_initial(updated)
                self._validate_initial = None
            with self._condition:
                self._assert_open()
                self.credentials = updated
                self._deadline = time.monotonic() + _delay(updated)
                self._condition.notify_all()
            if self._callback is not None:
                try:
                    _sync_callback(self._callback, updated, self)
                except Exception:
                    logging.getLogger("polymarket.auth").warning(
                        "Credential persistence callback failed"
                    )
            return updated
        except Exception as error:
            with self._condition:
                self._error = error
            raise
        finally:
            with self._condition:
                self._refreshing = False
                self._owner = None
                self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._stop.is_set() or self._error is not None:
                    return
                remaining = self._deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                token = self.credentials.access_token
            try:
                self.refresh(token)
            except Exception:
                return

    def close(self) -> None:
        with self._condition:
            self._stop.set()
            self._condition.notify_all()
            if self._owner != threading.get_ident() and _CALLBACK_SESSION.get() is not self:
                self._condition.wait_for(lambda: not self._refreshing)
        if (
            self._worker is not None
            and self._worker is not threading.current_thread()
            and _CALLBACK_SESSION.get() is not self
        ):
            self._worker.join()
        self.transport.close()


class AsyncGatewaySession:
    def __init__(
        self,
        credentials: BearerCredentials,
        transport: AsyncTransport,
        callback: CredentialsCallback | None = None,
        validate_initial: Callable[[BearerCredentials], Awaitable[None]] | None = None,
    ) -> None:
        token_claims(credentials)
        self.credentials = credentials
        self.transport = transport
        self._callback = callback
        self._validate_initial = validate_initial
        self._closed = False
        self._error: Exception | None = None
        self._task: asyncio.Task[BearerCredentials] | None = None
        self._timer: asyncio.TimerHandle | None = None
        self._listeners: set[Callable[[BearerCredentials], None]] = set()

    def add_listener(self, listener: Callable[[BearerCredentials], None]) -> Callable[[], None]:
        self._assert_open()
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Authentication session is closed")
        if self._error is not None:
            raise self._error

    def start(self) -> None:
        self._assert_open()
        if self._timer is not None:
            self._timer.cancel()
        self._timer = asyncio.get_running_loop().call_later(
            _delay(self.credentials), self._scheduled
        )

    def _scheduled(self) -> None:
        self._timer = None
        if not self._closed and self._task is None:
            self._launch()

    def _launch(self) -> asyncio.Task[BearerCredentials]:
        task = asyncio.create_task(self._refresh())
        self._task = task

        def done(completed: asyncio.Task[BearerCredentials]) -> None:
            if self._task is completed:
                self._task = None
            if not completed.cancelled():
                completed.exception()  # background errors surface on the next operation

        task.add_done_callback(done)
        return task

    async def ensure_valid(self) -> BearerCredentials:
        self._assert_open()
        if token_claims(self.credentials)["exp"] - time.time() <= REFRESH_BUFFER_S:
            return await self.refresh(self.credentials.access_token)
        return self.credentials

    async def refresh(self, previous_token: str) -> BearerCredentials:
        self._assert_open()
        if self.credentials.access_token != previous_token:
            return self.credentials
        if self._task is asyncio.current_task():
            return self.credentials
        task = self._task or self._launch()
        # Cancellation of one HTTP/socket waiter must not cancel the shared refresh.
        return await asyncio.shield(task)

    async def _refresh(self) -> BearerCredentials:
        before = self.credentials
        try:
            updated = before
            for attempt in range(MAX_ATTEMPTS):
                try:
                    value = await self.transport.post_json(
                        "/v1/auth/refresh", json={"refresh_token": before.refresh_token}
                    )
                    updated = parse_tokens(value)
                    _check_identity(before, updated)
                    break
                except Exception as error:
                    if not _transient(error) or attempt == MAX_ATTEMPTS - 1:
                        raise
                    await asyncio.sleep(0.25 * 2**attempt)
            if self._validate_initial is not None:
                await self._validate_initial(updated)
                self._validate_initial = None
            self._assert_open()
            self.credentials = updated
            self.start()
            for listener in tuple(self._listeners):
                listener(updated)
            if self._callback is not None:
                try:
                    result = self._callback(updated)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    logging.getLogger("polymarket.auth").warning(
                        "Credential persistence callback failed"
                    )
            return updated
        except Exception as error:
            self._error = error
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            raise

    async def close(self) -> None:
        self._closed = True
        self._listeners.clear()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        task = self._task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self.transport.close()


def logout_sync(transport: SyncTransport, credentials: BearerCredentials) -> None:
    """Revoke a stopped session without consulting its cached refresh failure.

    A still-usable bearer needs no refresh. Recovery credentials are used only
    for revocation: they never revive the client or invoke persistence callbacks.
    Logout is idempotent, including an uncertain 503 commit acknowledgement.
    """
    current = credentials
    refreshed = False
    refresh_requested = False
    for attempt in range(MAX_ATTEMPTS):
        if token_claims(current)["exp"] <= time.time():
            if refreshed:
                raise RequestRejectedError(
                    "Access Token expired before logout", status=401, code="expired_access_token"
                )
            refresh_requested = True
        if refresh_requested:
            for refresh_attempt in range(MAX_ATTEMPTS):
                try:
                    updated = parse_tokens(
                        transport.post_json(
                            "/v1/auth/refresh", json={"refresh_token": current.refresh_token}
                        )
                    )
                    _check_identity(current, updated)
                    current = updated
                    break
                except Exception as error:
                    if not _transient(error) or refresh_attempt == MAX_ATTEMPTS - 1:
                        raise
                    time.sleep(0.25 * 2**refresh_attempt)
            refreshed = True
            refresh_requested = False
        try:
            transport.post(
                "/v1/auth/logout", headers={"Authorization": "Bearer " + current.access_token}
            )
            return
        except Exception as error:
            if attempt == MAX_ATTEMPTS - 1:
                raise
            if (
                isinstance(error, RequestRejectedError)
                and error.status == 401
                and error.code == "expired_access_token"
                and not refreshed
            ):
                refresh_requested = True
                continue
            if not _transient(error):
                raise
            time.sleep(0.25 * 2**attempt)


async def logout_async(transport: AsyncTransport, credentials: BearerCredentials) -> None:
    """Revoke a stopped session without consulting its cached refresh failure.

    A still-usable bearer needs no refresh. Recovery credentials are used only
    for revocation: they never revive the client or invoke persistence callbacks.
    Logout is idempotent, including an uncertain 503 commit acknowledgement.
    """
    current = credentials
    refreshed = False
    refresh_requested = False
    for attempt in range(MAX_ATTEMPTS):
        if token_claims(current)["exp"] <= time.time():
            if refreshed:
                raise RequestRejectedError(
                    "Access Token expired before logout", status=401, code="expired_access_token"
                )
            refresh_requested = True
        if refresh_requested:
            for refresh_attempt in range(MAX_ATTEMPTS):
                try:
                    updated = parse_tokens(
                        await transport.post_json(
                            "/v1/auth/refresh", json={"refresh_token": current.refresh_token}
                        )
                    )
                    _check_identity(current, updated)
                    current = updated
                    break
                except Exception as error:
                    if not _transient(error) or refresh_attempt == MAX_ATTEMPTS - 1:
                        raise
                    await asyncio.sleep(0.25 * 2**refresh_attempt)
            refreshed = True
            refresh_requested = False
        try:
            await transport.post(
                "/v1/auth/logout", headers={"Authorization": "Bearer " + current.access_token}
            )
            return
        except Exception as error:
            if attempt == MAX_ATTEMPTS - 1:
                raise
            if (
                isinstance(error, RequestRejectedError)
                and error.status == 401
                and error.code == "expired_access_token"
                and not refreshed
            ):
                refresh_requested = True
                continue
            if not _transient(error):
                raise
            await asyncio.sleep(0.25 * 2**attempt)
