"""Asynchronous public Polymarket client."""

import contextlib
import logging
from collections.abc import Sequence
from decimal import Decimal
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Self, assert_never, cast, overload

from polymarket._internal.actions import builders as _builders_actions
from polymarket._internal.actions import clob as _clob_actions
from polymarket._internal.actions import data as _data_actions
from polymarket._internal.actions import gamma as _gamma_actions
from polymarket._internal.actions import rewards as _rewards_actions
from polymarket._internal.actions import rfq as _rfq_actions
from polymarket._internal.actions.data import (
    ActivitySortBy,
    ActivityTypeFilter,
    ClosedPositionSortBy,
    ComboPositionSort,
    ComboPositionStatus,
    MarketPositionSortBy,
    MarketPositionStatus,
    PositionSortBy,
    SortDirection,
    TradeFilterType,
    TradeSide,
)
from polymarket._internal.actions.gamma import (
    CommentParentEntityType,
    DateFilter,
    Recurrence,
    SearchSort,
    TagMatch,
    TimestampFilter,
)
from polymarket._internal.actions.orders.estimate import (
    estimate_market_price as _estimate_market_price,
)
from polymarket._internal.actions.orders.types import MarketOrderType
from polymarket._internal.actions.perps import public as _perps_actions
from polymarket._internal.context import AsyncClientContext
from polymarket._internal.dispatch import (
    async_dispatch,
    async_paginate_keyset,
    async_paginate_offset,
    async_paginate_page_based,
)
from polymarket._internal.streams.handle import AsyncSubscriptionHandle, SubscriptionHandle
from polymarket.clients._transport import AsyncTransport
from polymarket.environments import PRODUCTION, Environment
from polymarket.errors import RequestRejectedError
from polymarket.models import (
    ComboMarket,
    Comment,
    Event,
    LastTradePrice,
    LastTradePriceForToken,
    Market,
    OrderBook,
    OrderSide,
    PriceHistoryInterval,
    PriceHistoryPoint,
    PriceRequest,
    PublicProfile,
    RelatedTag,
    SearchResults,
    Series,
    SportsMarketTypes,
    SportsMetadata,
    Tag,
    TagReference,
    Team,
)
from polymarket.models.clob.builder import BuilderTrade
from polymarket.models.clob.market_events import MarketEvent
from polymarket.models.clob.rewards import CurrentReward, MarketReward
from polymarket.models.data import (
    Activity,
    BuilderVolumeEntry,
    BuilderVolumeTimePeriod,
    ClosedPosition,
    ComboActivity,
    ComboPosition,
    LeaderboardCategory,
    LeaderboardEntry,
    LeaderboardOrderBy,
    LeaderboardTimePeriod,
    LiveVolume,
    MetaHolder,
    MetaMarketPosition,
    OpenInterest,
    PortfolioValue,
    Position,
    Trade,
    TradedMarketCount,
    TraderLeaderboardEntry,
)
from polymarket.models.perps import (
    PerpsBook,
    PerpsBookDepth,
    PerpsCandle,
    PerpsFeeScheduleEntry,
    PerpsFundingRate,
    PerpsInstrument,
    PerpsInstrumentCategory,
    PerpsKlineInterval,
    PerpsMarketEvent,
    PerpsTicker,
    PerpsTrade,
)
from polymarket.models.rtds_events import (
    CommentsEvent,
    CryptoPricesEvent,
    EquityPricesEvent,
    RtdsEvent,
)
from polymarket.models.sports_events import SportsEvent
from polymarket.models.types import CtfConditionId
from polymarket.pagination import AsyncPaginator, Page
from polymarket.streams._specs import (
    CommentsSpec,
    CryptoPricesSpec,
    EquityPricesSpec,
    MarketSpec,
    PerpsSpec,
    PublicSubscription,
    SportsSpec,
    normalize_specs,
)

if TYPE_CHECKING:
    from datetime import datetime

    from polymarket._internal.streams.clob.market import ClobMarketStreamManager
    from polymarket._internal.streams.perps.market import PerpsMarketStreamManager
    from polymarket._internal.streams.rtds.manager import RtdsStreamManager
    from polymarket._internal.streams.sports.manager import SportsStreamManager


