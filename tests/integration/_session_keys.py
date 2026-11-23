from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from polymarket import RateLimitError, RequestRejectedError

_Result = TypeVar("_Result")
_WALLET_ACTION_MAX_ATTEMPTS = 61
_WALLET_IN_FLIGHT_RE = re.compile(r"wallet has in-flight action", re.IGNORECASE)
# How long to keep retrying a rate-limited operation, and the wait between tries
# when the API does not say how long to wait.
_RATE_LIMIT_BUDGET_S = 120.0
_RATE_LIMIT_DEFAULT_WAIT_S = 10.0


async def run_session_key_operation_when_ready(
    operation: Callable[[], Awaitable[_Result]],
) -> _Result:
    # Revocation returns after registry removal, before the wallet is released,
    # and earlier live tests can leave the wallet's submissions rate limited.
    # Rebuild the operation on each retry so it signs with the current nonce.
    rate_limit_deadline: float | None = None
    for attempt in range(_WALLET_ACTION_MAX_ATTEMPTS):
        try:
            return await operation()
        except RateLimitError as error:
            now = time.monotonic()
            if rate_limit_deadline is None:
                rate_limit_deadline = now + _RATE_LIMIT_BUDGET_S
            wait = _RATE_LIMIT_DEFAULT_WAIT_S if error.retry_after is None else error.retry_after
            if now + wait > rate_limit_deadline or attempt == _WALLET_ACTION_MAX_ATTEMPTS - 1:
                raise
            await asyncio.sleep(wait)
        except RequestRejectedError as error:
            if (
                _WALLET_IN_FLIGHT_RE.search(str(error)) is None
                or attempt == _WALLET_ACTION_MAX_ATTEMPTS - 1
            ):
                raise
            await asyncio.sleep(2)
    raise AssertionError("unreachable")
