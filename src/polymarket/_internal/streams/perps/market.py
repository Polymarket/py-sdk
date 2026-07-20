# pyright: reportPrivateUsage=false
import asyncio
import logging
from types import TracebackType
from typing import Self

from polymarket._internal.streams.handle import AsyncSubscriptionHandle
from polymarket._internal.streams.perps.heartbeat import PerpsWebSocketHeartbeat
from polymarket._internal.streams.perps.market_protocol import (
    PerpsServerState,
    build_channel_frame,
    derive_state,
    diff_channels,
    match_for,
    parse_events,
)
from polymarket._internal.streams.reconnect import ReconnectScheduler
from polymarket._internal.streams.registry import SubscriptionRegistry
from polymarket._internal.ws.connection import AsyncWebSocketConnection, ConnectResult
from polymarket._internal.ws.heartbeat import Heartbeat
from polymarket.errors import TransportError
from polymarket.models.perps.events import PerpsMarketEvent
from polymarket.streams._specs import PerpsSpec

DEFAULT_QUEUE_SIZE = 1024


class PerpsMarketStreamManager:
    """Perps market data WebSocket stream. Multiplexes many subscriptions onto
    one socket and resends the subscribed channels on reconnect."""

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
        self._logger = logger or logging.getLogger("polymarket.streams.perps.market")
        self._heartbeat: Heartbeat = heartbeat or PerpsWebSocketHeartbeat()
        self._queue_size = queue_size
        self._connection = AsyncWebSocketConnection(heartbeat=self._heartbeat, logger=self._logger)
        self._registry: SubscriptionRegistry[PerpsSpec, PerpsMarketEvent, PerpsServerState] = (
            SubscriptionRegistry(derive_state=derive_state, logger=self._logger)
        )
        self._scheduler = ReconnectScheduler(logger=self._logger)
        self._send_lock = asyncio.Lock()
        self._next_request_id = 1
        self._closed = False
        self._dropped_events = 0

    @property
    def is_open(self) -> bool:
        return self._connection.is_open

    @property
    def dropped_events(self) -> int:
        return self._dropped_events

    async def subscribe(self, spec: PerpsSpec) -> AsyncSubscriptionHandle[PerpsMarketEvent]:
        if self._closed:
            raise RuntimeError("PerpsMarketStreamManager is closed")
        handle: AsyncSubscriptionHandle[PerpsMarketEvent] = AsyncSubscriptionHandle(
            queue_size=self._queue_size
        )
        handle._bind_close(self._on_handle_close)

        async with self._send_lock:
            before = self._registry.server_state()
            self._registry.add(sub=spec, matcher=match_for(spec), handle=handle)
            after = self._registry.server_state()
            try:
                result = await self._open_connection()
                if result.reused:
                    added, removed = diff_channels(before, after)
                    await self._send_channel_frames(added, removed)
                else:
                    self._scheduler.cancel_pending()
                    await self._send_subscribe(sorted(after))
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

    async def _send_channel_frames(self, added: list[str], removed: list[str]) -> None:
        if added:
            await self._send_subscribe(added)
        if removed:
            await self._send_unsubscribe(removed)

    async def _send_subscribe(self, channels: list[str]) -> bool:
        if not channels:
            return True
        return await self._connection.send(
            build_channel_frame(
                request_id=self._take_request_id(), operation="sub", channels=channels
            )
        )

    async def _send_unsubscribe(self, channels: list[str]) -> bool:
        if not channels:
            return True
        return await self._connection.send(
            build_channel_frame(
                request_id=self._take_request_id(), operation="unsub", channels=channels
            )
        )

    def _take_request_id(self) -> int:
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id

    async def _on_handle_close(self, handle: AsyncSubscriptionHandle[PerpsMarketEvent]) -> None:
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
            added_channels, removed_channels = diff_channels(before, after)
            await self._send_channel_frames(added_channels, removed_channels)

    def _on_message(self, raw: object) -> None:
        events, dropped = parse_events(raw)
        if dropped:
            self._dropped_events += dropped
            self._logger.debug("dropped %d malformed perps market event(s)", dropped)
        for event in events:
            self._registry.dispatch(event)

    def _on_socket_connection_lost(self, code: int, reason: str) -> None:
        if self._closed:
            return
        self._scheduler.schedule(
            reconnect=self._reconnect,
            should_reconnect=self._should_reconnect,
        )

    def _on_socket_error(self, exc: BaseException) -> None:
        self._logger.warning("perps market stream reader error: %r", exc)

    def _should_reconnect(self) -> bool:
        return not self._closed and not self._registry.is_empty

    async def _reconnect(self) -> None:
        async with self._send_lock:
            if not self._should_reconnect():
                return
            try:
                result = await self._open_connection()
            except TransportError as exc:
                self._logger.info("perps market stream reconnect failed: %r; rescheduling", exc)
                self._scheduler.schedule(
                    reconnect=self._reconnect,
                    should_reconnect=self._should_reconnect,
                )
                return
            if self._closed:
                await self._connection.close()
                return
            if result.reused:
                return
            self._scheduler.reset()
            state = self._registry.server_state()
            if state:
                await self._send_subscribe(sorted(state))
