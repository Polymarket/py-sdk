"""Synchronous public Polymarket client."""

import logging
from collections.abc import Sequence
from decimal import Decimal
from types import TracebackType
from typing import Literal, Self, overload

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
    estimate_market_price_sync as _estimate_market_price_sync,
)
from polymarket._internal.actions.orders.types import MarketOrderType
from polymarket._internal.context import SyncClientContext
from polymarket._internal.dispatch import (
    sync_dispatch,
    sync_paginate_keyset,
    sync_paginate_offset,
    sync_paginate_page_based,
)
from polymarket._internal.environment import get_environment_config
from polymarket.clients._transport import SyncTransport
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
from polymarket.models.clob import BuilderTrade
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
from polymarket.models.types import CtfConditionId, TokenId
from polymarket.pagination import Page, Paginator


class PublicClient:
    """Client for public Polymarket data workflows.

    Public methods return stable, idiomatic Python SDK objects.
    """

    def __init__(
        self,
        environment: Environment = PRODUCTION,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        config = get_environment_config(environment)
        self._ctx = SyncClientContext(
            environment=environment,
            _resolved_environment_config=config,
            gamma=SyncTransport(base_url=config.gamma_url, logger=logger),
            data=SyncTransport(base_url=config.data_url, logger=logger),
            rfq=SyncTransport(base_url=config.rfq_url, logger=logger),
            clob=SyncTransport(base_url=config.clob_url, logger=logger),
        )

    @property
    def environment(self) -> Environment:
        """Environment this client sends requests to."""
        return self._ctx.environment

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying network transports."""
        try:
            self._ctx.gamma.close()
        finally:
            try:
                self._ctx.data.close()
            finally:
                try:
                    self._ctx.rfq.close()
                finally:
                    self._ctx.clob.close()

    @overload
    def get_market(
        self, *, id: str, include_tag: bool | None = None, locale: str | None = None
    ) -> Market: ...
    @overload
    def get_market(
        self, *, slug: str, include_tag: bool | None = None, locale: str | None = None
    ) -> Market: ...
    @overload
    def get_market(
        self, *, url: str, include_tag: bool | None = None, locale: str | None = None
    ) -> Market: ...
    def get_market(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        url: str | None = None,
        include_tag: bool | None = None,
        locale: str | None = None,
    ) -> Market:
        """Get a market.

        Markets that cannot be represented by the binary Market model raise
        UnexpectedResponseError.
        """
        return sync_dispatch(
            self._ctx,
            _gamma_actions.get_market_spec(
                id=id, slug=slug, url=url, include_tag=include_tag, locale=locale
            ),
        )

    def get_market_tags(self, id: str) -> tuple[TagReference, ...]:
        """Get a market's tags."""
        return sync_dispatch(self._ctx, _gamma_actions.get_market_tags_spec(id))

    @overload
    def get_event(
        self,
        *,
        id: str,
        include_best_lines: bool | None = None,
        include_chat: bool | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Event: ...
    @overload
    def get_event(
        self,
        *,
        slug: str,
        include_best_lines: bool | None = None,
        include_chat: bool | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Event: ...
    @overload
    def get_event(
        self,
        *,
        url: str,
        include_best_lines: bool | None = None,
        include_chat: bool | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Event: ...
    def get_event(
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
        """Get an event."""
        return sync_dispatch(
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

    def get_event_tags(self, id: str) -> tuple[TagReference, ...]:
        """Get an event's tags."""
        return sync_dispatch(self._ctx, _gamma_actions.get_event_tags_spec(id))

    def get_series(
        self,
        id: str,
        *,
        locale: str | None = None,
    ) -> Series:
        """Get a series."""
        return sync_dispatch(
            self._ctx,
            _gamma_actions.get_series_spec(id, locale=locale),
        )

    @overload
    def get_tag(
        self, *, id: str, include_template: bool | None = None, locale: str | None = None
    ) -> Tag: ...
    @overload
    def get_tag(self, *, slug: str, locale: str | None = None) -> Tag: ...
    def get_tag(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Tag:
        """Get a tag."""
        return sync_dispatch(
            self._ctx,
            _gamma_actions.get_tag_spec(
                id=id,
                slug=slug,
                include_template=include_template,
                locale=locale,
            ),
        )

    def get_related_tags(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        omit_empty: bool | None = None,
        status: str | None = None,
    ) -> tuple[RelatedTag, ...]:
        """Get related tag relationships."""
        return sync_dispatch(
            self._ctx,
            _gamma_actions.get_related_tags_spec(
                id=id, slug=slug, omit_empty=omit_empty, status=status
            ),
        )

    def get_related_tag_resources(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        locale: str | None = None,
        omit_empty: bool | None = None,
        status: str | None = None,
    ) -> tuple[Tag, ...]:
        """Get tag resources linked from related tag relationships."""
        return sync_dispatch(
            self._ctx,
            _gamma_actions.get_related_tag_resources_spec(
                id=id, slug=slug, locale=locale, omit_empty=omit_empty, status=status
            ),
        )

    def get_sports(self) -> tuple[SportsMetadata, ...]:
        """Get available sports metadata."""
        return sync_dispatch(self._ctx, _gamma_actions.get_sports_spec())

    def get_sports_market_types(self) -> SportsMarketTypes:
        """Get available sports market types."""
        return sync_dispatch(self._ctx, _gamma_actions.get_sports_market_types_spec())

    def get_public_profile(self, address: str) -> PublicProfile | None:
        """Get a public profile by wallet address. Returns None if no profile exists."""
        try:
            return sync_dispatch(self._ctx, _gamma_actions.get_public_profile_spec(address))
        except RequestRejectedError as error:
            if error.status == 404:
                return None
            raise

    def get_comment_thread(
        self, id: str, *, get_positions: bool | None = None
    ) -> tuple[Comment, ...]:
        """Get a comment thread by comment ID."""
        return sync_dispatch(
            self._ctx,
            _gamma_actions.get_comment_thread_spec(id, get_positions=get_positions),
        )

    def get_event_live_volumes(self, *, id: str) -> tuple[LiveVolume, ...]:
        """Get live volume entries for an event."""
        return sync_dispatch(self._ctx, _data_actions.get_event_live_volumes_spec(id=id))

    def get_open_interests(
        self, *, market: Sequence[str] | None = None
    ) -> tuple[OpenInterest, ...]:
        """Get open interest values, optionally filtered by market ids."""
        return sync_dispatch(self._ctx, _data_actions.get_open_interests_spec(market=market))

    def get_market_holders(
        self,
        *,
        market: Sequence[str],
        limit: int | None = None,
        min_balance: int | None = None,
    ) -> tuple[MetaHolder, ...]:
        """Get holder balances for one or more markets."""
        return sync_dispatch(
            self._ctx,
            _data_actions.get_market_holders_spec(
                market=market, limit=limit, min_balance=min_balance
            ),
        )

    def get_portfolio_values(
        self, *, user: str, market: Sequence[str] | None = None
    ) -> tuple[PortfolioValue, ...]:
        """Get portfolio value snapshots for a user."""
        return sync_dispatch(
            self._ctx, _data_actions.get_portfolio_values_spec(user=user, market=market)
        )

    def get_traded_market_count(self, *, user: str) -> TradedMarketCount:
        """Get the number of markets a user has traded."""
        return sync_dispatch(self._ctx, _data_actions.get_traded_market_count_spec(user=user))

    def get_builder_volumes(
        self, *, time_period: BuilderVolumeTimePeriod | None = None
    ) -> tuple[BuilderVolumeEntry, ...]:
        """Get builder volume leaderboard entries."""
        return sync_dispatch(
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
    ) -> Paginator[BuilderTrade]:
        """List builder-attributed trades.

        Returns:
            A paginator. Use ``first_page()``, iterate over pages, or call ``iter_items()``
            to stream individual trades.
        """

        def fetch(cursor: str | None) -> Page[BuilderTrade]:
            path, params = _builders_actions.build_list_builder_trades_request(
                builder_code=builder_code,
                market=market,
                token_id=token_id,
                id=id,
                after=after,
                before=before,
                cursor=cursor,
            )
            payload = self._ctx.clob.get_json(path, params=params)
            return _builders_actions.parse_builder_trades_page(payload)

        return Paginator(fetch=fetch)

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
    ) -> Paginator[Position]:
        """List open positions for a user.

        Returns:
            A paginator over matching positions.
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
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[ClosedPosition]:
        """List closed positions for a user.

        Returns:
            A paginator over matching closed positions.
        """
        spec = _data_actions.list_closed_positions_spec(
            user=user,
            market=market,
            event_id=event_id,
            title=title,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[ComboPosition]:
        """List combo positions for a user.

        Returns:
            A paginator over matching combo positions.
        """
        spec = _data_actions.list_combo_positions_spec(
            user=user,
            status=status,
            sort=sort,
            condition_id=condition_id,
            updated_after=updated_after,
            updated_before=updated_before,
        )
        return sync_paginate_keyset(self._ctx, spec, page_size=page_size)

    def list_market_positions(
        self,
        *,
        market: str,
        user: str | None = None,
        status: MarketPositionStatus | None = None,
        sort_by: MarketPositionSortBy | None = None,
        sort_direction: SortDirection | None = None,
        page_size: int = 20,
    ) -> Paginator[MetaMarketPosition]:
        """List positions in a market.

        Returns:
            A paginator over matching market positions.
        """
        spec = _data_actions.list_market_positions_spec(
            market=market,
            user=user,
            status=status,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[Trade]:
        """List public trades.

        Returns:
            A paginator over matching trades.
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
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[Activity]:
        """List user activity.

        Returns:
            A paginator over matching activity entries.
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
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_combo_activity(
        self,
        *,
        user: str,
        condition_id: str | Sequence[str] | None = None,
        page_size: int = 50,
    ) -> Paginator[ComboActivity]:
        """List combo lifecycle activity for a user.

        Returns:
            A paginator over matching combo lifecycle activity entries.
        """
        spec = _data_actions.list_combo_activity_spec(user=user, condition_id=condition_id)
        return sync_paginate_keyset(self._ctx, spec, page_size=page_size)

    def list_builder_leaderboard(
        self,
        *,
        time_period: LeaderboardTimePeriod | None = None,
        page_size: int = 20,
    ) -> Paginator[LeaderboardEntry]:
        """List builder leaderboard entries.

        Returns:
            A paginator over leaderboard rows.
        """
        spec = _data_actions.list_builder_leaderboard_spec(time_period=time_period)
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

    def download_accounting_snapshot(self, *, user: str) -> bytes:
        """Download the accounting snapshot archive for a user."""
        path, params = _data_actions.build_accounting_snapshot_request(user=user)
        return self._ctx.data.get_bytes(path, params=params)

    def list_trader_leaderboard(
        self,
        *,
        category: LeaderboardCategory | None = None,
        time_period: LeaderboardTimePeriod | None = None,
        order_by: LeaderboardOrderBy | None = None,
        user: str | None = None,
        user_name: str | None = None,
        page_size: int = 20,
    ) -> Paginator[TraderLeaderboardEntry]:
        """List trader leaderboard entries.

        Returns:
            A paginator over leaderboard rows.
        """
        spec = _data_actions.list_trader_leaderboard_spec(
            category=category,
            time_period=time_period,
            order_by=order_by,
            user=user,
            user_name=user_name,
        )
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[Event]:
        """List events.

        Defaults to open events. Pass ``closed=True`` to list settled events.

        Returns:
            A paginator over matching events.

        Examples:
            Fetch the first page::

                paginator = client.list_events(page_size=10)
                first_page = paginator.first_page()

            Iterate over all pages::

                for page in client.list_events(page_size=10):
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
        return sync_paginate_keyset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[Market]:
        """List markets.

        Markets that cannot be represented by the binary Market model are
        omitted from results.

        Returns:
            A paginator over matching markets.

        Examples:
            Fetch the first page::

                paginator = client.list_markets(closed=False, page_size=10)
                first_page = paginator.first_page()

            Iterate over every market item::

                for market in client.list_markets(closed=False).iter_items():
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
        return sync_paginate_keyset(self._ctx, spec, page_size=page_size)

    def list_combo_markets(
        self,
        *,
        exclude: str | Sequence[str] | None = None,
        page_size: int = 20,
    ) -> Paginator[ComboMarket]:
        """List markets available for Combos.

        Returns:
            A paginator over matching Combo markets.
        """
        spec = _rfq_actions.list_combo_markets_spec(exclude=exclude)
        return sync_paginate_keyset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[Series]:
        """List series.

        Returns:
            A paginator over matching series.
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
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_tags(
        self,
        *,
        ascending: bool | None = None,
        include_template: bool | None = None,
        is_carousel: bool | None = None,
        locale: str | None = None,
        order: str | None = None,
        page_size: int = 20,
    ) -> Paginator[Tag]:
        """List tags.

        Returns:
            A paginator over matching tags.
        """
        spec = _gamma_actions.list_tags_spec(
            ascending=ascending,
            include_template=include_template,
            is_carousel=is_carousel,
            locale=locale,
            order=order,
        )
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[Team]:
        """List teams.

        Returns:
            A paginator over matching teams.
        """
        spec = _gamma_actions.list_teams_spec(
            abbreviation=abbreviation,
            ascending=ascending,
            league=league,
            name=name,
            order=order,
            provider_ids=provider_ids,
        )
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[Comment]:
        """List comments for a market or event.

        Returns:
            A paginator over matching comments.
        """
        spec = _gamma_actions.list_comments_spec(
            parent_entity_id=parent_entity_id,
            parent_entity_type=parent_entity_type,
            ascending=ascending,
            get_positions=get_positions,
            holders_only=holders_only,
            order=order,
        )
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_comments_by_user_address(
        self,
        *,
        address: str,
        ascending: bool | None = None,
        order: str | None = None,
        page_size: int = 20,
    ) -> Paginator[Comment]:
        """List comments authored by a user address.

        Returns:
            A paginator over matching comments.
        """
        spec = _gamma_actions.list_comments_by_user_address_spec(
            address=address,
            ascending=ascending,
            order=order,
        )
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[SearchResults]:
        """Search Polymarket content.

        Args:
            keep_closed_markets: Include markets closed within this many hours when
                searching active events.
            sort: Event sort field. Supported values are ``volume``, ``volume_24hr``,
                ``liquidity``, ``competitive``, ``closed_time``, ``start_date``, and
                ``end_date``.

        Returns:
            A paginator over search result pages.

        Examples:
            Search markets and events::

                for result in client.search(q="election").iter_items():
                    print(result)
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
        return sync_paginate_page_based(self._ctx, spec, page_size=page_size)

    def get_midpoint(self, *, token_id: str) -> Decimal:
        """Get the midpoint price for a token."""
        path, params = _clob_actions.build_midpoint_request(token_id=token_id)
        return _clob_actions.parse_midpoint(self._ctx.clob.get_json(path, params=params))

    def get_midpoints(self, *, token_ids: Sequence[str]) -> dict[TokenId, Decimal]:
        """Get midpoint prices for multiple tokens."""
        path, body = _clob_actions.build_midpoints_request(token_ids=token_ids)
        return _clob_actions.parse_midpoints(self._ctx.clob.post_json(path, json=body))

    def get_price(self, *, token_id: str, side: OrderSide) -> Decimal:
        """Get the executable price for a token side."""
        path, params = _clob_actions.build_price_request(token_id=token_id, side=side)
        return _clob_actions.parse_price(self._ctx.clob.get_json(path, params=params))

    def get_prices(
        self, *, requests: Sequence[PriceRequest]
    ) -> dict[TokenId, dict[OrderSide, Decimal]]:
        """Get executable prices for multiple token-side requests."""
        path, body = _clob_actions.build_prices_request(requests=requests)
        return _clob_actions.parse_prices(self._ctx.clob.post_json(path, json=body))

    def get_order_book(self, *, token_id: str) -> OrderBook:
        """Get the order book for a token."""
        path, params = _clob_actions.build_order_book_request(token_id=token_id)
        return _clob_actions.parse_order_book(self._ctx.clob.get_json(path, params=params))

    def get_order_books(self, *, token_ids: Sequence[str]) -> tuple[OrderBook, ...]:
        """Get order books for multiple tokens."""
        path, body = _clob_actions.build_order_books_request(token_ids=token_ids)
        return _clob_actions.parse_order_books(self._ctx.clob.post_json(path, json=body))

    def get_spread(self, *, token_id: str) -> Decimal:
        """Get the bid-ask spread for a token."""
        path, params = _clob_actions.build_spread_request(token_id=token_id)
        return _clob_actions.parse_spread(self._ctx.clob.get_json(path, params=params))

    def get_spreads(self, *, token_ids: Sequence[str]) -> dict[TokenId, Decimal]:
        """Get bid-ask spreads for multiple tokens."""
        path, body = _clob_actions.build_spreads_request(token_ids=token_ids)
        return _clob_actions.parse_spreads(self._ctx.clob.post_json(path, json=body))

    def get_last_trade_price(self, *, token_id: str) -> LastTradePrice | None:
        """Get the most recent trade price for a token.

        Returns ``None`` when the token has not traded.
        """
        path, params = _clob_actions.build_last_trade_price_request(token_id=token_id)
        return _clob_actions.parse_last_trade_price(self._ctx.clob.get_json(path, params=params))

    def get_last_trade_prices(
        self, *, token_ids: Sequence[str]
    ) -> tuple[LastTradePriceForToken, ...]:
        """Get the most recent trade prices for multiple tokens.

        Tokens without trades are omitted. Match returned entries by ``token_id``;
        the result is not positionally aligned with ``token_ids``.
        """
        path, body = _clob_actions.build_last_trade_prices_request(token_ids=token_ids)
        return _clob_actions.parse_last_trade_prices(self._ctx.clob.post_json(path, json=body))

    def get_price_history(
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
        return _clob_actions.parse_price_history(self._ctx.clob.get_json(path, params=params))

    @overload
    def estimate_market_price(
        self,
        *,
        token_id: str,
        side: Literal["BUY"],
        amount: Decimal | int | float | str,
        order_type: MarketOrderType = "FOK",
    ) -> Decimal: ...
    @overload
    def estimate_market_price(
        self,
        *,
        token_id: str,
        side: Literal["SELL"],
        shares: Decimal | int | float | str,
        order_type: MarketOrderType = "FOK",
    ) -> Decimal: ...
    def estimate_market_price(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | int | float | str | None = None,
        shares: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FOK",
    ) -> Decimal:
        """Estimate the limiting price level for a market order.

        BUY orders use ``amount`` as the spend amount. SELL orders use ``shares``
        as the number of shares to sell.

        Raises:
            UserInputError: If the side-specific amount is missing or invalid.
            InsufficientLiquidityError: If available liquidity cannot fill the order.
        """
        return _estimate_market_price_sync(
            self._ctx,
            token_id=token_id,
            side=side,
            amount=amount,
            shares=shares,
            order_type=order_type,
        )

    def list_current_rewards(self, *, sponsored: bool | None = None) -> Paginator[CurrentReward]:
        """List current rewards.

        Returns:
            A paginator over current reward configurations.
        """

        def fetch(cursor: str | None) -> Page[CurrentReward]:
            path, params = _rewards_actions.build_list_current_rewards_request(
                sponsored=sponsored, cursor=cursor
            )
            return _rewards_actions.parse_current_rewards_page(
                self._ctx.clob.get_json(path, params=params)
            )

        return Paginator(fetch=fetch)

    def list_market_rewards(
        self, *, condition_id: str, sponsored: bool | None = None
    ) -> Paginator[MarketReward]:
        """List rewards for a market condition.

        Returns:
            A paginator over matching market reward configurations.
        """

        def fetch(cursor: str | None) -> Page[MarketReward]:
            path, params = _rewards_actions.build_list_market_rewards_request(
                condition_id=CtfConditionId(condition_id), sponsored=sponsored, cursor=cursor
            )
            return _rewards_actions.parse_market_rewards_page(
                self._ctx.clob.get_json(path, params=params)
            )

        return Paginator(fetch=fetch)
