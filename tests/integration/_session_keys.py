from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

from polymarket import RequestRejectedError

_Result = TypeVar("_Result")
_WALLET_ACTION_MAX_ATTEMPTS = 61
_WALLET_IN_FLIGHT_RE = re.compile(r"wallet has in-flight action", re.IGNORECASE)


async def run_session_key_operation_when_ready(
    operation: Callable[[], Awaitable[_Result]],
) -> _Result:
    # Revocation returns after registry removal, before the wallet is released.
    # Rebuild the operation on each retry so it signs with the current nonce.
    for attempt in range(_WALLET_ACTION_MAX_ATTEMPTS):
        try:
            return await operation()
        except RequestRejectedError as error:
            if (
                _WALLET_IN_FLIGHT_RE.search(str(error)) is None
                or attempt == _WALLET_ACTION_MAX_ATTEMPTS - 1
            ):
                raise
            await asyncio.sleep(2)
    raise AssertionError("unreachable")