class AsyncPublicClient:
    """Async client for public Polymarket data workflows.

    Public methods return stable, idiomatic Python SDK objects.
    """

    def __init__(
        self,
        environment: Environment = PRODUCTION,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ctx = AsyncClientContext(
            environment=environment,
            gamma=AsyncTransport(base_url=environment.gamma_url, logger=logger),
            data=AsyncTransport(base_url=environment.data_url, logger=logger),
            rfq=AsyncTransport(base_url=environment.rfq_url, logger=logger),
            clob=AsyncTransport(base_url=environment.clob_url, logger=logger),
            perps=AsyncTransport(base_url=environment.perps_url, logger=logger),
        )
        self._market_manager: ClobMarketStreamManager | None = None
        self._sports_manager: SportsStreamManager | None = None
        self._rtds_manager: RtdsStreamManager | None = None
        self._perps_manager: PerpsMarketStreamManager | None = None
        self._streams_logger = logger

    @property
    def environment(self) -> Environment:
        """Environment this client sends requests to."""
        return self._ctx.environment

    @overload
    async def subscribe(self, specs: MarketSpec, /) -> SubscriptionHandle[MarketEvent]: ...
    @overload
    async def subscribe(self, specs: SportsSpec, /) -> SubscriptionHandle[SportsEvent]: ...
    @overload
    async def subscribe(self, specs: CommentsSpec, /) -> SubscriptionHandle[CommentsEvent]: ...
    @overload
    async def subscribe(
        self, specs: CryptoPricesSpec, /
    ) -> SubscriptionHandle[CryptoPricesEvent]: ...
    @overload
    async def subscribe(
        self, specs: EquityPricesSpec, /
    ) -> SubscriptionHandle[EquityPricesEvent]: ...
    @overload
    async def subscribe(self, specs: PerpsSpec, /) -> SubscriptionHandle[PerpsMarketEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[MarketSpec], /
    ) -> SubscriptionHandle[MarketEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[SportsSpec], /
    ) -> SubscriptionHandle[SportsEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[CommentsSpec], /
    ) -> SubscriptionHandle[CommentsEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[CryptoPricesSpec], /
    ) -> SubscriptionHandle[CryptoPricesEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[EquityPricesSpec], /
    ) -> SubscriptionHandle[EquityPricesEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[PerpsSpec], /
    ) -> SubscriptionHandle[PerpsMarketEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[PublicSubscription], /
    ) -> SubscriptionHandle[MarketEvent | SportsEvent | RtdsEvent | PerpsMarketEvent]: ...
    async def subscribe(
        self,
        specs: PublicSubscription | Sequence[PublicSubscription],
    ) -> SubscriptionHandle[MarketEvent | SportsEvent | RtdsEvent | PerpsMarketEvent]:
        """Subscribe to one or more public realtime streams.

        Pass a single subscription spec for one stream or a sequence of specs to
        receive events through one merged handle.

        Returns:
            A subscription handle. Iterate over it to receive events and close it
            when finished.
        """
        items = normalize_specs(specs)
        # AsyncSubscriptionHandle is invariant in T, so per-channel handles
        # can't widen to the union type at the type level. Cast at the
        # boundary — the underlying queue holds whatever was pushed into it.
        handles: list[AsyncSubscriptionHandle[Any]] = []
        try:
            for spec in items:
                if isinstance(spec, MarketSpec):
                    handles.append(
                        await self._get_market_manager().subscribe(
                            token_ids=spec.token_ids,
                            custom_feature_enabled=spec.custom_feature_enabled,
                        )
                    )
                elif isinstance(spec, SportsSpec):
                    handles.append(await self._get_sports_manager().subscribe())
                elif isinstance(spec, PerpsSpec):
                    handles.append(await self._get_perps_manager().subscribe(spec))
                elif isinstance(spec, CommentsSpec | CryptoPricesSpec | EquityPricesSpec):  # pyright: ignore[reportUnnecessaryIsInstance]
                    handles.append(await self._get_rtds_manager().subscribe(spec))
                else:
                    assert_never(spec)
        except BaseException:
            for handle in handles:
                with contextlib.suppress(Exception):
                    await handle.close()
            raise
        if len(handles) == 1:
            return cast(
                SubscriptionHandle[MarketEvent | SportsEvent | RtdsEvent | PerpsMarketEvent],
                handles[0],
            )
        from polymarket._internal.streams.merged_handle import MergedSubscriptionHandle

        return cast(
            SubscriptionHandle[MarketEvent | SportsEvent | RtdsEvent | PerpsMarketEvent],
            MergedSubscriptionHandle(handles),
        )

    def _get_market_manager(self) -> "ClobMarketStreamManager":
        if self._market_manager is None:
            from polymarket._internal.streams.clob.market import ClobMarketStreamManager

            self._market_manager = ClobMarketStreamManager(
                url=self._ctx.environment.clob_market_ws_url,
                logger=self._streams_logger,
            )
        return self._market_manager

    def _get_rtds_manager(self) -> "RtdsStreamManager":
        if self._rtds_manager is None:
            from polymarket._internal.streams.rtds.manager import RtdsStreamManager

            self._rtds_manager = RtdsStreamManager(
                url=self._ctx.environment.rtds_ws_url,
                logger=self._streams_logger,
            )
        return self._rtds_manager

    def _get_sports_manager(self) -> "SportsStreamManager":
        if self._sports_manager is None:
            from polymarket._internal.streams.sports.manager import SportsStreamManager

            self._sports_manager = SportsStreamManager(
                url=self._ctx.environment.sports_ws_url,
                logger=self._streams_logger,
            )
        return self._sports_manager

    def _get_perps_manager(self) -> "PerpsMarketStreamManager":
        if self._perps_manager is None:
            from polymarket._internal.streams.perps.market import PerpsMarketStreamManager

            self._perps_manager = PerpsMarketStreamManager(
                url=self._ctx.environment.perps_ws_url,
                logger=self._streams_logger,
            )
        return self._perps_manager

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying network transports and any open streams."""
        try:
            if self._market_manager is not None:
                await self._market_manager.close()
        finally:
            try:
                if self._sports_manager is not None:
                    await self._sports_manager.close()
            finally:
                try:
                    if self._rtds_manager is not None:
                        await self._rtds_manager.close()
                finally:
                    try:
                        if self._perps_manager is not None:
                            await self._perps_manager.close()
                    finally:
                        try:
                            await self._ctx.gamma.close()
                        finally:
                            try:
                                await self._ctx.data.close()
                            finally:
                                try:
                                    await self._ctx.rfq.close()
                                finally:
                                    try:
                                        await self._ctx.clob.close()
                                    finally:
                                        await self._ctx.perps.close()

    @overload
    async def get_market(
        self, *, id: str, include_tag: bool | None = None, locale: str | None = None
    ) -> Market: ...
    @overload
    async def get_market(
        self, *, slug: str, include_tag: bool | None = None, locale: str | None = None
    ) -> Market: ...
    @overload
    async def get_market(
        self, *, url: str, include_tag: bool | None = None, locale: str | None = None
    ) -> Market: ...
    async def get_market(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        url: str | None = None,
        include_tag: bool | None = None,
        locale: str | None = None,
    ) -> Market:
        """Get a market by id, slug, or Polymarket URL.

        Markets that cannot be represented by the binary Market model raise
        UnexpectedResponseError.
        """
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_market_spec(
                id=id, slug=slug, url=url, include_tag=include_tag, locale=locale
            ),
        )

    async def get_market_tags(self, id: str) -> tuple[TagReference, ...]:
        """Get a market's tags."""
        return await async_dispatch(self._ctx, _gamma_actions.get_market_tags_spec(id))

    @overload
    async def get_event(
        self,
        *,
        id: str,
        include_best_lines: bool | None = None,
        include_chat: bool | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Event: ...
    @overload
    async def get_event(
        self,
        *,
        slug: str,
        include_best_lines: bool | None = None,
        include_chat: bool | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Event: ...
    @overload
    async def get_event(
        self,
        *,
        url: str,
        include_best_lines: bool | None = None,
        include_chat: bool | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Event: ...
    async def get_event(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        url: str | None = None,
        include_best_lines: bool | None = None,
        include_chat: bool | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Event:
        """Get an event by id, slug, or Polymarket URL."""
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_event_spec(
                id=id,
                slug=slug,
                url=url,
                include_best_lines=include_best_lines,
                include_chat=include_chat,
                include_template=include_template,
                locale=locale,
            ),
        )

    async def get_event_tags(self, id: str) -> tuple[TagReference, ...]:
        """Get an event's tags."""
        return await async_dispatch(self._ctx, _gamma_actions.get_event_tags_spec(id))

    async def get_series(
        self,
        id: str,
        *,
        locale: str | None = None,
    ) -> Series:
        """Get a series."""
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_series_spec(id, locale=locale),
        )

    @overload
    async def get_tag(
        self, *, id: str, include_template: bool | None = None, locale: str | None = None
    ) -> Tag: ...
    @overload
    async def get_tag(self, *, slug: str, locale: str | None = None) -> Tag: ...
    async def get_tag(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Tag:
        """Get a tag by id or slug."""
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_tag_spec(
                id=id,
                slug=slug,
                include_template=include_template,
                locale=locale,
            ),
        )

    async def get_related_tags(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        omit_empty: bool | None = None,
        status: str | None = None,
    ) -> tuple[RelatedTag, ...]:
        """Get related tag relationships."""
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_related_tags_spec(
                id=id, slug=slug, omit_empty=omit_empty, status=status
            ),
        )

    async def get_related_tag_resources(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        locale: str | None = None,
        omit_empty: bool | None = None,
        status: str | None = None,
    ) -> tuple[Tag, ...]:
        """Get tag resources linked from related tag relationships."""
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_related_tag_resources_spec(
                id=id, slug=slug, locale=locale, omit_empty=omit_empty, status=status
            ),
        )

    async def get_sports(self) -> tuple[SportsMetadata, ...]:
        """Get available sports metadata."""
        return await async_dispatch(self._ctx, _gamma_actions.get_sports_spec())

    async def get_sports_market_types(self) -> SportsMarketTypes:
        """Get available sports market types."""
        return await async_dispatch(self._ctx, _gamma_actions.get_sports_market_types_spec())

    async def get_public_profile(self, address: str) -> PublicProfile | None:
        """Get a public profile by wallet address. Returns None if no profile exists."""
        try:
            return await async_dispatch(self._ctx, _gamma_actions.get_public_profile_spec(address))
        except RequestRejectedError as error:
            if error.status == 404:
                return None
            raise

    async def get_comment_thread(
        self, id: str, *, get_positions: bool | None = None
    ) -> tuple[Comment, ...]:
        """Get a comment thread by comment ID."""
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_comment_thread_spec(id, get_positions=get_positions),
        )

    async def get_event_live_volumes(self, *, id: str) -> tuple[LiveVolume, ...]:
        """Get live volume entries for an event."""
        return await async_dispatch(self._ctx, _data_actions.get_event_live_volumes_spec(id=id))

    async def get_open_interests(
        self, *, market: Sequence[str] | None = None
    ) -> tuple[OpenInterest, ...]:
        """Get open interest values, optionally filtered by market ids."""
        return await async_dispatch(self._ctx, _data_actions.get_open_interests_spec(market=market))

    async def get_market_holders(
        self,
        *,
        market: Sequence[str],
        limit: int | None = None,
        min_balance: int | None = None,
    ) -> tuple[MetaHolder, ...]:
        """Get holder balances for one or more markets."""
        return await async_dispatch(
            self._ctx,
            _data_actions.get_market_holders_spec(
                market=market, limit=limit, min_balance=min_balance
            ),
        )

    async def get_portfolio_values(
        self, *, user: str, market: Sequence[str] | None = None
    ) -> tuple[PortfolioValue, ...]:
        """Get portfolio value snapshots for a user."""
        return await async_dispatch(
            self._ctx, _data_actions.get_portfolio_values_spec(user=user, market=market)
        )

    async def get_traded_market_count(self, *, user: str) -> TradedMarketCount:
        """Get the number of markets a user has traded."""
        return await async_dispatch(
            self._ctx, _data_actions.get_traded_market_count_spec(user=user)
        )

    async def get_builder_volumes(
        self, *, time_period: BuilderVolumeTimePeriod | None = None
    ) -> tuple[BuilderVolumeEntry, ...]:
        """Get builder volume leaderboard entries."""
        return await async_dispatch(
            self._ctx, _data_actions.get_builder_volumes_spec(time_period=time_period)
        )

    def list_builder_trades(
        self,
        *,
        builder_code: str,
        market: str | None = None,
        token_id: str | None = None,
        id: str | None = None,
        after: str | None = None,
        before: str | None = None,
    ) -> AsyncPaginator[BuilderTrade]:
        """List builder-attributed trades.

        Returns:
            An async paginator over matching builder-attributed trades.
        """

        async def fetch(cursor: str | None) -> Page[BuilderTrade]:
            path, params = _builders_actions.build_list_builder_trades_request(
                builder_code=builder_code,
                market=market,
                token_id=token_id,
                id=id,
                after=after,
                before=before,
                cursor=cursor,
            )
            payload = await self._ctx.clob.get_json(path, params=params)
            return _builders_actions.parse_builder_trades_page(payload)

        return AsyncPaginator(fetch=fetch)

    def list_positions(
        self,
        *,
        user: str,
        market: str | Sequence[str] | None = None,
        event_id: int | Sequence[int] | None = None,
        size_threshold: float | None = None,
        redeemable: bool | None = None,
        mergeable: bool | None = None,
        sort_by: PositionSortBy | None = None,
        sort_direction: SortDirection | None = None,
        title: str | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Position]:
        """List open positions for a user.

        Returns:
            An async paginator over matching positions.
        """
        spec = _data_actions.list_positions_spec(
            user=user,
            market=market,
            event_id=event_id,
            size_threshold=size_threshold,
            redeemable=redeemable,
            mergeable=mergeable,
            sort_by=sort_by,
            sort_direction=sort_direction,
            title=title,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_closed_positions(
        self,
        *,
        user: str,
        market: str | Sequence[str] | None = None,
        event_id: int | Sequence[int] | None = None,
        title: str | None = None,
        sort_by: ClosedPositionSortBy | None = None,
        sort_direction: SortDirection | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[ClosedPosition]:
        """List closed positions for a user.

        Returns:
            An async paginator over matching closed positions.
        """
        spec = _data_actions.list_closed_positions_spec(
            user=user,
            market=market,
            event_id=event_id,
            title=title,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_combo_positions(
        self,
        *,
        user: str,
        status: ComboPositionStatus | None = None,
        sort: ComboPositionSort | None = None,
        condition_id: str | Sequence[str] | None = None,
        updated_after: int | None = None,
        updated_before: int | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[ComboPosition]:
        """List combo positions for a user.

        Returns:
            An async paginator over matching combo positions.
        """
        spec = _data_actions.list_combo_positions_spec(
            user=user,
            status=status,
            sort=sort,
            condition_id=condition_id,
            updated_after=updated_after,
            updated_before=updated_before,
        )
        return async_paginate_keyset(self._ctx, spec, page_size=page_size)

    def list_market_positions(
        self,
        *,
        market: str,
        user: str | None = None,
        status: MarketPositionStatus | None = None,
        sort_by: MarketPositionSortBy | None = None,
        sort_direction: SortDirection | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[MetaMarketPosition]:
        """List positions in a market.

        Returns:
            An async paginator over matching market positions.
        """
        spec = _data_actions.list_market_positions_spec(
            market=market,
            user=user,
            status=status,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_trades(
        self,
        *,
        user: str | None = None,
        market: Sequence[str] | None = None,
        event_id: Sequence[int] | None = None,
        side: TradeSide | None = None,
        taker_only: bool | None = None,
        filter_type: TradeFilterType | None = None,
        filter_amount: float | None = None,
        start: int | None = None,
        end: int | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Trade]:
        """List public trades.

        Returns:
            An async paginator over matching trades.
        """
        spec = _data_actions.list_trades_spec(
            user=user,
            market=market,
            event_id=event_id,
            side=side,
            taker_only=taker_only,
            filter_type=filter_type,
            filter_amount=filter_amount,
            start=start,
            end=end,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_activity(
        self,
        *,
        user: str,
        market: str | Sequence[str] | None = None,
        event_id: int | Sequence[int] | None = None,
        activity_types: Sequence[ActivityTypeFilter] | None = None,
        side: TradeSide | None = None,
        sort_by: ActivitySortBy | None = None,
        sort_direction: SortDirection | None = None,
        start: int | None = None,
        end: int | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Activity]:
        """List user activity.

        Returns:
            An async paginator over matching activity entries.
        """
        spec = _data_actions.list_activity_spec(
            user=user,
            market=market,
            event_id=event_id,
            activity_types=activity_types,
            side=side,
            sort_by=sort_by,
            sort_direction=sort_direction,
            start=start,
            end=end,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_combo_activity(
        self,
        *,
        user: str,
        condition_id: str | Sequence[str] | None = None,
        page_size: int = 50,
    ) -> AsyncPaginator[ComboActivity]:
        """List combo lifecycle activity for a user.

        Returns:
            An async paginator over matching combo lifecycle activity entries.
        """
        spec = _data_actions.list_combo_activity_spec(user=user, condition_id=condition_id)
        return async_paginate_keyset(self._ctx, spec, page_size=page_size)

    def list_builder_leaderboard(
        self,
        *,
        time_period: LeaderboardTimePeriod | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[LeaderboardEntry]:
        """List builder leaderboard entries.

        Returns:
            An async paginator over leaderboard rows.
        """
        spec = _data_actions.list_builder_leaderboard_spec(time_period=time_period)
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    async def download_accounting_snapshot(self, *, user: str) -> bytes:
        """Download the accounting snapshot archive for a user."""
        path, params = _data_actions.build_accounting_snapshot_request(user=user)
        return await self._ctx.data.get_bytes(path, params=params)

    def list_trader_leaderboard(
        self,
        *,
        category: LeaderboardCategory | None = None,
        time_period: LeaderboardTimePeriod | None = None,
        order_by: LeaderboardOrderBy | None = None,
        user: str | None = None,
        user_name: str | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[TraderLeaderboardEntry]:
        """List trader leaderboard entries.

        Returns:
            An async paginator over leaderboard rows.
        """
        spec = _data_actions.list_trader_leaderboard_spec(
            category=category,
            time_period=time_period,
            order_by=order_by,
            user=user,
            user_name=user_name,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_events(
        self,
        *,
        ascending: bool | None = None,
        closed: bool = False,
        cyom: bool | None = None,
        end_date_max: TimestampFilter | None = None,
        end_date_min: TimestampFilter | None = None,
        ended: bool | None = None,
        event_date: DateFilter | None = None,
        event_week: int | None = None,
        exclude_tag_ids: int | Sequence[int] | None = None,
        featured: bool | None = None,
        featured_order: bool | None = None,
        game_ids: int | Sequence[int] | None = None,
        ids: int | Sequence[int] | None = None,
        include_best_lines: bool | None = None,
        include_chat: bool | None = None,
        include_children: bool | None = None,
        include_template: bool | None = None,
        liquidity_max: float | None = None,
        liquidity_min: float | None = None,
        live: bool | None = None,
        locale: str | None = None,
        order: str | None = None,
        parent_event_id: int | None = None,
        partner_slug: str | None = None,
        recurrence: Recurrence | None = None,
        related_tags: bool | None = None,
        series_ids: int | Sequence[int] | None = None,
        slug: str | Sequence[str] | None = None,
        start_date_max: TimestampFilter | None = None,
        start_date_min: TimestampFilter | None = None,
        start_time_max: TimestampFilter | None = None,
        start_time_min: TimestampFilter | None = None,
        tag_ids: int | Sequence[int] | None = None,
        tag_match: TagMatch | None = None,
        tag_slug: str | None = None,
        title_search: str | None = None,
        volume_max: float | None = None,
        volume_min: float | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Event]:
        """List events.

        Defaults to open events. Pass ``closed=True`` to list settled events.

        Returns:
            An async paginator over matching events.

        Examples:
            Iterate over every page::

                async for page in client.list_events(page_size=10):
                    for event in page.items:
                        print(event.title)
        """
        spec = _gamma_actions.list_events_spec(
            ascending=ascending,
            closed=closed,
            cyom=cyom,
            end_date_max=end_date_max,
            end_date_min=end_date_min,
            ended=ended,
            event_date=event_date,
            event_week=event_week,
            exclude_tag_ids=exclude_tag_ids,
            featured=featured,
            featured_order=featured_order,
            game_ids=game_ids,
            ids=ids,
            include_best_lines=include_best_lines,
            include_chat=include_chat,
            include_children=include_children,
            include_template=include_template,
            liquidity_max=liquidity_max,
            liquidity_min=liquidity_min,
            live=live,
            locale=locale,
            order=order,
            parent_event_id=parent_event_id,
            partner_slug=partner_slug,
            recurrence=recurrence,
            related_tags=related_tags,
            series_ids=series_ids,
            slug=slug,
            start_date_max=start_date_max,
            start_date_min=start_date_min,
            start_time_max=start_time_max,
            start_time_min=start_time_min,
            tag_ids=tag_ids,
            tag_match=tag_match,
            tag_slug=tag_slug,
            title_search=title_search,
            volume_max=volume_max,
            volume_min=volume_min,
        )
        return async_paginate_keyset(self._ctx, spec, page_size=page_size)

    def list_markets(
        self,
        *,
        ascending: bool | None = None,
        closed: bool | None = None,
        clob_token_ids: str | Sequence[str] | None = None,
        condition_ids: str | Sequence[str] | None = None,
        cyom: bool | None = None,
        decimalized: bool | None = None,
        end_date_max: TimestampFilter | None = None,
        end_date_min: TimestampFilter | None = None,
        game_id: str | None = None,
        ids: int | Sequence[int] | None = None,
        include_tag: bool | None = None,
        liquidity_num_max: float | None = None,
        liquidity_num_min: float | None = None,
        locale: str | None = None,
        market_maker_addresses: str | Sequence[str] | None = None,
        order: str | None = None,
        position_ids: str | Sequence[str] | None = None,
        question_ids: str | Sequence[str] | None = None,
        related_tags: bool | None = None,
        rfq_enabled: bool | None = None,
        rewards_min_size: float | None = None,
        slug: str | Sequence[str] | None = None,
        sports_market_types: str | Sequence[str] | None = None,
        start_date_max: TimestampFilter | None = None,
        start_date_min: TimestampFilter | None = None,
        tag_id: int | None = None,
        tag_match: TagMatch | None = None,
        uma_resolution_status: str | None = None,
        volume_num_max: float | None = None,
        volume_num_min: float | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Market]:
        """List markets.

        Markets that cannot be represented by the binary Market model are
        omitted from results.

        Returns:
            An async paginator over matching markets.

        Examples:
            Iterate over individual market items::

                async for market in client.list_markets(closed=False).iter_items():
                    print(market.question)
        """
        spec = _gamma_actions.list_markets_spec(
            ascending=ascending,
            closed=closed,
            clob_token_ids=clob_token_ids,
            condition_ids=condition_ids,
            cyom=cyom,
            decimalized=decimalized,
            end_date_max=end_date_max,
            end_date_min=end_date_min,
            game_id=game_id,
            ids=ids,
            include_tag=include_tag,
            liquidity_num_max=liquidity_num_max,
            liquidity_num_min=liquidity_num_min,
            locale=locale,
            market_maker_addresses=market_maker_addresses,
            order=order,
            position_ids=position_ids,
            question_ids=question_ids,
            related_tags=related_tags,
            rfq_enabled=rfq_enabled,
            rewards_min_size=rewards_min_size,
            slug=slug,
            sports_market_types=sports_market_types,
            start_date_max=start_date_max,
            start_date_min=start_date_min,
            tag_id=tag_id,
            tag_match=tag_match,
            uma_resolution_status=uma_resolution_status,
            volume_num_max=volume_num_max,
            volume_num_min=volume_num_min,
        )
        return async_paginate_keyset(self._ctx, spec, page_size=page_size)

    def list_combo_markets(
        self,
        *,
        exclude: str | Sequence[str] | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[ComboMarket]:
        """List markets available for Combos.

        Returns:
            An async paginator over matching Combo markets.
        """
        spec = _rfq_actions.list_combo_markets_spec(exclude=exclude)
        return async_paginate_keyset(self._ctx, spec, page_size=page_size)

    def list_series(
        self,
        *,
        ascending: bool | None = None,
        closed: bool | None = None,
        exclude_events: bool | None = None,
        locale: str | None = None,
        order: str | None = None,
        recurrence: Recurrence | None = None,
        slug: str | Sequence[str] | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Series]:
        """List series.

        Returns:
            An async paginator over matching series.
        """
        spec = _gamma_actions.list_series_spec(
            ascending=ascending,
            closed=closed,
            exclude_events=exclude_events,
            locale=locale,
            order=order,
            recurrence=recurrence,
            slug=slug,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_tags(
        self,
        *,
        ascending: bool | None = None,
        include_template: bool | None = None,
        is_carousel: bool | None = None,
        locale: str | None = None,
        order: str | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Tag]:
        """List tags.

        Returns:
            An async paginator over matching tags.
        """
        spec = _gamma_actions.list_tags_spec(
            ascending=ascending,
            include_template=include_template,
            is_carousel=is_carousel,
            locale=locale,
            order=order,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_teams(
        self,
        *,
        abbreviation: str | Sequence[str] | None = None,
        ascending: bool | None = None,
        league: str | Sequence[str] | None = None,
        name: str | Sequence[str] | None = None,
        order: str | None = None,
        provider_ids: int | Sequence[int] | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Team]:
        """List teams.

        Returns:
            An async paginator over matching teams.
        """
        spec = _gamma_actions.list_teams_spec(
            abbreviation=abbreviation,
            ascending=ascending,
            league=league,
            name=name,
            order=order,
            provider_ids=provider_ids,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_comments(
        self,
        *,
        parent_entity_id: str,
        parent_entity_type: CommentParentEntityType,
        ascending: bool | None = None,
        get_positions: bool | None = None,
        holders_only: bool | None = None,
        order: str | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Comment]:
        """List comments for a market or event.

        Returns:
            An async paginator over matching comments.
        """
        spec = _gamma_actions.list_comments_spec(
            parent_entity_id=parent_entity_id,
            parent_entity_type=parent_entity_type,
            ascending=ascending,
            get_positions=get_positions,
            holders_only=holders_only,
            order=order,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_comments_by_user_address(
        self,
        *,
        address: str,
        ascending: bool | None = None,
        order: str | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Comment]:
        """List comments authored by a user address.

        Returns:
            An async paginator over matching comments.
        """
        spec = _gamma_actions.list_comments_by_user_address_spec(
            address=address,
            ascending=ascending,
            order=order,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def search(
        self,
        *,
        q: str,
        ascending: bool | None = None,
        cache: bool | None = None,
        events_status: str | None = None,
        events_tag: str | Sequence[str] | None = None,
        exclude_tag_ids: int | Sequence[int] | None = None,
        keep_closed_markets: int | None = None,
        optimized: bool | None = None,
        presets: str | Sequence[str] | None = None,
        recurrence: Recurrence | None = None,
        search_profiles: bool | None = None,
        search_tags: bool | None = None,
        sort: SearchSort | None = None,
        page_size: int = 10,
    ) -> AsyncPaginator[SearchResults]:
        """Search Polymarket content.

        Args:
            keep_closed_markets: Include markets closed within this many hours when
                searching active events.
            sort: Event sort field. Supported values are ``volume``, ``volume_24hr``,
                ``liquidity``, ``competitive``, ``closed_time``, ``start_date``, and
                ``end_date``.

        Returns:
            An async paginator over search result pages.
        """
        spec = _gamma_actions.search_spec(
            q=q,
            ascending=ascending,
            cache=cache,
            events_status=events_status,
            events_tag=events_tag,
            exclude_tag_ids=exclude_tag_ids,
            keep_closed_markets=keep_closed_markets,
            optimized=optimized,
            presets=presets,
            recurrence=recurrence,
            search_profiles=search_profiles,
            search_tags=search_tags,
            sort=sort,
        )
        return async_paginate_page_based(self._ctx, spec, page_size=page_size)

    async def get_midpoint(self, *, token_id: str) -> Decimal:
        """Get the midpoint price for a token."""
        path, params = _clob_actions.build_midpoint_request(token_id=token_id)
        return _clob_actions.parse_midpoint(await self._ctx.clob.get_json(path, params=params))

    async def get_midpoints(self, *, token_ids: Sequence[str]) -> dict[str, Decimal]:
        """Get midpoint prices for multiple tokens."""
        path, body = _clob_actions.build_midpoints_request(token_ids=token_ids)
        return _clob_actions.parse_midpoints(await self._ctx.clob.post_json(path, json=body))

    async def get_price(self, *, token_id: str, side: OrderSide) -> Decimal:
        """Get the executable price for a token side."""
        path, params = _clob_actions.build_price_request(token_id=token_id, side=side)
        return _clob_actions.parse_price(await self._ctx.clob.get_json(path, params=params))

    async def get_prices(
        self, *, requests: Sequence[PriceRequest]
    ) -> dict[str, dict[OrderSide, Decimal]]:
        """Get executable prices for multiple token-side requests."""
        path, body = _clob_actions.build_prices_request(requests=requests)
        return _clob_actions.parse_prices(await self._ctx.clob.post_json(path, json=body))

    async def get_order_book(self, *, token_id: str) -> OrderBook:
        """Get the order book for a token."""
        path, params = _clob_actions.build_order_book_request(token_id=token_id)
        return _clob_actions.parse_order_book(await self._ctx.clob.get_json(path, params=params))

    async def get_order_books(self, *, token_ids: Sequence[str]) -> tuple[OrderBook, ...]:
        """Get order books for multiple tokens."""
        path, body = _clob_actions.build_order_books_request(token_ids=token_ids)
        return _clob_actions.parse_order_books(await self._ctx.clob.post_json(path, json=body))

    async def get_spread(self, *, token_id: str) -> Decimal:
        """Get the bid-ask spread for a token."""
        path, params = _clob_actions.build_spread_request(token_id=token_id)
        return _clob_actions.parse_spread(await self._ctx.clob.get_json(path, params=params))

    async def get_spreads(self, *, token_ids: Sequence[str]) -> dict[str, Decimal]:
        """Get bid-ask spreads for multiple tokens."""
        path, body = _clob_actions.build_spreads_request(token_ids=token_ids)
        return _clob_actions.parse_spreads(await self._ctx.clob.post_json(path, json=body))

    async def get_last_trade_price(self, *, token_id: str) -> LastTradePrice:
        """Get the most recent trade price for a token."""
        path, params = _clob_actions.build_last_trade_price_request(token_id=token_id)
        return _clob_actions.parse_last_trade_price(
            await self._ctx.clob.get_json(path, params=params)
        )

    async def get_last_trade_prices(
        self, *, token_ids: Sequence[str]
    ) -> tuple[LastTradePriceForToken, ...]:
        """Get the most recent trade prices for multiple tokens."""
        path, body = _clob_actions.build_last_trade_prices_request(token_ids=token_ids)
        return _clob_actions.parse_last_trade_prices(
            await self._ctx.clob.post_json(path, json=body)
        )

    async def get_price_history(
        self,
        *,
        token_id: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        fidelity: int | None = None,
        interval: PriceHistoryInterval | None = None,
    ) -> tuple[PriceHistoryPoint, ...]:
        """Get historical price points for a token."""
        path, params = _clob_actions.build_price_history_request(
            token_id=token_id,
            start_ts=start_ts,
            end_ts=end_ts,
            fidelity=fidelity,
            interval=interval,
        )
        return _clob_actions.parse_price_history(await self._ctx.clob.get_json(path, params=params))

    @overload
    async def estimate_market_price(
        self,
        *,
        token_id: str,
        side: Literal["BUY"],
        amount: Decimal | int | float | str,
        order_type: MarketOrderType = "FOK",
    ) -> Decimal: ...
    @overload
    async def estimate_market_price(
        self,
        *,
        token_id: str,
        side: Literal["SELL"],
        shares: Decimal | int | float | str,
        order_type: MarketOrderType = "FOK",
    ) -> Decimal: ...
    async def estimate_market_price(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | int | float | str | None = None,
        shares: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FOK",
    ) -> Decimal:
        """Estimate the average execution price for a market order.

        BUY orders use ``amount`` as the spend amount. SELL orders use ``shares``
        as the number of shares to sell.
        """
        return await _estimate_market_price(
            self._ctx,
            token_id=token_id,
            side=side,
            amount=amount,
            shares=shares,
            order_type=order_type,
        )

    def list_current_rewards(
        self, *, sponsored: bool | None = None
    ) -> AsyncPaginator[CurrentReward]:
        """List current rewards.

        Returns:
            An async paginator over current reward configurations.
        """

        async def fetch(cursor: str | None) -> Page[CurrentReward]:
            path, params = _rewards_actions.build_list_current_rewards_request(
                sponsored=sponsored, cursor=cursor
            )
            return _rewards_actions.parse_current_rewards_page(
                await self._ctx.clob.get_json(path, params=params)
            )

        return AsyncPaginator(fetch=fetch)

    def list_market_rewards(
        self, *, condition_id: str, sponsored: bool | None = None
    ) -> AsyncPaginator[MarketReward]:
        """List rewards for a market condition.

        Returns:
            An async paginator over matching market reward configurations.
        """

        async def fetch(cursor: str | None) -> Page[MarketReward]:
            path, params = _rewards_actions.build_list_market_rewards_request(
                condition_id=CtfConditionId(condition_id), sponsored=sponsored, cursor=cursor
            )
            return _rewards_actions.parse_market_rewards_page(
                await self._ctx.clob.get_json(path, params=params)
            )

        return AsyncPaginator(fetch=fetch)

    async def fetch_perps_instruments(
        self,
        *,
        instrument_id: int | None = None,
        category: PerpsInstrumentCategory | None = None,
    ) -> tuple[PerpsInstrument, ...]:
        """Fetch Perps instruments, optionally filtered by instrument or category."""
        return await _perps_actions.fetch_instruments(
            self._ctx.perps, instrument_id=instrument_id, category=category
        )

    async def fetch_perps_ticker(self, *, instrument_id: int) -> PerpsTicker:
        """Fetch the current Perps ticker for an instrument."""
        return await _perps_actions.fetch_ticker(self._ctx.perps, instrument_id=instrument_id)

    async def fetch_perps_tickers(
        self, *, instrument_id: int | None = None
    ) -> tuple[PerpsTicker, ...]:
        """Fetch current Perps tickers."""
        return await _perps_actions.fetch_tickers(self._ctx.perps, instrument_id=instrument_id)

    async def fetch_perps_book(
        self, *, instrument_id: int, depth: PerpsBookDepth = 100
    ) -> PerpsBook:
        """Fetch a Perps order book snapshot.

        ``depth`` controls the number of price levels returned on each side.
        """
        return await _perps_actions.fetch_book(
            self._ctx.perps, instrument_id=instrument_id, depth=depth
        )

    async def fetch_perps_fees(self) -> tuple[PerpsFeeScheduleEntry, ...]:
        """Fetch the Perps fee schedule."""
        return await _perps_actions.fetch_fees(self._ctx.perps)

    def list_perps_candles(
        self,
        *,
        instrument_id: int,
        interval: PerpsKlineInterval,
        start: "datetime | int | None" = None,
        end: "datetime | int | None" = None,
    ) -> AsyncPaginator[PerpsCandle]:
        """List Perps candles for an instrument with SDK-owned pagination.

        Defaults to the past 24 hours when ``start`` is omitted. ``start`` and
        ``end`` accept a ``datetime`` or an epoch-milliseconds int.

        Returns:
            An async paginator over matching candles.
        """
        return _perps_actions.list_candles(
            self._ctx.perps,
            instrument_id=instrument_id,
            interval=interval,
            start=start,
            end=end,
        )

    def list_perps_funding_history(
        self,
        *,
        instrument_id: int,
        start: "datetime | int | None" = None,
        end: "datetime | int | None" = None,
    ) -> AsyncPaginator[PerpsFundingRate]:
        """List Perps funding-rate history with SDK-owned pagination.

        Defaults to the past 24 hours when ``start`` is omitted. ``start`` and
        ``end`` accept a ``datetime`` or an epoch-milliseconds int.

        Returns:
            An async paginator over funding-rate observations.
        """
        return _perps_actions.list_funding_history(
            self._ctx.perps, instrument_id=instrument_id, start=start, end=end
        )

    def list_perps_trades(
        self,
        *,
        instrument_id: int,
        start: "datetime | int | None" = None,
        end: "datetime | int | None" = None,
    ) -> AsyncPaginator[PerpsTrade]:
        """List recent public Perps trades with SDK-owned pagination.

        Defaults to the past 24 hours when ``start`` is omitted. ``start`` and
        ``end`` accept a ``datetime`` or an epoch-milliseconds int.

        Returns:
            An async paginator over matching trades.
        """
        return _perps_actions.list_trades(
            self._ctx.perps, instrument_id=instrument_id, start=start, end=end
        )
