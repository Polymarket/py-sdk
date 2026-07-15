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
from polymarket._internal.streams.rtds.heartbeat import RtdsWebSocketHeartbeat
from polymarket._internal.streams.rtds.protocol import (
    RtdsServerSubscription,
    build_subscribe_frame,
    derive_state,
    diff_state_frames,
    matcher_for,
)
from polymarket._internal.ws.connection import AsyncWebSocketConnection, ConnectResult
from polymarket._internal.ws.heartbeat import Heartbeat
from polymarket.errors import TransportError
from polymarket.models.rtds_events import RtdsEvent, parse_rtds_event
from polymarket.streams._specs import RtdsSpec

DEFAULT_QUEUE_SIZE = 1024


class RtdsStreamManager:
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
        self._logger = logger or logging.getLogger("polymarket.streams.rtds")
        self._heartbeat: Heartbeat = heartbeat or RtdsWebSocketHeartbeat()
        self._queue_size = queue_size
        self._connection = AsyncWebSocketConnection(heartbeat=self._heartbeat, logger=self._logger)
        self._registry: SubscriptionRegistry[
            RtdsSpec, RtdsEvent, dict[str, RtdsServerSubscription]
        ] = SubscriptionRegistry(derive_state=derive_state, logger=self._logger)
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

    async def subscribe(self, spec: RtdsSpec) -> AsyncSubscriptionHandle[RtdsEvent]:
        if self._closed:
            raise RuntimeError("RtdsStreamManager is closed")
        handle: AsyncSubscriptionHandle[RtdsEvent] = AsyncSubscriptionHandle(
            queue_size=self._queue_size
        )
        handle._bind_close(self._on_handle_close)
        matcher = matcher_for(spec)

        async with self._send_lock:
            before = self._registry.server_state()
            self._registry.add(sub=spec, matcher=matcher, handle=handle)
            after = self._registry.server_state()
            try:
                result = await self._open_connection()
                if result.reused:
                    for frame in diff_state_frames(before, after):
                        await self._connection.send(frame)
                else:
                    self._scheduler.cancel_pending()
                    if after:
                        await self._connection.send(build_subscribe_frame(after.values()))
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

    async def _on_handle_close(self, handle: AsyncSubscriptionHandle[RtdsEvent]) -> None:
        async with self._send_lock:
            before = self._registry.server_state()
            removed = self._registry.remove_handle(handle)
            if not removed:
                return
            if self._registry.is_empty:
                self._scheduler.cancel_pending()
                await self._connection.close()
                return
            after = self._registry.server_state()
            for frame in diff_state_frames(before, after):
                if not await self._connection.send(frame):
                    return

    def _on_message(self, raw: object) -> None:
        try:
            event = parse_rtds_event(raw)
        except (ValueError, ValidationError):
            self._dropped_events += 1
            self._logger.debug("dropped malformed RTDS event")
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
        self._logger.warning("RTDS stream reader error: %r", exc)

    def _should_reconnect(self) -> bool:
        return not self._closed and not self._registry.is_empty

    async def _reconnect(self) -> None:
        async with self._send_lock:
            if not self._should_reconnect():
                return
            try:
                result = await self._open_connection()
            except TransportError as exc:
                self._logger.info("RTDS reconnect failed: %r; rescheduling", exc)
                self._scheduler.schedule(
                    reconnect=self._reconnect,
                    should_reconnect=self._should_reconnect,
                )
                return
            if self._closed:
                with contextlib.suppress(Exception):
                    await self._connection.close()
                return
            if result.reused:
                return
            self._scheduler.reset()
            state = self._registry.server_state()
            if state:
                await self._connection.send(build_subscribe_frame(state.values()))
