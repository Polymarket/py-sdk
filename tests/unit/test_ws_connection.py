import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from polymarket._internal.ws.connection import AsyncWebSocketConnection
from polymarket._internal.ws.heartbeat import SendText
from polymarket.errors import TransportError

Handler = Callable[[ServerConnection], Awaitable[None]]


@asynccontextmanager
async def ws_server(handler: Handler) -> AsyncGenerator[str, None]:
    server = await serve(handler, host="127.0.0.1", port=0)
    try:
        sockets = next(iter(server.sockets))
        port = sockets.getsockname()[1]
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 2.0) -> Awaitable[None]:
    async def wait() -> None:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while not predicate():
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError("timeout waiting for predicate")
            await asyncio.sleep(0.01)

    return wait()


def test_open_send_receive_close_roundtrip() -> None:
    server_received: list[str] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            server_received.append(raw)
            await ws.send(json.dumps({"echo": json.loads(raw)}))

    async def run() -> list[Any]:
        seen: list[Any] = []
        closed = asyncio.Event()
        errors: list[BaseException] = []

        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            result = await conn.connect(
                url=url,
                on_message=seen.append,
                on_connection_lost=lambda _code, _reason: closed.set(),
                on_error=errors.append,
            )
            assert result.reused is False
            assert conn.is_open is True

            await conn.send({"hello": "world"})
            await _wait_until(lambda: len(seen) == 1)
            await conn.close()
            assert conn.is_open is False

        assert errors == []
        return seen

    seen = asyncio.run(run())
    assert seen == [{"echo": {"hello": "world"}}]
    assert server_received == ['{"hello":"world"}']


def test_close_is_idempotent() -> None:
    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> None:
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            await asyncio.gather(conn.close(), conn.close(), conn.close())
            await conn.close()

    asyncio.run(run())


def test_close_before_connect_is_noop() -> None:
    async def run() -> None:
        conn = AsyncWebSocketConnection()
        await conn.close()

    asyncio.run(run())


def test_second_connect_reuses_open_socket() -> None:
    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> None:
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            first = await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            second = await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            assert first.reused is False
            assert second.reused is True
            await conn.close()

    asyncio.run(run())


def test_concurrent_connect_coalesces() -> None:
    accept_count = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal accept_count
        accept_count += 1
        async for _ in ws:
            pass

    async def run() -> list[Any]:
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            results = await asyncio.gather(
                conn.connect(
                    url=url,
                    on_message=lambda _m: None,
                    on_connection_lost=lambda _code, _reason: None,
                    on_error=lambda _e: None,
                ),
                conn.connect(
                    url=url,
                    on_message=lambda _m: None,
                    on_connection_lost=lambda _code, _reason: None,
                    on_error=lambda _e: None,
                ),
                conn.connect(
                    url=url,
                    on_message=lambda _m: None,
                    on_connection_lost=lambda _code, _reason: None,
                    on_error=lambda _e: None,
                ),
            )
            await conn.close()
            return list(results)

    results = asyncio.run(run())
    assert len(results) == 3
    assert accept_count == 1


def test_server_close_triggers_on_connection_lost() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.close(code=4001, reason="maker suspended")

    async def run() -> None:
        closed = asyncio.Event()
        close_info: list[tuple[int, str]] = []

        def on_connection_lost(code: int, reason: str) -> None:
            close_info.append((code, reason))
            closed.set()

        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=on_connection_lost,
                on_error=lambda _e: None,
            )
            await asyncio.wait_for(closed.wait(), timeout=2.0)
            assert conn.is_open is False
            assert close_info == [(4001, "maker suspended")]
            await conn.close()

    asyncio.run(run())


def test_user_close_does_not_fire_on_connection_lost() -> None:
    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> None:
        closed = asyncio.Event()
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: closed.set(),
                on_error=lambda _e: None,
            )
            await conn.close()
            await asyncio.sleep(0.05)
            assert not closed.is_set()

    asyncio.run(run())


