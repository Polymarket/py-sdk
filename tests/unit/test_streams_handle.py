# pyright: reportPrivateUsage=false
import asyncio

import pytest

from polymarket._internal.streams.handle import AsyncSubscriptionHandle
from polymarket._internal.streams.merged_handle import MergedSubscriptionHandle
from polymarket.errors import ConnectionLostError


def test_async_iteration_yields_pushed_events() -> None:
    async def run() -> list[int]:
        handle: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        handle._push(1)
        handle._push(2)
        handle._end()
        collected: list[int] = []
        async for event in handle:
            collected.append(event)
        return collected

    assert asyncio.run(run()) == [1, 2]


def test_drop_oldest_when_queue_full_and_counter_increments() -> None:
    async def run() -> tuple[list[int], int]:
        handle: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=3)
        handle._push(1)
        handle._push(2)
        handle._push(3)
        handle._push(4)  # drops 1
        handle._push(5)  # drops 2
        # consume one before ending so the end sentinel fits without dropping more.
        first = await handle.__aiter__().__anext__()
        handle._end()
        collected: list[int] = [first]
        async for event in handle:
            collected.append(event)
        return collected, handle.dropped

    items, dropped = asyncio.run(run())
    assert items == [3, 4, 5]
    assert dropped == 2


def test_end_with_error_raises_in_iteration() -> None:
    async def run() -> None:
        handle: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        handle._push(1)
        handle._end(RuntimeError("boom"))
        first = await handle.__aiter__().__anext__()
        assert first == 1
        with pytest.raises(RuntimeError, match="boom"):
            await handle.__aiter__().__anext__()

    asyncio.run(run())


def test_merged_terminal_error_closes_live_sibling_and_reaches_consumer() -> None:
    async def run() -> None:
        failed: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        live: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        sibling_closed = asyncio.Event()

        async def close_sibling(_: AsyncSubscriptionHandle[int]) -> None:
            sibling_closed.set()

        live._bind_close(close_sibling)
        merged = MergedSubscriptionHandle([failed, live])
        failure = ConnectionLostError("session expired", code=4001, reason="expired")
        failed._end(failure)
        with pytest.raises(ConnectionLostError) as caught:
            await asyncio.wait_for(anext(merged), 1)
        assert caught.value is failure
        await asyncio.wait_for(sibling_closed.wait(), 1)
        await merged.close()
        with pytest.raises(StopAsyncIteration):
            await anext(live)

    asyncio.run(run())


def test_close_is_idempotent_under_concurrent_callers() -> None:
    closes: list[int] = []

    async def on_close(_h: AsyncSubscriptionHandle[int]) -> None:
        closes.append(1)

    async def run() -> int:
        handle: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        handle._bind_close(on_close)
        await asyncio.gather(handle.close(), handle.close(), handle.close())
        return len(closes)

    assert asyncio.run(run()) == 1


def test_async_context_manager_calls_close_on_exit() -> None:
    closes: list[int] = []

    async def on_close(_h: AsyncSubscriptionHandle[int]) -> None:
        closes.append(1)

    async def run() -> None:
        handle: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        handle._bind_close(on_close)
        async with handle:
            handle._push(7)

    asyncio.run(run())
    assert closes == [1]


def test_push_after_end_is_a_noop() -> None:
    async def run() -> list[int]:
        handle: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        handle._end()
        handle._push(99)
        collected: list[int] = []
        async for event in handle:
            collected.append(event)
        return collected

    assert asyncio.run(run()) == []


def test_invalid_queue_size_raises() -> None:
    with pytest.raises(ValueError, match="queue_size"):
        AsyncSubscriptionHandle[int](queue_size=0)


def test_explicit_close_discards_buffered_events_and_iteration_remains_terminal() -> None:
    async def run() -> None:
        handle: AsyncSubscriptionHandle[int] = AsyncSubscriptionHandle(queue_size=4)
        handle._push(1)
        handle._push(2)
        await handle.close()
        for _ in range(2):
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(handle), 1)

    asyncio.run(run())
