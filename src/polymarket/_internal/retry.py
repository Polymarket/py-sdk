from asyncio import sleep as async_sleep
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import sleep
from typing import TypeVar

from polymarket.errors import RateLimitError

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RateLimitRetry:
    retries: int = 2
    max_delay_seconds: float = 5.0


DATA_READ_RETRY = RateLimitRetry()


def run_with_rate_limit_retry(call: Callable[[], T], retry: RateLimitRetry | None) -> T:
    for attempt in range((retry.retries if retry else 0) + 1):
        try:
            return call()
        except RateLimitError as error:
            delay = error.retry_after if error.retry_after is not None else 1
            if retry is None or attempt >= retry.retries or delay > retry.max_delay_seconds:
                raise
            sleep(max(0, delay))
    raise RuntimeError("Retry attempts exhausted")


async def async_run_with_rate_limit_retry(
    call: Callable[[], Awaitable[T]], retry: RateLimitRetry | None
) -> T:
    for attempt in range((retry.retries if retry else 0) + 1):
        try:
            return await call()
        except RateLimitError as error:
            delay = error.retry_after if error.retry_after is not None else 1
            if retry is None or attempt >= retry.retries or delay > retry.max_delay_seconds:
                raise
            await async_sleep(max(0, delay))
    raise RuntimeError("Retry attempts exhausted")
