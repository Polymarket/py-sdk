import asyncio
import contextlib
import time

from polymarket._internal.ws.heartbeat import SendText

PING_INTERVAL_S = 30.0


class PriceHeartbeat:
    """Send protocol pings every 30 seconds; any inbound frame proves liveness."""

    def __init__(self) -> None:
        self._last_message = 0.0
        self._task: asyncio.Task[None] | None = None

    async def start(self, send: SendText) -> None:
        await self.stop()
        self._last_message = time.monotonic()
        self._task = asyncio.create_task(self._ping(send))

    async def _ping(self, send: SendText) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL_S)
            await send('{"op":"ping"}')

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def handle(self, message: str) -> bool:
        self._last_message = time.monotonic()
        return False

    def is_stale(self, now: float) -> bool:
        return now - self._last_message >= 90
