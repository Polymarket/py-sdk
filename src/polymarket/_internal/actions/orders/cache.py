from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from dataclasses import dataclass
from decimal import Decimal
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from polymarket._internal.actions.orders.market_data import (
    MarketInfo,
    fetch_builder_fee_rates,
    fetch_builder_fee_rates_sync,
    fetch_market_info,
    fetch_market_info_sync,
    resolve_condition_by_token,
    resolve_condition_by_token_sync,
)
from polymarket._internal.actions.orders.types import BYTES32_ZERO
from polymarket.errors import UnexpectedResponseError
from polymarket.models.types import CtfConditionId, TokenId
from polymarket.types import HexString

if TYPE_CHECKING:
    from polymarket._internal.context import AsyncClientContext, SyncClientContext

_METADATA_TTL_S = 10 * 60

_Key = TypeVar("_Key")
_Value = TypeVar("_Value")


@dataclass(frozen=True, slots=True)
class _CachedValue(Generic[_Value]):
    value: _Value
    expires_at: float | None


class _SyncSingleFlightCache(Generic[_Key, _Value]):
    def __init__(self, *, ttl_s: float | None, clock: Callable[[], float]) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._values: dict[_Key, _CachedValue[_Value]] = {}
        self._inflight: dict[_Key, Future[_Value]] = {}
        self._lock = Lock()

    def get(self, key: _Key, load: Callable[[], _Value], *, force: bool = False) -> _Value:
        owner = False
        with self._lock:
            cached = self._values.get(key)
            if (
                not force
                and cached is not None
                and (cached.expires_at is None or cached.expires_at > self._clock())
            ):
                return cached.value
            existing = self._inflight.get(key)
            if existing is None:
                future: Future[_Value] = Future()
                self._inflight[key] = future
                owner = True
            else:
                future = existing

        if not owner:
            return future.result()

        try:
            value = load()
        except BaseException as error:
            with self._lock:
                if self._inflight.get(key) is future:
                    self._inflight.pop(key, None)
            future.set_exception(error)
            raise

        expires_at = None if self._ttl_s is None else self._clock() + self._ttl_s
        with self._lock:
            self._values[key] = _CachedValue(value=value, expires_at=expires_at)
            if self._inflight.get(key) is future:
                self._inflight.pop(key, None)
        future.set_result(value)
        return value

    def set(self, key: _Key, value: _Value) -> None:
        expires_at = None if self._ttl_s is None else self._clock() + self._ttl_s
        with self._lock:
            self._values[key] = _CachedValue(value=value, expires_at=expires_at)

    def discard(self, key: _Key) -> None:
        with self._lock:
            self._values.pop(key, None)


