from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

from polymarket import RateLimitError, RequestRejectedError

_Result = TypeVar("_Result")
_WALLET_ACTION_MAX_ATTEMPTS = 61
_WALLET_IN_FLIGHT_RE = re.compile(r"wallet has in-flight action", re.IGNORECASE)
# Rate-limited attempts to retry, and the longest wait honoured before each.
_RATE_LIMIT_MAX_RETRIES = 5
_MAX_RATE_LIMIT_WAIT_S = 30.0


async def run_session_key_operation_when_ready(
    operation: Callable[[], Awaitable[_Result]],
) -> _Result:
    # Revocation returns after registry removal, before the wallet is released,
    # and earlier live tests can leave the wallet's submissions rate limited.
    # Rebuild the operation on each retry so it signs with the current nonce.
    rate_limited = 0
    for attempt in range(_WALLET_ACTION_MAX_ATTEMPTS):
        try:
            return await operation()
        except RateLimitError as error:
            rate_limited += 1
            if rate_limited > _RATE_LIMIT_MAX_RETRIES or attempt == _WALLET_ACTION_MAX_ATTEMPTS - 1:
                raise
            wait = 2.0 if error.retry_after is None else error.retry_after
            await asyncio.sleep(min(wait, _MAX_RATE_LIMIT_WAIT_S))
        except RequestRejectedError as error:
            if (
                _WALLET_IN_FLIGHT_RE.search(str(error)) is None
                or attempt == _WALLET_ACTION_MAX_ATTEMPTS - 1
            ):
                raise
            await asyncio.sleep(2)
    raise AssertionError("unreachable")
