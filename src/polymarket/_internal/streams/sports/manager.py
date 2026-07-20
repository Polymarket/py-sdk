# pyright: reportPrivateUsage=false
import asyncio
import contextlib
import logging
from types import TracebackType
from typing import Self

from pydantic import ValidationError

from polymarket._internal.streams.handle import AsyncSubscriptionHandle
from polymarket._internal.streams.reconnect import ReconnectScheduler
from polymarket._internal.streams.registry import SubscriptionRegistry
from polymarket._internal.streams.sports.heartbeat import SportsWebSocketHeartbeat
from polymarket._internal.ws.connection import AsyncWebSocketConnection, ConnectResult
from polymarket._internal.ws.heartbeat import Heartbeat
from polymarket.errors import TransportError
from polymarket.models.sports_events import SportsEvent, parse_sports_event
from polymarket.streams._specs import SportsSpec

DEFAULT_QUEUE_SIZE = 1024


def _accept_all(_event: SportsEvent) -> bool:
    return True


def _no_state(_subs: object) -> None:
    return None


class SportsStreamManager:
    """Sports WebSocket stream.

    The server streams immediately on connection open; the client never
    sends a subscribe frame. Every subscriber receives every event — there
    is no per-subscription filtering on the wire. Heartbeat is
    server-initiated: server pings, client pongs.
    """

    def __init__(
        self,
        *,
        url: str,
        logger: logging.Logger | None = None,
        heartbeat: Heartbeat | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self._url = url
        self._logger = logger or logging.getLogger("polymarket.streams.sports")
        self._heartbeat: Heartbeat = heartbeat or SportsWebSocketHeartbeat()
        self._queue_size = queue_size
        self._connection = AsyncWebSocketConnection(heartbeat=self._heartbeat, logger=self._logger)
        self._registry: SubscriptionRegistry[SportsSpec, SportsEvent, None] = SubscriptionRegistry(
            derive_state=_no_state, logger=self._logger
        )
        self._scheduler = ReconnectScheduler(logger=self._logger)
        self._send_lock = asyncio.Lock()
        self._closed = False
        self._dropped_events = 0

    @property
    def is_open(self) -> bool:
        return self._connection.is_open

    @property
    def dropped_events(self) -> int:
        return self._dropped_events

    async def subscribe(self) -> AsyncSubscriptionHandle[SportsEvent]:
        if self._closed:
            raise RuntimeError("SportsStreamManager is closed")
        handle: AsyncSubscriptionHandle[SportsEvent] = AsyncSubscriptionHandle(
            queue_size=self._queue_size
        )
        handle._bind_close(self._on_handle_close)

        async with self._send_lock:
            self._registry.add(sub=SportsSpec(), matcher=_accept_all, handle=handle)
            try:
                await self._open_connection()
            except BaseException:
                self._registry.remove_handle(handle)
                handle._end()
                if self._registry.is_empty and self._connection.is_open:
                    self._scheduler.cancel_pending()
                    try:
                        await self._connection.close()
                    except Exception:
                        self._logger.exception("error closing socket during subscribe rollback")
                raise
        return handle

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._scheduler.aclose()
        self._registry.end_all()
        await self._connection.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def _open_connection(self) -> ConnectResult:
        return await self._connection.connect(
            url=self._url,
            on_message=self._on_message,
            on_connection_lost=self._on_socket_connection_lost,
            on_error=self._on_socket_error,
        )

    async def _on_handle_close(self, handle: AsyncSubscriptionHandle[SportsEvent]) -> None:
        async with self._send_lock:
            removed = self._registry.remove_handle(handle)
            if not removed:
                return
            if self._registry.is_empty:
                self._scheduler.cancel_pending()
                await self._connection.close()

    def _on_message(self, raw: object) -> None:
        try:
            event = parse_sports_event(raw)
        except ValidationError:
            self._dropped_events += 1
            self._logger.debug("dropped malformed sports event")
            return
        self._registry.dispatch(event)

    def _on_socket_connection_lost(self, code: int, reason: str) -> None:
        if self._closed:
            return
        self._scheduler.schedule(
            reconnect=self._reconnect,
            should_reconnect=self._should_reconnect,
        )

    def _on_socket_error(self, exc: BaseException) -> None:
        self._logger.warning("sports stream reader error: %r", exc)

    def _should_reconnect(self) -> bool:
        return not self._closed and not self._registry.is_empty

    async def _reconnect(self) -> None:
        # Lock serializes against subscribe(); sports has no initial frame
        # to send so this is mostly defensive.
        async with self._send_lock:
            if not self._should_reconnect():
                return
            try:
                await self._open_connection()
            except TransportError as exc:
                self._logger.info("sports stream reconnect failed: %r; rescheduling", exc)
                self._scheduler.schedule(
                    reconnect=self._reconnect,
                    should_reconnect=self._should_reconnect,
                )
                return
            if self._closed:
                with contextlib.suppress(Exception):
                    await self._connection.close()
                return
            self._scheduler.reset()
