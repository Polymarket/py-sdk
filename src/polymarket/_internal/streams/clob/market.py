# pyright: reportPrivateUsage=false
import asyncio
import logging
from collections.abc import Iterable
from types import TracebackType
from typing import Self

from polymarket._internal.streams.clob.heartbeat import ClobWebSocketHeartbeat
from polymarket._internal.streams.clob.market_protocol import (
    MarketServerState,
    MarketSubscription,
    build_initial_frame,
    derive_state,
    diff_state_frames,
    match_for,
    parse_events,
)
from polymarket._internal.streams.handle import AsyncSubscriptionHandle
from polymarket._internal.streams.reconnect import ReconnectScheduler
from polymarket._internal.streams.registry import SubscriptionRegistry
from polymarket._internal.ws.connection import AsyncWebSocketConnection, ConnectResult
from polymarket._internal.ws.heartbeat import Heartbeat
from polymarket.errors import TransportError, UserInputError
from polymarket.models.clob.market_events import MarketEvent
from polymarket.models.types import TokenId

DEFAULT_QUEUE_SIZE = 1024


class ClobMarketStreamManager:
    """CLOB market WebSocket stream. Multiplexes many subscriptions onto
    one socket and resends state on reconnect."""

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
        self._logger = logger or logging.getLogger("polymarket.streams.clob.market")
        self._heartbeat: Heartbeat = heartbeat or ClobWebSocketHeartbeat()
        self._queue_size = queue_size
        self._connection = AsyncWebSocketConnection(heartbeat=self._heartbeat, logger=self._logger)
        self._registry: SubscriptionRegistry[MarketSubscription, MarketEvent, MarketServerState] = (
            SubscriptionRegistry(derive_state=derive_state, logger=self._logger)
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

    async def subscribe(
        self,
        *,
        token_ids: Iterable[str],
        custom_feature_enabled: bool = False,
    ) -> AsyncSubscriptionHandle[MarketEvent]:
        if self._closed:
            raise RuntimeError("ClobMarketStreamManager is closed")
        if not isinstance(custom_feature_enabled, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise UserInputError("custom_feature_enabled must be a bool")
        if isinstance(token_ids, str | bytes):
            raise UserInputError("token_ids must be a sequence of token ids, not a single string")
        ids: list[TokenId] = []
        for tid in token_ids:
            if not isinstance(tid, str):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise UserInputError(f"token_id must be a string, got {type(tid).__name__}")
            if not tid:
                raise UserInputError("token_id must be non-empty")
            ids.append(TokenId(tid))
        if not ids:
            raise UserInputError("token_ids must be a non-empty sequence")
        sub = MarketSubscription(
            token_ids=tuple(ids), custom_feature_enabled=custom_feature_enabled
        )
        matcher = match_for(sub)
        handle: AsyncSubscriptionHandle[MarketEvent] = AsyncSubscriptionHandle(
            queue_size=self._queue_size
        )
        handle._bind_close(self._on_handle_close)

        async with self._send_lock:
            before = self._registry.server_state()
            self._registry.add(sub=sub, matcher=matcher, handle=handle)
            after = self._registry.server_state()
            try:
                # connect() short-circuits any pending reconnect backoff.
                result = await self._open_connection()
                if result.reused:
                    for frame in diff_state_frames(before, after):
                        await self._connection.send(frame)
                else:
                    self._scheduler.cancel_pending()
                    await self._connection.send(build_initial_frame(after))
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

    async def _on_handle_close(self, handle: AsyncSubscriptionHandle[MarketEvent]) -> None:
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
        events, dropped = parse_events(raw)
        if dropped:
            self._dropped_events += dropped
            self._logger.debug("dropped %d malformed market event(s)", dropped)
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
        self._logger.warning("market stream reader error: %r", exc)

    def _should_reconnect(self) -> bool:
        return not self._closed and not self._registry.is_empty

    async def _reconnect(self) -> None:
        # Lock serializes the initial-frame send against subscribe().
        async with self._send_lock:
            # close() can fire after the scheduler invoked us but before we
            # got the lock; the scheduler cannot cancel an in-flight callback.
            if not self._should_reconnect():
                return
            try:
                result = await self._open_connection()
            except TransportError as exc:
                self._logger.info("market stream reconnect failed: %r; rescheduling", exc)
                self._scheduler.schedule(
                    reconnect=self._reconnect,
                    should_reconnect=self._should_reconnect,
                )
                return
            if self._closed:
                # close() raced past the pre-open guard while connect awaited.
                await self._connection.close()
                return
            if result.reused:
                return
            self._scheduler.reset()
            state = self._registry.server_state()
            if state.asset_ids:
                await self._connection.send(build_initial_frame(state))
