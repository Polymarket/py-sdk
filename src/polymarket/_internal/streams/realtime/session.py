import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from polymarket._internal.streams.realtime.protocol import (
    PriceKey,
    reconnect_delay,
    refresh_snapshot,
)
from polymarket._internal.streams.realtime.socket import Operation, PriceConnection
from polymarket.errors import ConnectionLostError, RequestRejectedError, TransportError
from polymarket.models.price_events import PriceEvent

ACCEPTANCE_TIMEOUT_S = 30.0
IDLE_TIMEOUT_S = 1.0


@dataclass(eq=False, slots=True)
class PriceListener:
    event: Callable[[PriceEvent], None]
    end: Callable[[Exception], None]


def _ready_future() -> asyncio.Future[None]:
    future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    # A shared key can lose its final listener before an operation finishes.
    future.add_done_callback(lambda result: None if result.cancelled() else result.exception())
    return future


@dataclass(eq=False, slots=True)
class _KeyState:
    key: PriceKey
    ready: asyncio.Future[None] = field(default_factory=_ready_future)
    listeners: set[PriceListener] = field(default_factory=set[PriceListener])
    accepted: bool = False
    snapshot: PriceEvent | None = None


class PriceSession:
    """Own shared key acceptance, ordered operations, and reconnect recovery.

    One worker serializes connection teardown, authentication and subscription
    changes. Listener registration/removal is synchronous within the event loop.
    """

    def __init__(self, connection: PriceConnection) -> None:
        self._connection = connection
        self._keys: dict[PriceKey, _KeyState] = {}
        self._ops: deque[tuple[Operation, list[_KeyState]]] = deque()
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._idle: asyncio.TimerHandle | None = None
        self._closing: asyncio.Task[None] | None = None
        self._authenticated = False
        self._lost: ConnectionLostError | None = None
        self._attempt = 0
        self._key_target = 64
        self._last_drop = float("-inf")
        self.closed = False

    @property
    def size(self) -> int:
        return len(self._keys)

    @property
    def key_target(self) -> int:
        return 64 if time.monotonic() - self._last_drop >= 60 else self._key_target

    def has(self, key: PriceKey) -> bool:
        return key in self._keys

    def add(self, key: PriceKey, listener: PriceListener) -> Awaitable[None]:
        if self.closed:
            raise TransportError("Realtime session is closed")
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        state = self._keys.get(key)
        if state is None:
            state = _KeyState(key)
            self._keys[key] = state
            if self._authenticated:
                self._enqueue("subscribe", [state])
        state.listeners.add(listener)
        if state.snapshot is not None:
            listener.event(state.snapshot)
        self._wake.set()
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())
        return self._await_acceptance(state.ready)

    async def _await_acceptance(self, ready: asyncio.Future[None]) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(ready), ACCEPTANCE_TIMEOUT_S)
        except TimeoutError as error:
            raise TransportError(
                "Realtime subscription was not accepted within 30 seconds"
            ) from error

    def remove(self, key: PriceKey, listener: PriceListener) -> None:
        state = self._keys.get(key)
        if state is None:
            return
        state.listeners.discard(listener)
        if state.listeners:
            return
        del self._keys[key]
        if not state.ready.done():
            state.ready.set_exception(TransportError("Realtime subscription closed"))
        if self._authenticated:
            self._enqueue("unsubscribe", [state])
        self._schedule_idle()

    def _schedule_idle(self) -> None:
        if not self._keys and self._idle is None and not self.closed:
            self._idle = asyncio.get_running_loop().call_later(IDLE_TIMEOUT_S, self._start_close)

    def _start_close(self) -> None:
        if self._closing is None:
            self.closed = True
            self._closing = asyncio.create_task(self._shutdown())

    def _enqueue(self, op: Operation, states: Sequence[_KeyState]) -> None:
        if not states:
            return
        if self._ops and self._ops[-1][0] == op:
            self._ops[-1][1].extend(states)
        else:
            self._ops.append((op, list(states)))
        self._wake.set()

    def _reset(self) -> None:
        self._authenticated = False
        self._ops.clear()
        for state in self._keys.values():
            state.snapshot = None
            if state.ready.done():
                state.ready = _ready_future()

    def _disconnected(self, error: ConnectionLostError) -> None:
        if self.closed:
            return
        self._lost = error
        self._reset()
        self._wake.set()

    def _event(self, event: PriceEvent) -> None:
        state = self._keys.get(PriceKey(event.topic, event.payload.symbol))
        if state is None:
            return
        state.snapshot = refresh_snapshot(state.snapshot, event)
        for listener in tuple(state.listeners):
            listener.event(event)

    def _dropped(self) -> None:
        now = time.monotonic()
        if now - self._last_drop >= 5:
            self._key_target = max(1, self.key_target // 2)
            self._last_drop = now

    def _reject(
        self,
        states: Sequence[_KeyState],
        error: Exception,
        *,
        unsubscribe: bool = True,
    ) -> None:
        current = [state for state in states if self._keys.get(state.key) is state]
        # Closing one multi-key handle may remove other listeners. Capture fanout first.
        listeners = {listener for state in current for listener in state.listeners}
        for state in current:
            del self._keys[state.key]
            if not state.ready.done():
                state.ready.set_exception(error)
        if unsubscribe and self._authenticated:
            self._enqueue("unsubscribe", current)
        for listener in listeners:
            listener.end(error)
        self._schedule_idle()

    async def _recover(self, code: int) -> None:
        self._reset()
        self._lost = None
        await self._connection.close()
        if self._keys and not self.closed:
            delay = reconnect_delay(code, self._attempt)
            self._attempt += 1
            await asyncio.sleep(delay)

    async def _run(self) -> None:
        try:
            while not self.closed:
                if self._lost is not None:
                    error = self._lost
                    if error.code in (4001, 4008):
                        self._reject(list(self._keys.values()), error, unsubscribe=False)
                        self._start_close()
                        return
                    await self._recover(error.code)
                if not self._keys and not self._ops:
                    self._wake.clear()
                    await self._wake.wait()
                    continue
                if not self._authenticated:
                    try:
                        await self._connection.open(
                            event=self._event,
                            dropped=self._dropped,
                            disconnected=self._disconnected,
                        )
                    except (TransportError, ConnectionLostError) as error:
                        self._reject(
                            [state for state in self._keys.values() if not state.accepted],
                            error,
                            unsubscribe=False,
                        )
                        await self._recover(1006)
                        continue
                    try:
                        await self._connection.authorize()
                    except RequestRejectedError as error:
                        if error.code != "auth_unavailable":
                            self._reject(list(self._keys.values()), error, unsubscribe=False)
                            self._start_close()
                            return
                        await self._recover(1006)
                        continue
                    except (TransportError, ConnectionLostError):
                        if self._lost is None:
                            await self._recover(1006)
                        continue
                    if self._lost is not None:
                        continue
                    self._authenticated = True
                    self._enqueue("subscribe", list(self._keys.values()))
                if not self._ops:
                    self._wake.clear()
                    await self._wake.wait()
                    continue
                # Coalesce adjacent registrations without losing unsubscribe order.
                await asyncio.sleep(0.010)
                if self._lost is not None or not self._ops:
                    continue
                operation, queued = self._ops.popleft()
                batch = [
                    state
                    for state in dict.fromkeys(queued)
                    if operation == "unsubscribe" or self._keys.get(state.key) is state
                ]
                if not batch:
                    continue
                try:
                    rejections = await self._connection.change(
                        operation, [state.key for state in batch]
                    )
                    if self._lost is not None:
                        continue
                    if operation == "unsubscribe":
                        if rejections:
                            await self._recover(1006)
                        continue
                    self._attempt = 0
                    rejected = dict(rejections)
                    for state in batch:
                        if state.key in rejected:
                            self._reject([state], rejected[state.key], unsubscribe=False)
                        elif self._keys.get(state.key) is state:
                            state.accepted = True
                            if not state.ready.done():
                                state.ready.set_result(None)
                except RequestRejectedError as error:
                    if operation == "subscribe":
                        self._reject(batch, error)
                    else:
                        await self._recover(1006)
                except (TransportError, ConnectionLostError):
                    if self._lost is None:
                        await self._recover(1006)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._reject(list(self._keys.values()), TransportError(str(error)), unsubscribe=False)
            self._start_close()

    async def close(self) -> None:
        self._start_close()
        assert self._closing is not None
        await asyncio.shield(self._closing)

    async def _shutdown(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._reject(
            list(self._keys.values()),
            TransportError("Realtime connection closed"),
            unsubscribe=False,
        )
        self._ops.clear()
        await self._connection.close()
