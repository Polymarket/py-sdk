# pyright: reportPrivateUsage=false
import asyncio
import logging
from collections.abc import Callable, Mapping

from polymarket._internal.streams.handle import AsyncSubscriptionHandle
from polymarket._internal.streams.realtime.protocol import PriceKey, subscriptions_for
from polymarket._internal.streams.realtime.session import PriceListener, PriceSession
from polymarket._internal.streams.realtime.socket import PriceConnection
from polymarket.errors import TransportError
from polymarket.models.clob.api_key import ApiKeyCreds
from polymarket.models.price_events import PriceEvent
from polymarket.streams._specs import EquityPriceSpec, PriceSpec


class RealtimeStreamManager:
    """Pool shared price filters, with at most 64 new filters per connection."""

    def __init__(
        self,
        *,
        url: str,
        credentials: ApiKeyCreds,
        headers: Mapping[str, str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._url, self._credentials, self._headers, self._logger = (
            url,
            credentials,
            headers,
            logger,
        )
        self._sessions: list[PriceSession] = []
        self._handles: set[AsyncSubscriptionHandle[PriceEvent]] = set()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None

    def _place(self, key: PriceKey) -> PriceSession:
        self._sessions = [session for session in self._sessions if not session.closed]
        for session in self._sessions:
            if session.has(key):
                return session
        for session in self._sessions:
            if session.size < session.key_target:
                return session
        session = PriceSession(
            PriceConnection(
                url=self._url,
                credentials=self._credentials,
                headers=self._headers,
                logger=self._logger,
            )
        )
        self._sessions.append(session)
        return session

    async def subscribe(self, spec: PriceSpec) -> AsyncSubscriptionHandle[PriceEvent]:
        if self._closed:
            raise TransportError("Realtime streams are closed")
        handle: AsyncSubscriptionHandle[PriceEvent] = AsyncSubscriptionHandle(queue_size=1024)
        self._handles.add(handle)
        releases: list[Callable[[], None]] = []
        active = True

        def release() -> None:
            nonlocal active
            if not active:
                return
            active = False
            for remove in releases:
                remove()
            self._handles.discard(handle)

        async def close(_: AsyncSubscriptionHandle[PriceEvent]) -> None:
            release()

        def event(value: PriceEvent) -> None:
            if active and not (
                isinstance(spec, EquityPriceSpec) and spec.types and value.type not in spec.types
            ):
                handle._push(value)

        def end(error: Exception) -> None:
            handle._end(error)
            release()

        handle._bind_close(close)
        listener = PriceListener(event, end)
        waits: list[asyncio.Future[None]] = []
        try:
            for key in subscriptions_for(spec):
                session = self._place(key)
                # Capture each placement before registering the next filter.
                releases.append(lambda session=session, key=key: session.remove(key, listener))
                waits.append(asyncio.ensure_future(session.add(key, listener)))
            await asyncio.gather(*waits)
        except BaseException:
            release()
            for wait in waits:
                wait.cancel()
            await asyncio.gather(*waits, return_exceptions=True)
            await handle.close()
            raise
        return handle

    async def close(self) -> None:
        if self._closing is None:
            self._closed = True
            self._closing = asyncio.create_task(self._shutdown())
        await asyncio.shield(self._closing)

    async def _shutdown(self) -> None:
        await asyncio.gather(*(handle.close() for handle in tuple(self._handles)))
        await asyncio.gather(*(session.close() for session in self._sessions))
        self._sessions.clear()
