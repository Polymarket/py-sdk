import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.protocol import State

from polymarket._internal.ws.heartbeat import Heartbeat, NoopHeartbeat
from polymarket.errors import TransportError

OnMessage = Callable[[Any], None]
# Invoked only for closes not initiated through close(), with the WebSocket
# close code and reason.
OnConnectionLost = Callable[[int, str], None]
OnError = Callable[[BaseException], None]

DEFAULT_WATCHDOG_INTERVAL_S = 5.0
DEFAULT_OPEN_TIMEOUT_S = 10.0
DEFAULT_CLOSE_TIMEOUT_S = 0.5


@dataclass(frozen=True)
class ConnectResult:
    reused: bool


def _socket_is_open(socket: ClientConnection | None) -> bool:
    return socket is not None and socket.state is State.OPEN


class AsyncWebSocketConnection:
    def __init__(
        self,
        *,
        heartbeat: Heartbeat | None = None,
        logger: logging.Logger | None = None,
        watchdog_interval_s: float = DEFAULT_WATCHDOG_INTERVAL_S,
        open_timeout_s: float = DEFAULT_OPEN_TIMEOUT_S,
        close_timeout_s: float = DEFAULT_CLOSE_TIMEOUT_S,
    ) -> None:
        if watchdog_interval_s <= 0:
            raise ValueError("watchdog_interval_s must be positive")
        if close_timeout_s <= 0:
            raise ValueError("close_timeout_s must be positive")
        self._heartbeat: Heartbeat = heartbeat or NoopHeartbeat()
        self._logger = logger or logging.getLogger("polymarket.ws")
        self._watchdog_interval_s = watchdog_interval_s
        self._open_timeout_s = open_timeout_s
        self._close_timeout_s = close_timeout_s
        self._socket: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._connecting: asyncio.Task[ConnectResult] | None = None
        self._closing: asyncio.Task[None] | None = None
        self._on_connection_lost: OnConnectionLost | None = None
        self._on_error: OnError | None = None

    @property
    def is_open(self) -> bool:
        return _socket_is_open(self._socket)

    async def connect(
        self,
        *,
        url: str,
        on_message: OnMessage,
        on_connection_lost: OnConnectionLost,
        on_error: OnError,
        headers: Mapping[str, str] | None = None,
    ) -> ConnectResult:
        existing = self._socket
        if existing is not None:
            if _socket_is_open(existing):
                return ConnectResult(reused=True)
            # Stale socket: route through close() so the finalizer's
            # heartbeat.stop() and watchdog cancel run before re-opening.
            await self.close()
        if self._connecting is not None:
            return await self._connecting
        task = asyncio.create_task(
            self._open(
                url=url,
                on_message=on_message,
                on_connection_lost=on_connection_lost,
                on_error=on_error,
                headers=headers,
            )
        )
        self._connecting = task
        try:
            return await task
        finally:
            if self._connecting is task:
                self._connecting = None

    async def _open(
        self,
        *,
        url: str,
        on_message: OnMessage,
        on_connection_lost: OnConnectionLost,
        on_error: OnError,
        headers: Mapping[str, str] | None,
    ) -> ConnectResult:
        additional_headers = dict(headers) if headers else None
        try:
            socket = await ws_connect(
                url,
                additional_headers=additional_headers,
                open_timeout=self._open_timeout_s,
                close_timeout=self._close_timeout_s,
            )
        except (OSError, TimeoutError, WebSocketException) as error:
            raise TransportError(str(error) or f"WebSocket connection failed: {url}") from error
        self._socket = socket
        self._on_connection_lost = on_connection_lost
        self._on_error = on_error
        self._reader_task = asyncio.create_task(self._read_loop(socket, on_message))
        try:
            await self._heartbeat.start(self.send)
        except BaseException:
            await self._abort_open(socket)
            raise
        self._watchdog_task = asyncio.create_task(self._watchdog_loop(socket))
        return ConnectResult(reused=False)

    async def _abort_open(self, socket: ClientConnection) -> None:
        self._socket = None
        self._on_connection_lost = None
        self._on_error = None
        try:
            await socket.close()
        except Exception:
            self._logger.debug("error closing socket during aborted open", exc_info=True)
        if self._reader_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task
            self._reader_task = None

    def _claim_socket(self, expected: ClientConnection) -> bool:
        # Atomic check-and-clear: no await between the two lines, so only
        # one caller can claim cleanup ownership for any given socket.
        if self._socket is not expected:
            return False
        self._socket = None
        return True

    async def _read_loop(self, socket: ClientConnection, on_message: OnMessage) -> None:
        try:
            async for raw in socket:
                if self._socket is not socket:
                    return
                if isinstance(raw, bytes):
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                else:
                    text = raw
                if self._heartbeat.handle(text):
                    continue
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                try:
                    on_message(parsed)
                except Exception:
                    self._logger.exception("on_message callback raised")
        except ConnectionClosed:
            pass
        except Exception as exc:
            if self._socket is socket and self._on_error is not None:
                try:
                    self._on_error(exc)
                except Exception:
                    self._logger.exception("on_error callback raised")
        finally:
            if self._claim_socket(socket):
                on_connection_lost = self._on_connection_lost
                self._on_connection_lost = None
                self._on_error = None
                watchdog = self._watchdog_task
                self._watchdog_task = None
                await self._heartbeat.stop()
                if watchdog is not None:
                    watchdog.cancel()
                try:
                    await socket.close()
                except Exception:
                    self._logger.debug("error closing socket after reader stopped", exc_info=True)
                if on_connection_lost is not None:
                    code = socket.close_code if socket.close_code is not None else 1006
                    reason = socket.close_reason or ""
                    try:
                        on_connection_lost(code, reason)
                    except Exception:
                        self._logger.exception("on_connection_lost callback raised")

    async def _watchdog_loop(self, socket: ClientConnection) -> None:
        try:
            while True:
                await asyncio.sleep(self._watchdog_interval_s)
                if self._socket is not socket:
                    return
                if self._heartbeat.is_stale(time.monotonic()):
                    self._logger.warning("WebSocket heartbeat stale; closing")
                    try:
                        await socket.close()
                    except Exception:
                        self._logger.debug("error closing stale socket", exc_info=True)
                    return
        except asyncio.CancelledError:
            return

    async def send(self, payload: Any) -> bool:
        # Best-effort: returns False on disconnect rather than raising. The
        # reconnect path is expected to replay any frames that were missed.
        socket = self._socket
        if not _socket_is_open(socket):
            return False
        text = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
        try:
            assert socket is not None
            await socket.send(text)
        except ConnectionClosed:
            return False
        return True

    async def close(self) -> None:
        if self._closing is None:
            self._closing = asyncio.create_task(self._shutdown())
        closing = self._closing
        try:
            await closing
        finally:
            if self._closing is closing:
                self._closing = None

    async def _shutdown(self) -> None:
        if self._connecting is not None:
            with contextlib.suppress(Exception):
                await self._connecting
        socket = self._socket
        # If the reader finalizer claimed first, cleanup is done — just
        # await the leftover tasks below.
        claimed = socket is not None and self._claim_socket(socket)
        watchdog = self._watchdog_task
        self._watchdog_task = None
        reader = self._reader_task
        self._reader_task = None
        if claimed:
            # User-initiated close: suppress on_connection_lost to distinguish
            # from an unexpected disconnect.
            self._on_connection_lost = None
            self._on_error = None
            await self._heartbeat.stop()
            if watchdog is not None:
                watchdog.cancel()
            if socket is not None:
                try:
                    await socket.close()
                except Exception:
                    self._logger.debug("error closing socket on shutdown", exc_info=True)
        if reader is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader
        if watchdog is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog
