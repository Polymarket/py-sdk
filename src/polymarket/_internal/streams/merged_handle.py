# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from types import TracebackType
from typing import Generic, Self, TypeVar

from polymarket._internal.streams.handle import AsyncSubscriptionHandle

T = TypeVar("T")

DEFAULT_MERGED_QUEUE_SIZE = 1024


class _MergedEnd:
    __slots__ = ()


_MERGED_END = _MergedEnd()


class MergedSubscriptionHandle(Generic[T]):
    """Merges N AsyncSubscriptionHandles into a single async iterable.

    Bounded queue with drop-oldest backpressure (mirrors per-handle policy).
    Preserves the first child error and re-raises it at end-of-stream.
    """

    def __init__(
        self,
        handles: Sequence[AsyncSubscriptionHandle[T]],
        *,
        queue_size: int = DEFAULT_MERGED_QUEUE_SIZE,
    ) -> None:
        if not handles:
            raise ValueError("MergedSubscriptionHandle requires at least one handle")
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self._handles: list[AsyncSubscriptionHandle[T]] = list(handles)
        self._queue: asyncio.Queue[T | _MergedEnd] = asyncio.Queue(maxsize=queue_size)
        self._closing: asyncio.Task[None] | None = None
        self._closed = False
        self._open = len(self._handles)
        self._dropped = 0
        self._first_error: BaseException | None = None
        self._pumps: list[asyncio.Task[None]] = [
            asyncio.create_task(self._pump(h)) for h in self._handles
        ]

    @property
    def dropped(self) -> int:
        return self._dropped

    async def _pump(self, handle: AsyncSubscriptionHandle[T]) -> None:
        try:
            async for event in handle:
                self._put_or_drop(event)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            if self._first_error is None:
                self._first_error = exc
                # A failed child must not wait for unrelated, potentially infinite
                # streams to finish before exposing its terminal error.
                if self._closing is None:
                    self._closing = asyncio.create_task(self._do_close())
        finally:
            self._open -= 1
            if self._open == 0:
                self._enqueue_end()

    def _put_or_drop(self, event: T) -> None:
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

    def _enqueue_end(self) -> None:
        try:
            self._queue.put_nowait(_MERGED_END)
            return
        except asyncio.QueueFull:
            pass
        try:
            self._queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        else:
            self._dropped += 1
        self._queue.put_nowait(_MERGED_END)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        if self._closed or (self._open == 0 and self._queue.empty()):
            if self._first_error is not None:
                raise self._first_error
            raise StopAsyncIteration
        item = await self._queue.get()
        if isinstance(item, _MergedEnd):
            if self._first_error is not None:
                raise self._first_error
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        if self._closing is None:
            self._closing = asyncio.create_task(self._do_close())
        await asyncio.shield(self._closing)

    async def _do_close(self) -> None:
        results = await asyncio.gather(*(h.close() for h in self._handles), return_exceptions=True)
        for pump in self._pumps:
            if not pump.done():
                pump.cancel()
        for pump in self._pumps:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pump
        self._closed = True
        while not self._queue.empty():
            self._queue.get_nowait()
        self._enqueue_end()
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, Exception):
                raise result

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()


__all__ = ["MergedSubscriptionHandle"]
