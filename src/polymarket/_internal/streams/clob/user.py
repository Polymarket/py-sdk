# pyright: reportPrivateUsage=false
import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from types import TracebackType
from typing import Self, cast

from polymarket._internal.gateway_session import AsyncGatewaySession
from polymarket._internal.socket_auth import SocketAuthentication
from polymarket._internal.streams.clob.heartbeat import ClobWebSocketHeartbeat
from polymarket._internal.streams.clob.user_protocol import (
    UserServerState,
    UserSubscription,
    build_initial_frame,
    derive_state,
    diff_state_frames,
    matcher_for,
)
from polymarket._internal.streams.handle import AsyncSubscriptionHandle
from polymarket._internal.streams.reconnect import ReconnectScheduler
from polymarket._internal.streams.registry import SubscriptionRegistry
from polymarket._internal.ws.connection import AsyncWebSocketConnection, ConnectResult
from polymarket._internal.ws.heartbeat import Heartbeat
from polymarket.auth import BearerCredentials
from polymarket.errors import RequestRejectedError, TransportError, UserInputError
from polymarket.models import ApiKeyCreds
from polymarket.models.clob.user_events import UserEvent, parse_user_events

DEFAULT_QUEUE_SIZE = 1024

ApiKeyCredsResolver = Callable[[], Awaitable[ApiKeyCreds | BearerCredentials]]


class ClobUserStreamManager:
    def __init__(
        self,
        *,
        url: str,
        resolve_credentials: ApiKeyCredsResolver,
        session: AsyncGatewaySession | None = None,
        logger: logging.Logger | None = None,
        heartbeat: Heartbeat | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self._url = url
        self._resolve_credentials = resolve_credentials
        self._logger = logger or logging.getLogger("polymarket.streams.clob.user")
        self._heartbeat: Heartbeat = heartbeat or ClobWebSocketHeartbeat()
        self._queue_size = queue_size
        self._connection = AsyncWebSocketConnection(heartbeat=self._heartbeat, logger=self._logger)
        self._registry: SubscriptionRegistry[UserSubscription, UserEvent, UserServerState] = (
            SubscriptionRegistry(derive_state=derive_state, logger=self._logger)
        )
        self._scheduler = ReconnectScheduler(logger=self._logger)
        self._send_lock = asyncio.Lock()
        self._closed = False
        self._dropped_events = 0
        self._auth_failures = 0
        self._authentication = (
            SocketAuthentication(
                session=session, protocol="clob", send=self._connection.send, expire=self._expired
            )
            if session is not None
            else None
        )

    @property
    def is_open(self) -> bool:
        return self._connection.is_open

    @property
    def dropped_events(self) -> int:
        return self._dropped_events

    async def subscribe(
        self,
        *,
        markets: Iterable[str] | None = None,
    ) -> AsyncSubscriptionHandle[UserEvent]:
        if self._closed:
            raise RuntimeError("ClobUserStreamManager is closed")
        normalized_markets: tuple[str, ...] = ()
        if markets is not None:
            if isinstance(markets, str | bytes):
                raise UserInputError(
                    "markets must be a sequence of market ids, not a single string"
                )
            collected: list[str] = []
            for m in markets:
                if not isinstance(m, str):  # pyright: ignore[reportUnnecessaryIsInstance]
                    raise UserInputError(f"market must be a string, got {type(m).__name__}")
                if not m:
                    raise UserInputError("market must be non-empty")
                collected.append(m)
            normalized_markets = tuple(collected)

        sub = UserSubscription(markets=normalized_markets)
        matcher = matcher_for(sub)
        handle: AsyncSubscriptionHandle[UserEvent] = AsyncSubscriptionHandle(
            queue_size=self._queue_size
        )
        handle._bind_close(self._on_handle_close)

        async with self._send_lock:
            before = self._registry.server_state()
            self._registry.add(sub=sub, matcher=matcher, handle=handle)
            after = self._registry.server_state()
            try:
                result = await self._open_connection()
                if result.reused:
                    for frame in diff_state_frames(before, after):
                        await self._connection.send(frame)
                else:
                    self._scheduler.cancel_pending()
                    credentials = await self._resolve_credentials()
                    if self._authentication is not None:
                        await self._authentication.initial(build_initial_frame(after, credentials))
                    else:
                        await self._connection.send(build_initial_frame(after, credentials))
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
        if self._authentication is not None:
            await self._authentication.close()
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

    async def _on_handle_close(self, handle: AsyncSubscriptionHandle[UserEvent]) -> None:
        async with self._send_lock:
            before = self._registry.server_state()
            removed = self._registry.remove_handle(handle)
            if not removed:
                return
            if self._registry.is_empty:
                self._scheduler.cancel_pending()
                if self._authentication is not None:
                    self._authentication.disconnected()
                await self._connection.close()
                return
            after = self._registry.server_state()
            for frame in diff_state_frames(before, after):
                if not await self._connection.send(frame):
                    return

    def _on_message(self, raw: object) -> None:
        if self._authentication is not None and self._authentication.message(raw):
            if isinstance(raw, dict) and cast(dict[str, object], raw).get("success") is True:
                self._auth_failures = 0
            return
        events, dropped = parse_user_events(raw)
        if dropped:
            self._dropped_events += dropped
            self._logger.debug("dropped %d malformed user event(s)", dropped)
        if events:
            self._auth_failures = 0
        for event in events:
            self._registry.dispatch(event)

    def _on_socket_connection_lost(self, code: int, reason: str) -> None:
        if self._authentication is not None:
            self._authentication.disconnected()
        if self._closed:
            return
        if self._authentication is not None:
            if code == 1008 and reason == "authentication failed":
                self._scheduler.cancel_pending()
                self._registry.end_all(
                    RequestRejectedError(
                        "Socket authentication rejected", status=401, code="auth_invalid"
                    )
                )
                return
            if code == 1013:
                self._auth_failures += 1
                if self._auth_failures >= 3:
                    self._scheduler.cancel_pending()
                    self._registry.end_all(
                        RequestRejectedError(
                            "Socket authentication unavailable", status=503, code="auth_unavailable"
                        )
                    )
                    return
        self._scheduler.schedule(
            reconnect=self._reconnect,
            should_reconnect=self._should_reconnect,
        )

    async def _expired(self) -> None:
        await self._connection.close()
        self._on_socket_connection_lost(1008, "authentication expired")

    def _on_socket_error(self, exc: BaseException) -> None:
        self._logger.warning("user stream reader error: %r", exc)

    def _should_reconnect(self) -> bool:
        return not self._closed and not self._registry.is_empty

    async def _reconnect(self) -> None:
        async with self._send_lock:
            if not self._should_reconnect():
                return
            try:
                result = await self._open_connection()
            except TransportError as exc:
                self._logger.info("user stream reconnect failed: %r; rescheduling", exc)
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
            try:
                credentials = await self._resolve_credentials()
            except Exception:
                self._logger.exception("user stream credential resolution failed on reconnect")
                await self._connection.close()
                self._scheduler.schedule(
                    reconnect=self._reconnect,
                    should_reconnect=self._should_reconnect,
                )
                return
            state = self._registry.server_state()
            if self._authentication is not None:
                await self._authentication.initial(build_initial_frame(state, credentials))
            else:
                await self._connection.send(build_initial_frame(state, credentials))
