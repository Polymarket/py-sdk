"""Access-token upkeep for authenticated realtime connections."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from polymarket._internal.auth_session import RENEWAL_LEAD_SECONDS, AsyncAuthSession
from polymarket.auth import BearerCredentials
from polymarket.errors import RequestRejectedError, TransportError

_RENEWAL_ATTEMPTS = 3


class SocketAuthentication:
    """Track the access token a connection last had acknowledged.

    The connection receives every renewed token in-band. When the acknowledged
    token expires without a successful renewal, ``expired`` runs so the owner can
    reconnect with a current token. A failure that ends the session runs ``fail``.
    """

    def __init__(
        self,
        *,
        session: AsyncAuthSession,
        authenticate: Callable[[str], Awaitable[None]],
        expired: Callable[[], None],
        fail: Callable[[BaseException], None],
    ) -> None:
        self._session = session
        self._authenticate = authenticate
        self._expired = expired
        self._fail = fail
        self._active = False
        self._generation = 0
        self._pending: str | None = None
        self._renewing = False
        self._deadline: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._unlisten: Callable[[], None] | None = None
        self._unfail: Callable[[], None] | None = None

    async def prepare(self) -> BearerCredentials:
        """Return credentials for a new connection, waiting for a due renewal."""
        return await self._session.ready()

    def accepted(self, access_token: str) -> None:
        """Record that the server acknowledged ``access_token`` on this connection."""
        self._active = True
        if self._unlisten is None:
            self._unlisten = self._session.on_change(self._on_change)
            self._unfail = self._session.on_failure(self._fail)
        self._cancel_deadline()
        delay = self._session.time_until_expiry(access_token) + RENEWAL_LEAD_SECONDS
        self._deadline = asyncio.get_running_loop().call_later(max(0.0, delay), self._expired)
        # A renewal can complete while an acknowledgement is pending.
        current = self._session.credentials.access_token
        if current != access_token:
            self._pending = current
            self._start_renewal()

    def stop(self) -> None:
        self._active = False
        self._generation += 1
        self._pending = None
        self._cancel_deadline()
        for task in tuple(self._tasks):
            task.cancel()
        if self._unlisten is not None:
            self._unlisten()
            self._unlisten = None
        if self._unfail is not None:
            self._unfail()
            self._unfail = None

    def _on_change(self, credentials: BearerCredentials) -> None:
        self._pending = credentials.access_token
        self._start_renewal()

    def _start_renewal(self) -> None:
        if not self._active or self._renewing:
            return
        task = asyncio.get_running_loop().create_task(self._renew())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _renew(self) -> None:
        if not self._active or self._renewing:
            return
        self._renewing = True
        generation = self._generation
        try:
            while self._pending is not None and self._is_current(generation):
                token = self._pending
                self._pending = None
                for attempt in range(_RENEWAL_ATTEMPTS):
                    if not self._is_current(generation):
                        return
                    try:
                        await self._authenticate(token)
                    except Exception as error:
                        if not self._is_current(generation):
                            return
                        transient = isinstance(error, TransportError) or (
                            isinstance(error, RequestRejectedError)
                            and error.code == "auth_unavailable"
                        )
                        # A rejection keeps the deadline of the token already accepted.
                        if not transient or attempt == _RENEWAL_ATTEMPTS - 1:
                            break
                        await asyncio.sleep(0.25 * 2**attempt)
                        continue
                    if self._is_current(generation):
                        self.accepted(token)
                    break
        finally:
            self._renewing = False

    def _is_current(self, generation: int) -> bool:
        return self._active and generation == self._generation

    def _cancel_deadline(self) -> None:
        if self._deadline is not None:
            self._deadline.cancel()
            self._deadline = None


async def wait_for_acknowledgement(
    future: asyncio.Future[None], timeout: float, message: str
) -> None:
    """Wait for an authentication acknowledgement, failing with ``message`` on timeout."""
    try:
        await asyncio.wait_for(asyncio.shield(future), timeout)
    except TimeoutError:
        with contextlib.suppress(asyncio.InvalidStateError):
            future.cancel()
        raise TransportError(message) from None


__all__ = ["SocketAuthentication", "wait_for_acknowledgement"]