class _AsyncSingleFlightCache(Generic[_Key, _Value]):
    def __init__(self, *, ttl_s: float | None, clock: Callable[[], float]) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._values: dict[_Key, _CachedValue[_Value]] = {}
        self._inflight: dict[_Key, asyncio.Task[_Value]] = {}

    async def get(
        self,
        key: _Key,
        load: Callable[[], Coroutine[Any, Any, _Value]],
        *,
        force: bool = False,
    ) -> _Value:
        cached = self._values.get(key)
        if (
            not force
            and cached is not None
            and (cached.expires_at is None or cached.expires_at > self._clock())
        ):
            return cached.value

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._load(key, load))
            task.add_done_callback(_consume_task_exception)
            self._inflight[key] = task
        return await asyncio.shield(task)

    async def _load(self, key: _Key, load: Callable[[], Coroutine[Any, Any, _Value]]) -> _Value:
        try:
            value = await load()
            expires_at = None if self._ttl_s is None else self._clock() + self._ttl_s
            self._values[key] = _CachedValue(value=value, expires_at=expires_at)
            return value
        finally:
            if self._inflight.get(key) is asyncio.current_task():
                self._inflight.pop(key, None)

    def set(self, key: _Key, value: _Value) -> None:
        expires_at = None if self._ttl_s is None else self._clock() + self._ttl_s
        self._values[key] = _CachedValue(value=value, expires_at=expires_at)

    def discard(self, key: _Key) -> None:
        self._values.pop(key, None)

    async def close(self) -> None:
        tasks = tuple(self._inflight.values())
        self._inflight.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _consume_task_exception(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


class SyncOrderMetadataCache:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._conditions = _SyncSingleFlightCache[TokenId, CtfConditionId](ttl_s=None, clock=clock)
        self._markets = _SyncSingleFlightCache[CtfConditionId, MarketInfo](
            ttl_s=_METADATA_TTL_S, clock=clock
        )
        self._builder_taker_fee_rates = _SyncSingleFlightCache[HexString, Decimal](
            ttl_s=_METADATA_TTL_S, clock=clock
        )

    def resolve_market(self, ctx: SyncClientContext, *, token_id: TokenId) -> MarketInfo:
        return self._resolve_market(ctx, token_id=token_id, force=False)

    def fetch_current_market(self, ctx: SyncClientContext, *, token_id: TokenId) -> MarketInfo:
        return self._resolve_market(ctx, token_id=token_id, force=True)

    def resolve_builder_taker_fee_rate(
        self, ctx: SyncClientContext, *, builder_code: HexString | None
    ) -> Decimal:
        if builder_code is None or builder_code == BYTES32_ZERO:
            return Decimal(0)
        return self._builder_taker_fee_rates.get(
            builder_code,
            lambda: fetch_builder_fee_rates_sync(ctx, builder_code=builder_code).taker,
        )

    def _resolve_market(
        self, ctx: SyncClientContext, *, token_id: TokenId, force: bool
    ) -> MarketInfo:
        condition_id = self._conditions.get(
            token_id,
            lambda: resolve_condition_by_token_sync(ctx, token_id=token_id),
        )
        market = self._markets.get(
            condition_id,
            lambda: self._load_market(ctx, condition_id=condition_id),
            force=force,
        )
        if token_id not in market.token_ids:
            self._conditions.discard(token_id)
            self._markets.discard(condition_id)
            raise UnexpectedResponseError(
                f"Market {condition_id} does not include token {token_id}."
            )
        return market

    def _load_market(self, ctx: SyncClientContext, *, condition_id: CtfConditionId) -> MarketInfo:
        market = fetch_market_info_sync(ctx, condition_id=condition_id)
        for token_id in market.token_ids:
            self._conditions.set(token_id, condition_id)
        return market


class AsyncOrderMetadataCache:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._conditions = _AsyncSingleFlightCache[TokenId, CtfConditionId](ttl_s=None, clock=clock)
        self._markets = _AsyncSingleFlightCache[CtfConditionId, MarketInfo](
            ttl_s=_METADATA_TTL_S, clock=clock
        )
        self._builder_taker_fee_rates = _AsyncSingleFlightCache[HexString, Decimal](
            ttl_s=_METADATA_TTL_S, clock=clock
        )

    async def resolve_market(self, ctx: AsyncClientContext, *, token_id: TokenId) -> MarketInfo:
        return await self._resolve_market(ctx, token_id=token_id, force=False)

    async def fetch_current_market(
        self, ctx: AsyncClientContext, *, token_id: TokenId
    ) -> MarketInfo:
        return await self._resolve_market(ctx, token_id=token_id, force=True)

    async def resolve_builder_taker_fee_rate(
        self, ctx: AsyncClientContext, *, builder_code: HexString | None
    ) -> Decimal:
        if builder_code is None or builder_code == BYTES32_ZERO:
            return Decimal(0)
        return await self._builder_taker_fee_rates.get(
            builder_code,
            lambda: _fetch_builder_taker_fee_rate(ctx, builder_code=builder_code),
        )

    async def close(self) -> None:
        await asyncio.gather(
            self._conditions.close(),
            self._markets.close(),
            self._builder_taker_fee_rates.close(),
        )

    async def _resolve_market(
        self, ctx: AsyncClientContext, *, token_id: TokenId, force: bool
    ) -> MarketInfo:
        condition_id = await self._conditions.get(
            token_id,
            lambda: resolve_condition_by_token(ctx, token_id=token_id),
        )
        market = await self._markets.get(
            condition_id,
            lambda: self._load_market(ctx, condition_id=condition_id),
            force=force,
        )
        if token_id not in market.token_ids:
            self._conditions.discard(token_id)
            self._markets.discard(condition_id)
            raise UnexpectedResponseError(
                f"Market {condition_id} does not include token {token_id}."
            )
        return market

    async def _load_market(
        self, ctx: AsyncClientContext, *, condition_id: CtfConditionId
    ) -> MarketInfo:
        market = await fetch_market_info(ctx, condition_id=condition_id)
        for token_id in market.token_ids:
            self._conditions.set(token_id, condition_id)
        return market


async def _fetch_builder_taker_fee_rate(
    ctx: AsyncClientContext, *, builder_code: HexString
) -> Decimal:
    return (await fetch_builder_fee_rates(ctx, builder_code=builder_code)).taker


__all__ = ["AsyncOrderMetadataCache", "SyncOrderMetadataCache"]
