"""Serve several mocked operation families from one client transport."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

Handler = Callable[[httpx.Request], httpx.Response]


class _StackedMock(httpx.MockTransport):
    def __init__(self, top: httpx.MockTransport, previous: httpx.MockTransport | None) -> None:
        super().__init__(top.handler)
        self._top = top
        self._previous = previous

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._top.handle_request(request)
        if response.status_code == 404 and self._previous is not None:
            return self._previous.handle_request(request)
        return response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._top.handle_async_request(request)
        if response.status_code == 404 and self._previous is not None:
            return await self._previous.handle_async_request(request)
        return response


def stacked_mock(ctx_transport: Any, handler: Handler | httpx.MockTransport) -> httpx.MockTransport:
    """Mock that serves ``handler`` and falls back to the mock already installed.

    Requests ``handler`` answers with 404 go to the mock previously installed on
    ``ctx_transport``, so tests can mock each operation family separately.
    """
    previous = getattr(getattr(ctx_transport, "_client", None), "_transport", None)
    top = handler if isinstance(handler, httpx.MockTransport) else httpx.MockTransport(handler)
    return _StackedMock(top, previous if isinstance(previous, httpx.MockTransport) else None)
