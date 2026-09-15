import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from polymarket._internal.streams.realtime.heartbeat import PriceHeartbeat
from polymarket._internal.streams.realtime.protocol import (
    PriceKey,
    build_wire_subscription,
    parse_price_event,
)
from polymarket._internal.ws.connection import AsyncWebSocketConnection
from polymarket.errors import ConnectionLostError, RequestRejectedError, TransportError
from polymarket.models.clob.api_key import ApiKeyCreds
from polymarket.models.price_events import PriceEvent, RealtimeErrorCode

Operation = Literal["subscribe", "unsubscribe"]
ACK_TIMEOUT_S = 10.0
OPERATION_INTERVAL_S = 0.110


@dataclass
class _Pending:
    op: str
    channels: list[str | None]
    future: asyncio.Future[list[tuple[int, RequestRejectedError]]]
    rejected: list[tuple[int, RequestRejectedError]] = field(
        default_factory=list[tuple[int, RequestRejectedError]]
    )


class PriceConnection:
    """Translate ordered price operations to authenticated PolyBolt frames."""

    def __init__(
        self,
        *,
        url: str,
        credentials: ApiKeyCreds,
        headers: Mapping[str, str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._url = url
        self._credentials = credentials
        self._headers = headers
        self._connection = AsyncWebSocketConnection(
            heartbeat=PriceHeartbeat(), logger=logger, close_timeout_s=1.0
        )
        self._pending: dict[str, _Pending] = {}
        self._rid = 0
        self._last_sent = float("-inf")
        self._send_lock = asyncio.Lock()
        self._generation = 0
        self._event: Callable[[PriceEvent], None] | None = None
        self._dropped: Callable[[], None] | None = None

    async def open(
        self,
        *,
        event: Callable[[PriceEvent], None],
        dropped: Callable[[], None],
        disconnected: Callable[[ConnectionLostError], None],
    ) -> None:
        generation = self._generation
        self._event, self._dropped = event, dropped

        def lost(code: int, reason: str) -> None:
            if generation != self._generation:
                return
            error = ConnectionLostError("Realtime connection closed", code=code, reason=reason)
            self._cancel(error)
            disconnected(error)

        def message(value: object) -> None:
            if generation == self._generation:
                self._message(value)

        await self._connection.connect(
            url=self._url,
            headers=self._headers,
            on_message=message,
            on_connection_lost=lost,
            on_error=lambda error: None,
        )

    async def authorize(self) -> None:
        await self._request(
            {
                "op": "auth",
                "auth": {
                    "apiKey": self._credentials.key,
                    "secret": self._credentials.secret,
                    "passphrase": self._credentials.passphrase,
                },
            },
            "authed",
            [],
        )

    async def change(
        self,
        operation: Operation,
        keys: Sequence[PriceKey],
    ) -> list[tuple[PriceKey, RequestRejectedError]]:
        rejected: list[tuple[PriceKey, RequestRejectedError]] = []
        offset = 0
        while offset < len(keys):
            batch: list[dict[str, object]] = []
            for key in keys[offset:]:
                candidate = build_wire_subscription(key)
                frame = {
                    "op": operation,
                    "subscriptions": [*batch, candidate],
                    "rid": str(self._rid + 1),
                }
                if batch and len(json.dumps(frame, separators=(",", ":")).encode()) > 60_000:
                    break
                batch.append(candidate)
            errors = await self._request(
                {"op": operation, "subscriptions": batch},
                "subscribed" if operation == "subscribe" else "unsubscribed",
                [str(item["channel"]) for item in batch],
            )
            rejected.extend((keys[offset + index], error) for index, error in errors)
            offset += len(batch)
        return rejected

    async def _request(
        self,
        frame: dict[str, object],
        op: str,
        channels: list[str],
    ) -> list[tuple[int, RequestRejectedError]]:
        async with self._send_lock:
            self._rid += 1
            rid = str(self._rid)
            loop = asyncio.get_running_loop()
            future: asyncio.Future[list[tuple[int, RequestRejectedError]]] = loop.create_future()
            pending = _Pending(op=op, channels=list(channels), future=future)
            self._pending[rid] = pending
            try:
                await asyncio.sleep(max(0, OPERATION_INTERVAL_S - (loop.time() - self._last_sent)))
                if future.done():
                    return future.result()
                self._last_sent = loop.time()
                try:
                    sent = await self._connection.send({**frame, "rid": rid})
                except Exception as error:
                    raise TransportError("Realtime operation could not be sent") from error
                if not sent:
                    raise TransportError("Realtime connection is not open")
                try:
                    return await asyncio.wait_for(future, ACK_TIMEOUT_S)
                except TimeoutError as error:
                    raise TransportError(
                        "Realtime acknowledgement timed out after 10 seconds"
                    ) from error
            finally:
                self._pending.pop(rid, None)
                if future.done() and not future.cancelled():
                    future.exception()
                else:
                    future.cancel()

    def _message(self, value: object) -> None:
        if not isinstance(value, dict):
            return
        frame = cast(dict[str, object], value)
        op = frame.get("op")
        if op in ("authed", "subscribed", "unsubscribed", "pong", "error"):
            rid, channel = frame.get("rid"), frame.get("channel")
            if not isinstance(rid, str) or (channel is not None and not isinstance(channel, str)):
                return
            pending = self._pending.get(rid)
            if pending is None or pending.future.done():
                return
            if op == "error":
                code = frame.get("code")
                if not isinstance(code, str) or code not in {
                    item.value for item in RealtimeErrorCode
                }:
                    return
                error = RequestRejectedError(
                    f"Realtime subscription rejected: {code}", status=200, code=code
                )
                matches = [
                    i for i, candidate in enumerate(pending.channels) if candidate == channel
                ]
                if channel is None or len(matches) != 1:
                    pending.future.set_exception(error)
                    return
                index = matches[0]
                pending.channels[index] = None
                pending.rejected.append((index, error))
            elif op == pending.op:
                if pending.channels:
                    if channel is None or channel not in pending.channels:
                        return
                    pending.channels[pending.channels.index(channel)] = None
            else:
                return
            if all(channel is None for channel in pending.channels):
                pending.future.set_result(pending.rejected)
            return
        event = parse_price_event(frame)
        if event is not None:
            if self._event is not None:
                self._event(event)
            if event.dropped and self._dropped is not None:
                self._dropped()

    def _cancel(self, error: Exception) -> None:
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.set_exception(error)

    async def close(self) -> None:
        self._generation += 1
        self._event = self._dropped = None
        self._cancel(TransportError("Realtime connection closed"))
        await self._connection.close()