def test_malformed_json_is_dropped_silently() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.send("this-is-not-json")
        await ws.send(json.dumps({"ok": True}))
        async for _ in ws:
            pass

    async def run() -> list[Any]:
        seen: list[Any] = []
        errors: list[BaseException] = []
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            await conn.connect(
                url=url,
                on_message=seen.append,
                on_connection_lost=lambda _code, _reason: None,
                on_error=errors.append,
            )
            await _wait_until(lambda: len(seen) >= 1)
            await conn.close()
        assert errors == []
        return seen

    seen = asyncio.run(run())
    assert seen == [{"ok": True}]


def test_binary_frame_is_decoded_as_utf8_json() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.send(json.dumps({"binary": "frame"}).encode("utf-8"))
        async for _ in ws:
            pass

    async def run() -> list[Any]:
        seen: list[Any] = []
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            await conn.connect(
                url=url,
                on_message=seen.append,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            await _wait_until(lambda: len(seen) == 1)
            await conn.close()
        return seen

    seen = asyncio.run(run())
    assert seen == [{"binary": "frame"}]


def test_send_str_is_passed_through_verbatim() -> None:
    received: list[str] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            received.append(raw)

    async def run() -> None:
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            await conn.send("PING")
            await _wait_until(lambda: received == ["PING"])
            await conn.close()

    asyncio.run(run())


def test_send_returns_false_when_not_connected() -> None:
    async def run() -> bool:
        conn = AsyncWebSocketConnection()
        return await conn.send({"x": 1})

    assert asyncio.run(run()) is False


def test_heartbeat_consumes_pong_before_json_parsing() -> None:
    class CountingHeartbeat:
        def __init__(self) -> None:
            self.handled: list[str] = []
            self.started = False
            self.stopped = False

        async def start(self, send: SendText) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

        def handle(self, message: str) -> bool:
            if message == "PONG":
                self.handled.append(message)
                return True
            return False

        def is_stale(self, now: float) -> bool:
            return False

    heartbeat = CountingHeartbeat()

    async def handler(ws: ServerConnection) -> None:
        await ws.send("PONG")
        await ws.send(json.dumps({"x": 1}))
        async for _ in ws:
            pass

    async def run() -> list[Any]:
        seen: list[Any] = []
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection(heartbeat=heartbeat)
            await conn.connect(
                url=url,
                on_message=seen.append,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            await _wait_until(lambda: len(seen) == 1)
            await conn.close()
        return seen

    seen = asyncio.run(run())
    assert seen == [{"x": 1}]
    assert heartbeat.handled == ["PONG"]
    assert heartbeat.started is True
    assert heartbeat.stopped is True


def test_stale_heartbeat_forces_close_and_fires_on_connection_lost() -> None:
    class AlwaysStaleHeartbeat:
        async def start(self, send: SendText) -> None:
            return None

        async def stop(self) -> None:
            return None

        def handle(self, message: str) -> bool:
            return False

        def is_stale(self, now: float) -> bool:
            return True

    async def handler(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async def run() -> None:
        closed = asyncio.Event()
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection(
                heartbeat=AlwaysStaleHeartbeat(), watchdog_interval_s=0.05
            )
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: closed.set(),
                on_error=lambda _e: None,
            )
            await asyncio.wait_for(closed.wait(), timeout=2.0)
            assert conn.is_open is False
            await conn.close()

    asyncio.run(run())


def test_connect_failure_wraps_as_transport_error() -> None:
    async def run() -> None:
        conn = AsyncWebSocketConnection(open_timeout_s=0.5)
        with pytest.raises(TransportError) as excinfo:
            await conn.connect(
                url="ws://127.0.0.1:1",
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
        assert excinfo.value.__cause__ is not None
        assert conn.is_open is False
        await conn.close()

    asyncio.run(run())


def test_send_returns_true_on_success() -> None:
    received: list[str] = []

    async def handler(ws: ServerConnection) -> None:
        async for raw in ws:
            assert isinstance(raw, str)
            received.append(raw)

    async def run() -> bool:
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            ok = await conn.send({"hello": "world"})
            await _wait_until(lambda: received == ['{"hello":"world"}'])
            await conn.close()
            return ok

    assert asyncio.run(run()) is True


def test_send_returns_false_after_server_close() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.close()

    async def run() -> bool:
        closed = asyncio.Event()
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: closed.set(),
                on_error=lambda _e: None,
            )
            await asyncio.wait_for(closed.wait(), timeout=2.0)
            ok = await conn.send({"x": 1})
            await conn.close()
            return ok

    assert asyncio.run(run()) is False


def test_reconnect_over_stale_socket_does_not_leak_heartbeat() -> None:
    """Connecting again while a prior socket is CLOSING (read-loop finalizer
    not yet run) must not leak the prior heartbeat's ping task. The fix
    routes the stale-socket path through close(), which calls heartbeat.stop().
    """

    class CountingHeartbeat:
        def __init__(self) -> None:
            self.starts = 0
            self.stops = 0
            self._timer: asyncio.Task[None] | None = None

        async def start(self, send: SendText) -> None:
            self.starts += 1
            self._timer = asyncio.create_task(self._tick())

        async def stop(self) -> None:
            self.stops += 1
            if self._timer is not None:
                self._timer.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._timer
                self._timer = None

        def handle(self, message: str) -> bool:
            return False

        def is_stale(self, now: float) -> bool:
            return False

        async def _tick(self) -> None:
            try:
                while True:
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                return

    heartbeat = CountingHeartbeat()

    server_closed_first = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        if not server_closed_first.is_set():
            server_closed_first.set()
            await ws.close()
            return
        async for _ in ws:
            pass

    async def run() -> tuple[int, int]:
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection(heartbeat=heartbeat)
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            await asyncio.wait_for(server_closed_first.wait(), timeout=2.0)
            # Immediately reconnect while the prior socket may still be
            # CLOSING and its finalizer not yet run.
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            await conn.close()
            return heartbeat.starts, heartbeat.stops

    starts, stops = asyncio.run(run())
    assert starts == 2
    assert stops == 2


def test_concurrent_cleanup_paths_run_heartbeat_stop_exactly_once() -> None:
    """Forces overlap between close()'s shutdown and the reader's finalizer
    by making heartbeat.stop yield control. Verifies the atomic claim keeps
    cleanup single-owner: heartbeat.stop is called exactly once per socket.
    """

    class SlowStopHeartbeat:
        def __init__(self) -> None:
            self.starts = 0
            self.stops = 0

        async def start(self, send: SendText) -> None:  # noqa: ARG002
            self.starts += 1

        async def stop(self) -> None:
            self.stops += 1
            # Yield control so other tasks (reader finalizer) can run.
            await asyncio.sleep(0.01)

        def handle(self, message: str) -> bool:  # noqa: ARG002
            return False

        def is_stale(self, now: float) -> bool:  # noqa: ARG002
            return False

    heartbeat = SlowStopHeartbeat()
    server_closing = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        server_closing.set()
        await ws.close()

    async def run() -> tuple[int, int]:
        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection(heartbeat=heartbeat)
            await conn.connect(
                url=url,
                on_message=lambda _m: None,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            await asyncio.wait_for(server_closing.wait(), timeout=2.0)
            # Race close() against the reader's finalizer.
            await conn.close()
            return heartbeat.starts, heartbeat.stops

    starts, stops = asyncio.run(run())
    assert starts == 1
    assert stops == 1


def test_on_message_callback_exception_does_not_break_stream() -> None:
    raised: list[int] = []

    def on_message(msg: Any) -> None:
        if msg.get("idx") == 1:
            raised.append(1)
            raise RuntimeError("boom")

    async def handler(ws: ServerConnection) -> None:
        await ws.send(json.dumps({"idx": 1}))
        await ws.send(json.dumps({"idx": 2}))
        async for _ in ws:
            pass

    async def run() -> int:
        seen: list[Any] = []

        def capture(msg: Any) -> None:
            on_message(msg)
            seen.append(msg)

        async with ws_server(handler) as url:
            conn = AsyncWebSocketConnection()
            await conn.connect(
                url=url,
                on_message=capture,
                on_connection_lost=lambda _code, _reason: None,
                on_error=lambda _e: None,
            )
            await _wait_until(lambda: any(s.get("idx") == 2 for s in seen))
            await conn.close()
        return len(seen)

    # idx=1 raises before append; idx=2 succeeds and appends → seen has at least idx=2
    total_seen = asyncio.run(run())
    assert raised == [1]
    assert total_seen >= 1
