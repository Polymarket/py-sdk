from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType
from typing import Generic, Protocol, Self, TypeVar, runtime_checkable

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


@runtime_checkable
class SubscriptionHandle(Protocol[T_co]):
    """Public protocol: async-iterable events with an idempotent close()."""

    def __aiter__(self) -> AsyncIterator[T_co]: ...
    async def __anext__(self) -> T_co: ...
    async def close(self) -> None: ...
    async def __aenter__(self) -> SubscriptionHandle[T_co]: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class _EndSentinel:
    __slots__ = ()


_END = _EndSentinel()


class AsyncSubscriptionHandle(Generic[T]):
    """Async-iterable handle for one stream subscription.

    Bounded queue with drop-oldest backpressure; ``dropped`` counts losses.
    Idempotent ``close()``.
    """

    def __init__(self, *, queue_size: int) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self._queue: asyncio.Queue[T | _EndSentinel] = asyncio.Queue(maxsize=queue_size)
        self._ended = False
        self._dropped = 0
        self._end_error: BaseException | None = None
        self._closing: asyncio.Task[None] | None = None
        self._on_close: Callable[[AsyncSubscriptionHandle[T]], Awaitable[None]] | None = None

    @property
    def dropped(self) -> int:
        return self._dropped

    def _bind_close(
        self, on_close: Callable[[AsyncSubscriptionHandle[T]], Awaitable[None]]
    ) -> None:
        self._on_close = on_close

    def _push(self, event: T) -> None:
        if self._ended:
            return
        try:
            self._queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass
        try:
            self._queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        else:
            self._dropped += 1
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1

    def _end(self, error: BaseException | None = None, *, discard_pending: bool = False) -> None:
        if discard_pending:
            while not self._queue.empty():
                self._queue.get_nowait()
        if self._ended:
            if discard_pending:
                self._queue.put_nowait(_END)
            return
        self._ended = True
        self._end_error = error
        try:
            self._queue.put_nowait(_END)
            return
        except asyncio.QueueFull:
            pass
        # Make room for the end sentinel.
        try:
            self._queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        else:
            self._dropped += 1
        self._queue.put_nowait(_END)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        if self._ended and self._queue.empty():
            if self._end_error is not None:
                raise self._end_error
            raise StopAsyncIteration
        item = await self._queue.get()
        if isinstance(item, _EndSentinel):
            if self._end_error is not None:
                raise self._end_error
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        if self._closing is None:
            self._closing = asyncio.create_task(self._do_close())
        await asyncio.shield(self._closing)

    async def _do_close(self) -> None:
        on_close = self._on_close
        self._on_close = None
        if on_close is not None:
            # Best-effort: close() must always leave the handle terminal.
            with contextlib.suppress(Exception):
                await on_close(self)
        self._end(discard_pending=True)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
