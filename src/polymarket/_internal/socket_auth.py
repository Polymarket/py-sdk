"""Bearer renewal ownership for persistent sockets; never sends Refresh Tokens."""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Literal, cast

from polymarket._internal.gateway_auth import token_claims
from polymarket._internal.gateway_session import AsyncGatewaySession
from polymarket.auth import BearerCredentials
from polymarket.errors import RequestRejectedError, TransportError

SocketProtocol = Literal["clob", "combos", "polybolt"]
ACK_TIMEOUT_S = 10.0
EXPIRY_TOLERANCE_S = 30.0


class SocketAuthentication:
    def __init__(
        self,
        *,
        session: AsyncGatewaySession,
        protocol: SocketProtocol,
        send: Callable[[dict[str, object]], Awaitable[object]],
        expire: Callable[[], Awaitable[None]],
    ) -> None:
        self._session, self._protocol, self._send, self._expire = session, protocol, send, expire
        self._unsubscribe = session.add_listener(self._changed)
        self._lock = asyncio.Lock()
        self._pending: asyncio.Future[None] | None = None
        self._rid = 0
        self._expected_rid: str | None = None
        self._accepted: BearerCredentials | None = None
        self._deadline: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False
        self._connected = False

    def _spawn(self, operation: Awaitable[None]) -> None:
        async def run() -> None:
            await operation

        task = asyncio.create_task(run())
        self._tasks.add(task)

        def done(value: asyncio.Task[None]) -> None:
            self._tasks.discard(value)
            if not value.cancelled():
                value.exception()

        task.add_done_callback(done)

    def _changed(self, credentials: BearerCredentials) -> None:
        if self._connected and not self._closed:
            self._spawn(self._renew(credentials))

    async def initial(self, frame: dict[str, object] | None = None) -> None:
        credentials = await self._session.ensure_valid()
        self._connected = True
        if self._protocol == "clob":
            # CLOB's first subscribe has no authentication acknowledgement.
            assert frame is not None
            async with self._lock:
                await self._send({**frame, "auth": {"accessToken": credentials.access_token}})
                self._accept(credentials)
        else:
            await self._renew(credentials)

    async def _renew(self, credentials: BearerCredentials) -> None:
        async with self._lock:
            if self._closed or not self._connected:
                return
            if self._accepted == credentials:
                return
            if self._accepted is not None:
                keys = (
                    ("sub", "client_id", "clob_api_key")
                    if self._protocol == "clob"
                    else (
                        ("sub", "client_id")
                        if self._protocol == "polybolt"
                        else ("sub", "client_id", "wallet", "signature_type")
                    )
                )
                old, new = token_claims(self._accepted), token_claims(credentials)
                if any(old.get(key) != new.get(key) for key in keys):
                    raise RequestRejectedError("Socket renewal changed identity", status=401)
            for attempt in range(3):
                loop = asyncio.get_running_loop()
                pending: asyncio.Future[None] = loop.create_future()
                self._pending = pending
                frame: dict[str, object] = {"auth": {"accessToken": credentials.access_token}}
                if self._protocol == "polybolt":
                    self._rid += 1
                    self._expected_rid = "auth-" + str(self._rid)
                    frame.update(op="auth", rid=self._expected_rid)
                else:
                    frame["type"] = "auth"
                try:
                    if await self._send(frame) is False:
                        raise TransportError("Socket is not open")
                    await asyncio.wait_for(pending, ACK_TIMEOUT_S)
                    if self._closed or not self._connected:
                        return
                    self._accept(credentials)
                    return
                except RequestRejectedError as error:
                    if error.code != "auth_unavailable" or attempt == 2:
                        raise
                    await asyncio.sleep(0.25 * 2**attempt)
                except TimeoutError:
                    # An uncorrelated late CLOB/Combos ack cannot accept a later attempt.
                    self.disconnected()
                    await self._expire()
                    raise TransportError(
                        "Socket authentication acknowledgement timed out"
                    ) from None
                finally:
                    if self._pending is pending:
                        self._pending = None
                    if not pending.done():
                        pending.cancel()
                    elif not pending.cancelled():
                        pending.exception()

    def message(self, value: object) -> bool:
        if not isinstance(value, dict):
            return False
        frame = cast(dict[str, object], value)
        if self._protocol == "polybolt":
            if frame.get("op") not in ("authed", "error") or frame.get("rid") != self._expected_rid:
                return False
            success = frame.get("op") == "authed"
        else:
            if frame.get("type") != "auth":
                return False
            success = frame.get("success") is True
        pending = self._pending
        if pending is not None and not pending.done():
            if success:
                pending.set_result(None)
            else:
                # Do not echo server text: errors may contain credentials.
                code = (
                    "auth_unavailable"
                    if frame.get("code") == "auth_unavailable"
                    else "auth_invalid"
                )
                pending.set_exception(
                    RequestRejectedError("Socket authentication rejected", status=401, code=code)
                )
        return True

    def _accept(self, credentials: BearerCredentials) -> None:
        self._accepted = credentials
        if self._deadline is not None:
            self._deadline.cancel()
        delay = max(
            0,
            float(token_claims(credentials)["exp"]) + EXPIRY_TOLERANCE_S - time.time(),
        )
        self._deadline = asyncio.get_running_loop().call_later(delay, self._expired)

    def _expired(self) -> None:
        self._deadline = None
        if self._connected and not self._closed:
            self.disconnected()
            self._spawn(self._expire())

    def disconnected(self) -> None:
        self._connected = False
        self._accepted = None
        if self._deadline is not None:
            self._deadline.cancel()
            self._deadline = None
        if self._pending is not None and not self._pending.done():
            self._pending.set_exception(TransportError("Socket disconnected during authentication"))

    async def close(self) -> None:
        self._closed = True
        self._unsubscribe()
        self.disconnected()
        tasks = tuple(self._tasks)
        for task in tasks:
            if task is not asyncio.current_task():
                task.cancel()
        for task in tasks:
            if task is not asyncio.current_task():
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
