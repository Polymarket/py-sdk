import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Self, TypeAlias, assert_never, cast, overload

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils.address import to_checksum_address

from polymarket._internal.actions import account as _account_actions
from polymarket._internal.actions import auth as _auth_actions
from polymarket._internal.actions import builders as _builders_actions
from polymarket._internal.actions import clob as _clob_actions
from polymarket._internal.actions import data as _data_actions
from polymarket._internal.actions import gamma as _gamma_actions
from polymarket._internal.actions import rewards as _rewards_actions
from polymarket._internal.actions.data import (
    ActivitySortBy,
    ActivityTypeFilter,
    ClosedPositionSortBy,
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
    TagMatch,
    TimestampFilter,
)
from polymarket._internal.actions.orders import cancel as _cancel_actions
from polymarket._internal.actions.orders import post as _post_actions
from polymarket._internal.actions.orders.estimate import (
    estimate_market_price as _estimate_market_price,
)
from polymarket._internal.actions.orders.limit import (
    prepare_limit_order_draft,
    validate_limit_order_params,
)
from polymarket._internal.actions.orders.market import (
    prepare_market_order_draft,
    validate_market_order_params,
)
from polymarket._internal.actions.orders.orders import (
    create_signed_order,
    create_unsigned_order,
)
from polymarket._internal.actions.orders.place import (
    post_order_with_allowance_recovery,
)
from polymarket._internal.actions.orders.typed_data import (
    build_order_signature,
    build_order_typed_data,
)
from polymarket._internal.actions.orders.types import OrderDraft
from polymarket._internal.actions.relayer.auth import make_relayer_header_resolver
from polymarket._internal.actions.relayer.calls import (
    MAX_UINT256,
    TransactionCall,
    ctf_redeem_positions_call,
    erc20_approval_call,
    erc20_transfer_call,
    erc1155_set_approval_for_all_call,
    merge_positions_call,
    split_position_call,
)
from polymarket._internal.actions.relayer.deployed import fetch_deployed
from polymarket._internal.actions.relayer.gasless import (
    prepare_gasless_transaction,
    submit_deposit_wallet_create,
)
from polymarket._internal.actions.relayer.positions import (
    expect_binary_positions,
    expect_negative_risk_flag,
    resolve_binary_positions_condition_id,
    resolve_merge_amount,
)
from polymarket._internal.context import AsyncSecureClientContext
from polymarket._internal.dispatch import (
    async_dispatch,
    async_paginate_keyset,
    async_paginate_offset,
    async_paginate_page_based,
)
from polymarket._internal.eoa.broadcast import broadcast_eoa_call
from polymarket._internal.eoa.rpc import JsonRpcClient
from polymarket._internal.hmac import build_hmac_signature
from polymarket._internal.l1_auth import sign_api_key_auth
from polymarket._internal.streams.handle import AsyncSubscriptionHandle, SubscriptionHandle
from polymarket._internal.wallet import (
    WalletType,
    classify_wallet_type,
    derive_current_deposit_wallet_address,
    signature_type_for,
)
from polymarket.auth import ApiKey, BuilderApiKey
from polymarket.clients._transport import AsyncTransport
from polymarket.clients.async_public import AsyncPublicClient
from polymarket.environments import PRODUCTION, Environment
from polymarket.errors import (
    RequestRejectedError,
    SigningError,
    UnexpectedResponseError,
    UserInputError,
)
from polymarket.models import (
    ApiKeyCreds,
    AssetType,
    BalanceAllowance,
    BuilderApiKeyInfo,
    BuilderFeeRates,
    BuilderTrade,
    ClobTrade,
    Comment,
    Event,
    LastTradePrice,
    LastTradePriceForToken,
    Market,
    Notification,
    OpenOrder,
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
from polymarket.models.clob.cancel import CancelOrdersResponse
from polymarket.models.clob.market_events import MarketEvent
from polymarket.models.clob.order_response import OrderResponse
from polymarket.models.clob.orders import MarketOrderType, SignedOrder
from polymarket.models.clob.relayer import RelayerTransactionType
from polymarket.models.clob.rewards import (
    CurrentReward,
    MarketReward,
    RewardsPercentages,
    TotalUserEarning,
    UserEarning,
    UserRewardsEarning,
)
from polymarket.models.clob.user_events import UserEvent
from polymarket.models.data import (
    Activity,
    BuilderVolumeEntry,
    BuilderVolumeTimePeriod,
    ClosedPosition,
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
from polymarket.models.rtds_events import (
    CommentsEvent,
    CryptoPricesEvent,
    EquityPricesEvent,
    RtdsEvent,
)
from polymarket.models.sports_events import SportsEvent
from polymarket.models.types import ConditionId
from polymarket.pagination import AsyncPaginator, Page
from polymarket.streams._specs import (
    CommentsSpec,
    CryptoPricesSpec,
    EquityPricesSpec,
    MarketSpec,
    SecureSubscription,
    SportsSpec,
    UserSpec,
    _normalize_specs,
)
from polymarket.transactions import (
    EoaTransactionHandle,
    TransactionHandle,
)
from polymarket.types import EvmAddress, HexString

if TYPE_CHECKING:
    from polymarket._internal.streams.clob.market import ClobMarketStreamManager
    from polymarket._internal.streams.clob.user import ClobUserStreamManager
    from polymarket._internal.streams.rtds.manager import RtdsStreamManager
    from polymarket._internal.streams.sports.manager import SportsStreamManager


_CREATE_TOKEN = object()

_L2HeaderResolver: TypeAlias = Callable[[str, str, str | None], Awaitable[Mapping[str, str]]]


class AsyncSecureClient:
    """Async client for authenticated account, trading, wallet, and stream workflows.

    Create instances with :meth:`AsyncSecureClient.create` so the SDK can derive
    or validate credentials before authenticated requests are made.
    """

    def __init__(
        self,
        *,
        ctx: AsyncSecureClientContext,
        _create_token: object | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if _create_token is not _CREATE_TOKEN:
            raise RuntimeError("Use AsyncSecureClient.create(...) to create a secure client")
        self._ended = False
        self._ctx_inner = ctx
        self._market_manager: ClobMarketStreamManager | None = None
        self._sports_manager: SportsStreamManager | None = None
        self._rtds_manager: RtdsStreamManager | None = None
        self._user_manager: ClobUserStreamManager | None = None
        self._streams_logger = logger

    @property
    def _ctx(self) -> AsyncSecureClientContext:
        if self._ended:
            raise RuntimeError(
                "AsyncSecureClient has ended authentication; use the returned "
                "AsyncPublicClient or create a new SecureClient."
            )
        return self._ctx_inner

    @_ctx.setter
    def _ctx(self, value: AsyncSecureClientContext) -> None:
        self._ctx_inner = value

    @classmethod
    async def create(
        cls,
        *,
        private_key: str,
        wallet: str | None = None,
        environment: Environment = PRODUCTION,
        credentials: ApiKeyCreds | None = None,
        api_key: ApiKey | None = None,
        nonce: int = 0,
        logger: logging.Logger | None = None,
    ) -> Self:
        """Create an authenticated async client.

        Args:
            private_key: EVM private key used for signing.
            wallet: Wallet address to act for. Defaults to the signer's address.
            credentials: Existing API credentials. When omitted, credentials are
                derived during client creation.
            api_key: Optional key for gasless wallet and relayed transaction workflows.
            nonce: Credential derivation nonce. Cannot be combined with ``credentials``.

        Raises:
            UserInputError: If key material, wallet, nonce, or credentials are invalid.
            RequestRejectedError: If credential derivation or validation is rejected.
        """
        return await cls._create(
            private_key=private_key,
            wallet=wallet,
            environment=environment,
            credentials=credentials,
            api_key=api_key,
            nonce=nonce,
            validate_credentials=True,
            logger=logger,
        )

    @classmethod
    async def _create(
        cls,
        *,
        private_key: str,
        wallet: str | None = None,
        environment: Environment = PRODUCTION,
        credentials: ApiKeyCreds | None = None,
        api_key: ApiKey | None = None,
        nonce: int = 0,
        validate_credentials: bool = True,
        logger: logging.Logger | None = None,
    ) -> Self:
        if not private_key:
            raise UserInputError("private_key is required")
        _validate_nonce(nonce)
        if credentials is not None and nonce != 0:
            raise UserInputError("nonce cannot be combined with credentials.")
        try:
            signer = cast(LocalAccount, Account.from_key(private_key))
        except (ValueError, TypeError) as error:
            raise UserInputError(f"Invalid private_key: {error}") from error

        resolved_wallet = wallet if wallet else signer.address
        try:
            wallet_checksum = to_checksum_address(resolved_wallet)
        except ValueError as error:
            raise UserInputError(f"Invalid wallet address: {error}") from error

        bootstrap_clob = AsyncTransport(base_url=environment.clob_url, logger=logger)
        try:
            resolved_credentials = await _bootstrap_credentials(
                environment=environment,
                signer=signer,
                clob=bootstrap_clob,
                provided=credentials,
                nonce=nonce,
                validate=validate_credentials,
                logger=logger,
            )
        finally:
            await bootstrap_clob.close()

        return cls._construct_for_wallet(
            signer=signer,
            wallet=wallet_checksum,
            environment=environment,
            credentials=resolved_credentials,
            api_key=api_key,
            logger=logger,
        )

    @classmethod
    def _construct_for_wallet(
        cls,
        *,
        signer: LocalAccount,
        wallet: str,
        environment: Environment,
        credentials: ApiKeyCreds,
        api_key: ApiKey | None,
        logger: logging.Logger | None,
    ) -> Self:
        wallet_checksum = to_checksum_address(wallet)
        wallet_type = classify_wallet_type(
            signer=signer.address,
            wallet=wallet_checksum,
            config=environment.wallet_derivation,
        )
        branded_wallet = cast(EvmAddress, wallet_checksum)

        gamma = AsyncTransport(base_url=environment.gamma_url, logger=logger)
        data = AsyncTransport(base_url=environment.data_url, logger=logger)
        clob = AsyncTransport(base_url=environment.clob_url, logger=logger)
        relayer_resolver = make_relayer_header_resolver(api_key) if api_key is not None else None
        relayer = AsyncTransport(
            base_url=environment.relayer_url,
            logger=logger,
            header_resolver=relayer_resolver,
        )
        secure_clob = AsyncTransport(
            base_url=environment.clob_url,
            logger=logger,
            header_resolver=_make_l2_header_resolver(signer, credentials),
        )
        rpc_transport = AsyncTransport(base_url=environment.rpc_url, logger=logger)
        rpc = JsonRpcClient(rpc_transport)

        ctx = AsyncSecureClientContext(
            environment=environment,
            gamma=gamma,
            data=data,
            clob=clob,
            signer=signer,
            credentials=credentials,
            secure_clob=secure_clob,
            wallet=branded_wallet,
            wallet_type=wallet_type,
            relayer=relayer,
            api_key=api_key,
            rpc=rpc,
        )
        return cls(ctx=ctx, _create_token=_CREATE_TOKEN, logger=logger)

    @property
    def environment(self) -> Environment:
        """Environment this client sends requests to."""
        return self._ctx.environment

    @property
    def wallet(self) -> EvmAddress:
        """Wallet address authenticated by this client."""
        return self._ctx.wallet

    @property
    def signer(self) -> EvmAddress:
        """Signer address used for signatures."""
        return cast(EvmAddress, self._ctx.signer.address)

    @property
    def wallet_type(self) -> WalletType:
        """Detected wallet type for the authenticated wallet."""
        return self._ctx.wallet_type

    @property
    def credentials(self) -> ApiKeyCreds:
        """API credentials used for authenticated requests."""
        return self._ctx.credentials

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
    async def subscribe(self, specs: UserSpec, /) -> SubscriptionHandle[UserEvent]: ...
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
    async def subscribe(self, specs: Sequence[UserSpec], /) -> SubscriptionHandle[UserEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[SecureSubscription], /
    ) -> SubscriptionHandle[MarketEvent | SportsEvent | RtdsEvent | UserEvent]: ...
    async def subscribe(
        self,
        specs: SecureSubscription | Sequence[SecureSubscription],
    ) -> SubscriptionHandle[MarketEvent | SportsEvent | RtdsEvent | UserEvent]:
        """Subscribe to one or more public or authenticated realtime streams.

        Pass a single subscription spec for one stream or a sequence of specs to
        receive events through one merged handle. Authenticated user stream specs
        are supported only by secure clients.

        Returns:
            A subscription handle. Iterate over it to receive events and close it
            when finished.
        """
        items = _normalize_specs(specs)
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
                elif isinstance(spec, UserSpec):
                    handles.append(await self._get_user_manager().subscribe(markets=spec.markets))
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
                SubscriptionHandle[MarketEvent | SportsEvent | RtdsEvent | UserEvent],
                handles[0],
            )
        from polymarket._internal.streams.merged_handle import MergedSubscriptionHandle

        return cast(
            SubscriptionHandle[MarketEvent | SportsEvent | RtdsEvent | UserEvent],
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

    def _get_sports_manager(self) -> "SportsStreamManager":
        if self._sports_manager is None:
            from polymarket._internal.streams.sports.manager import SportsStreamManager

            self._sports_manager = SportsStreamManager(
                url=self._ctx.environment.sports_ws_url,
                logger=self._streams_logger,
            )
        return self._sports_manager

    def _get_rtds_manager(self) -> "RtdsStreamManager":
        if self._rtds_manager is None:
            from polymarket._internal.streams.rtds.manager import RtdsStreamManager

            self._rtds_manager = RtdsStreamManager(
                url=self._ctx.environment.rtds_ws_url,
                logger=self._streams_logger,
            )
        return self._rtds_manager

    def _get_user_manager(self) -> "ClobUserStreamManager":
        if self._user_manager is None:
            from polymarket._internal.streams.clob.user import ClobUserStreamManager

            self._user_manager = ClobUserStreamManager(
                url=self._ctx.environment.clob_user_ws_url,
                resolve_credentials=self._resolve_api_key_credentials,
                logger=self._streams_logger,
            )
        return self._user_manager

    async def _resolve_api_key_credentials(self) -> ApiKeyCreds:
        return self._ctx.credentials

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
        ctx = self._ctx_inner
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
                        if self._user_manager is not None:
                            await self._user_manager.close()
                    finally:
                        try:
                            await ctx.gamma.close()
                        finally:
                            try:
                                await ctx.data.close()
                            finally:
                                try:
                                    await ctx.clob.close()
                                finally:
                                    try:
                                        await ctx.secure_clob.close()
                                    finally:
                                        try:
                                            await ctx.relayer.close()
                                        finally:
                                            await ctx.rpc.close()

    def _user_or_wallet(self, user: str | None) -> str:
        return self._ctx.wallet if user is None else user

    async def get_market(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        url: str | None = None,
        include_tag: bool | None = None,
        locale: str | None = None,
    ) -> Market:
        """Get a market by id, slug, or Polymarket URL."""
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_market_spec(
                id=id, slug=slug, url=url, include_tag=include_tag, locale=locale
            ),
        )

    async def get_market_tags(self, id: str) -> tuple[TagReference, ...]:
        """Get a market's tags."""
        return await async_dispatch(self._ctx, _gamma_actions.get_market_tags_spec(id))

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
        include_chat: bool | None = None,
        locale: str | None = None,
    ) -> Series:
        """Get a series."""
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_series_spec(id, include_chat=include_chat, locale=locale),
        )

    async def get_tag(
        self,
        *,
        id: str | None = None,
        slug: str | None = None,
        include_chat: bool | None = None,
        include_template: bool | None = None,
        locale: str | None = None,
    ) -> Tag:
        """Get a tag by id or slug."""
        return await async_dispatch(
            self._ctx,
            _gamma_actions.get_tag_spec(
                id=id,
                slug=slug,
                include_chat=include_chat,
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
        self,
        *,
        user: str | None = None,
        market: Sequence[str] | None = None,
    ) -> tuple[PortfolioValue, ...]:
        """Get portfolio value snapshots for a user or the authenticated wallet."""
        return await async_dispatch(
            self._ctx,
            _data_actions.get_portfolio_values_spec(user=self._user_or_wallet(user), market=market),
        )

    async def get_traded_market_count(self, *, user: str | None = None) -> TradedMarketCount:
        """Get the number of markets traded by a user or the authenticated wallet."""
        return await async_dispatch(
            self._ctx,
            _data_actions.get_traded_market_count_spec(user=self._user_or_wallet(user)),
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
        user: str | None = None,
        market: Sequence[str] | None = None,
        event_id: Sequence[int] | None = None,
        size_threshold: float | None = None,
        redeemable: bool | None = None,
        mergeable: bool | None = None,
        sort_by: PositionSortBy | None = None,
        sort_direction: SortDirection | None = None,
        title: str | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Position]:
        """List open positions for a user or the authenticated wallet.

        Returns:
            An async paginator over matching positions.
        """
        spec = _data_actions.list_positions_spec(
            user=self._user_or_wallet(user),
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
        user: str | None = None,
        market: Sequence[str] | None = None,
        event_id: Sequence[int] | None = None,
        title: str | None = None,
        sort_by: ClosedPositionSortBy | None = None,
        sort_direction: SortDirection | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[ClosedPosition]:
        """List closed positions for a user or the authenticated wallet.

        Returns:
            An async paginator over matching closed positions.
        """
        spec = _data_actions.list_closed_positions_spec(
            user=self._user_or_wallet(user),
            market=market,
            event_id=event_id,
            title=title,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

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
        page_size: int = 20,
    ) -> AsyncPaginator[Trade]:
        """List trades for a user or the authenticated wallet.

        Returns:
            An async paginator over matching trades.
        """
        spec = _data_actions.list_trades_spec(
            user=self._user_or_wallet(user),
            market=market,
            event_id=event_id,
            side=side,
            taker_only=taker_only,
            filter_type=filter_type,
            filter_amount=filter_amount,
        )
        return async_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_activity(
        self,
        *,
        user: str | None = None,
        market: Sequence[str] | None = None,
        event_id: Sequence[int] | None = None,
        activity_types: Sequence[ActivityTypeFilter] | None = None,
        side: TradeSide | None = None,
        sort_by: ActivitySortBy | None = None,
        sort_direction: SortDirection | None = None,
        start: int | None = None,
        end: int | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator[Activity]:
        """List activity for a user or the authenticated wallet.

        Returns:
            An async paginator over matching activity entries.
        """
        spec = _data_actions.list_activity_spec(
            user=self._user_or_wallet(user),
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

    async def download_accounting_snapshot(self, *, user: str | None = None) -> bytes:
        """Download the accounting snapshot archive for a user or the authenticated wallet."""
        path, params = _data_actions.build_accounting_snapshot_request(
            user=self._user_or_wallet(user)
        )
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
        closed: bool | None = None,
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

        Returns:
            An async paginator over matching events.
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

        Returns:
            An async paginator over matching markets.
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

    def list_series(
        self,
        *,
        ascending: bool | None = None,
        categories_ids: int | Sequence[int] | None = None,
        categories_labels: str | Sequence[str] | None = None,
        closed: bool | None = None,
        exclude_events: bool | None = None,
        include_chat: bool | None = None,
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
            categories_ids=categories_ids,
            categories_labels=categories_labels,
            closed=closed,
            exclude_events=exclude_events,
            include_chat=include_chat,
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
        include_chat: bool | None = None,
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
            include_chat=include_chat,
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
        sort: str | None = None,
        page_size: int = 10,
    ) -> AsyncPaginator[SearchResults]:
        """Search Polymarket content.

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

    async def fetch_api_keys(self) -> tuple[str, ...]:
        """Fetch API key identifiers for the authenticated account."""
        return await _auth_actions.fetch_api_keys(self._ctx.secure_clob)

    async def create_builder_api_key(self) -> BuilderApiKey:
        """Create a builder API key for the authenticated account."""
        return await _auth_actions.create_builder_api_key(self._ctx.secure_clob)

    async def fetch_builder_api_keys(self) -> tuple[BuilderApiKeyInfo, ...]:
        """Fetch builder API key records for the authenticated account."""
        return await _auth_actions.fetch_builder_api_keys(self._ctx.secure_clob)

    async def revoke_builder_api_key(self) -> None:
        """Revoke a builder API key for the authenticated account."""
        await _auth_actions.revoke_builder_api_key(self._ctx.secure_clob)

    async def delete_api_key(self) -> None:
        """Delete the API key currently used by this client."""
        await _auth_actions.delete_api_key(self._ctx.secure_clob)

    async def end_authentication(self) -> "AsyncPublicClient":
        """Delete current credentials, close this client, and return an async public client."""
        environment = self._ctx.environment
        try:
            await self.delete_api_key()
        except RequestRejectedError as error:
            if error.status not in (401, 404):
                raise
        finally:
            await self.close()
            self._ended = True
        return AsyncPublicClient(environment=environment)

    async def get_closed_only_mode(self) -> bool:
        """Return whether the authenticated account is in closed-only mode."""
        path, params = _account_actions.build_closed_only_mode_request()
        return _account_actions.parse_closed_only_mode(
            await self._ctx.secure_clob.get_json(path, params=params)
        )

    def list_open_orders(
        self,
        *,
        token_id: str | None = None,
        id: str | None = None,
        market: str | None = None,
    ) -> AsyncPaginator[OpenOrder]:
        """List open orders for the authenticated account.

        Returns:
            An async paginator over matching open orders.
        """

        async def fetch(cursor: str | None) -> Page[OpenOrder]:
            path, params = _account_actions.build_list_open_orders_request(
                token_id=token_id, id=id, market=market, cursor=cursor
            )
            payload = await self._ctx.secure_clob.get_json(path, params=params)
            return _account_actions.parse_open_orders_page(payload)

        return AsyncPaginator(fetch=fetch)

    async def get_order(self, *, order_id: str) -> OpenOrder:
        """Get one open order for the authenticated account."""
        path, params = _account_actions.build_get_order_request(order_id=order_id)
        return _account_actions.parse_open_order(
            await self._ctx.secure_clob.get_json(path, params=params)
        )

    def list_account_trades(
        self,
        *,
        token_id: str | None = None,
        id: str | None = None,
        market: str | None = None,
        maker_address: str | None = None,
        after: str | None = None,
        before: str | None = None,
    ) -> AsyncPaginator[ClobTrade]:
        """List trades for the authenticated account.

        Returns:
            An async paginator over matching trades.
        """

        async def fetch(cursor: str | None) -> Page[ClobTrade]:
            path, params = _account_actions.build_list_account_trades_request(
                token_id=token_id,
                id=id,
                market=market,
                maker_address=maker_address,
                after=after,
                before=before,
                cursor=cursor,
            )
            payload = await self._ctx.secure_clob.get_json(path, params=params)
            return _account_actions.parse_account_trades_page(payload)

        return AsyncPaginator(fetch=fetch)

    async def get_notifications(self) -> tuple[Notification, ...]:
        """Get notifications for the authenticated account."""
        path, params = _account_actions.build_notifications_request(
            signature_type=signature_type_for(self._ctx.wallet_type)
        )
        return _account_actions.parse_notifications(
            await self._ctx.secure_clob.get_json(path, params=params)
        )

    async def drop_notifications(self, *, ids: Sequence[int | str]) -> None:
        """Delete notifications for the authenticated account."""
        path, params = _account_actions.build_drop_notifications_request(
            ids=ids, signature_type=signature_type_for(self._ctx.wallet_type)
        )
        await self._ctx.secure_clob.delete(path, params=params)

    async def get_balance_allowance(
        self, *, asset_type: AssetType, token_id: str | None = None
    ) -> BalanceAllowance:
        """Get balance and allowance information for an asset."""
        path, params = _account_actions.build_balance_allowance_request(
            asset_type=asset_type,
            token_id=token_id,
            signature_type=signature_type_for(self._ctx.wallet_type),
        )
        return _account_actions.parse_balance_allowance(
            await self._ctx.secure_clob.get_json(path, params=params)
        )

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

    async def create_limit_order(
        self,
        *,
        token_id: str,
        price: Decimal | int | float | str,
        size: Decimal | int | float | str,
        side: OrderSide,
        post_only: bool = False,
        expiration: int | None = None,
        builder_code: str | None = None,
    ) -> SignedOrder:
        """Create and sign a limit order without posting it.

        Use :meth:`post_order` to submit the returned signed order, or
        :meth:`place_limit_order` to create and post in one call.

        When ``expiration`` is provided, it must be a Unix timestamp at least
        60 seconds in the future. Use extra buffer for immediate submissions to
        account for latency and clock skew.
        """
        params = validate_limit_order_params(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            post_only=post_only,
            expiration=expiration,
            builder_code=builder_code,
        )
        draft = await prepare_limit_order_draft(self._ctx, params)
        return await self._sign_order(draft, post_only=params.post_only)

    @overload
    async def create_market_order(
        self,
        *,
        token_id: str,
        side: Literal["BUY"],
        amount: Decimal | int | float | str,
        max_spend: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder: ...
    @overload
    async def create_market_order(
        self,
        *,
        token_id: str,
        side: Literal["SELL"],
        shares: Decimal | int | float | str,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder: ...
    async def create_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | int | float | str | None = None,
        shares: Decimal | int | float | str | None = None,
        max_spend: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder:
        """Create and sign a market order without posting it.

        BUY orders use ``amount`` as the spend amount and may include
        ``max_spend``. SELL orders use ``shares`` as the number of shares to
        sell.
        """
        return await self._prepare_and_sign_market_order(
            token_id=token_id,
            side=side,
            amount=amount,
            shares=shares,
            max_spend=max_spend,
            order_type=order_type,
            builder_code=builder_code,
        )

    async def _prepare_and_sign_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | int | float | str | None = None,
        shares: Decimal | int | float | str | None = None,
        max_spend: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder:
        params = validate_market_order_params(
            token_id=token_id,
            side=side,
            amount=amount,
            shares=shares,
            max_spend=max_spend,
            order_type=order_type,
            builder_code=builder_code,
        )
        draft = await prepare_market_order_draft(self._ctx, params)
        return await self._sign_order(draft, post_only=False)

    async def place_limit_order(
        self,
        *,
        token_id: str,
        price: Decimal | int | float | str,
        size: Decimal | int | float | str,
        side: OrderSide,
        post_only: bool = False,
        expiration: int | None = None,
        builder_code: str | None = None,
    ) -> OrderResponse:
        """Create, sign, and post a limit order.

        When ``expiration`` is provided, it must be a Unix timestamp at least
        60 seconds in the future. Use extra buffer for immediate submissions to
        account for latency and clock skew.
        """
        signed = await self.create_limit_order(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            post_only=post_only,
            expiration=expiration,
            builder_code=builder_code,
        )
        return await post_order_with_allowance_recovery(self, signed)

    @overload
    async def place_market_order(
        self,
        *,
        token_id: str,
        side: Literal["BUY"],
        amount: Decimal | int | float | str,
        max_spend: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> OrderResponse: ...
    @overload
    async def place_market_order(
        self,
        *,
        token_id: str,
        side: Literal["SELL"],
        shares: Decimal | int | float | str,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> OrderResponse: ...
    async def place_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | int | float | str | None = None,
        shares: Decimal | int | float | str | None = None,
        max_spend: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> OrderResponse:
        """Create, sign, and post a market order.

        BUY orders use ``amount`` as the spend amount and may include
        ``max_spend``. SELL orders use ``shares`` as the number of shares to
        sell.
        """
        signed = await self._prepare_and_sign_market_order(
            token_id=token_id,
            side=side,
            amount=amount,
            shares=shares,
            max_spend=max_spend,
            order_type=order_type,
            builder_code=builder_code,
        )
        return await post_order_with_allowance_recovery(self, signed)

    async def get_builder_fee_rates(self, builder_code: str) -> BuilderFeeRates:
        """Get fee rates for a builder code."""
        from polymarket._internal.actions.orders.market_data import fetch_builder_fee_rates

        return await fetch_builder_fee_rates(self._ctx, builder_code=builder_code)

    async def approve_erc20(
        self,
        *,
        token_address: str,
        spender_address: str,
        amount: int | Literal["max"],
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Submit an ERC-20 approval transaction.

        Args:
            amount: Base-units amount to approve, or ``"max"`` for the maximum value.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
        """
        try:
            token = cast(EvmAddress, to_checksum_address(token_address))
        except ValueError as error:
            raise UserInputError(f"Invalid token_address: {error}") from error
        try:
            spender = cast(EvmAddress, to_checksum_address(spender_address))
        except ValueError as error:
            raise UserInputError(f"Invalid spender_address: {error}") from error
        resolved_amount = MAX_UINT256 if amount == "max" else amount
        call = erc20_approval_call(token_address=token, spender=spender, amount=resolved_amount)
        resolved_metadata = (
            metadata if metadata is not None else f"Approve {amount} of {token} to {spender}"
        )
        return await self._dispatch_single_call(call, metadata=resolved_metadata)

    async def approve_erc1155_for_all(
        self,
        *,
        token_address: str,
        operator_address: str,
        approved: bool = True,
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Approve or revoke an ERC-1155 operator for all tokens.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
        """
        try:
            token = cast(EvmAddress, to_checksum_address(token_address))
        except ValueError as error:
            raise UserInputError(f"Invalid token_address: {error}") from error
        try:
            operator = cast(EvmAddress, to_checksum_address(operator_address))
        except ValueError as error:
            raise UserInputError(f"Invalid operator_address: {error}") from error
        call = erc1155_set_approval_for_all_call(
            token_address=token, operator=operator, approved=approved
        )
        verb = "Approve" if approved else "Revoke"
        resolved_metadata = metadata if metadata is not None else f"{verb} {operator} on {token}"
        return await self._dispatch_single_call(call, metadata=resolved_metadata)

    async def transfer_erc20(
        self,
        *,
        token_address: str,
        recipient_address: str,
        amount: int,
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Submit an ERC-20 transfer transaction.

        Args:
            amount: Base-units amount to transfer.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
        """
        try:
            token = cast(EvmAddress, to_checksum_address(token_address))
        except ValueError as error:
            raise UserInputError(f"Invalid token_address: {error}") from error
        try:
            recipient = cast(EvmAddress, to_checksum_address(recipient_address))
        except ValueError as error:
            raise UserInputError(f"Invalid recipient_address: {error}") from error
        call = erc20_transfer_call(token_address=token, recipient=recipient, amount=amount)
        resolved_metadata = (
            metadata if metadata is not None else f"Transfer {amount} of {token} to {recipient}"
        )
        return await self._dispatch_single_call(call, metadata=resolved_metadata)

    async def setup_trading_approvals(self) -> TransactionHandle:
        """Approve the standard set of trading allowances for the wallet.

        EOA wallets submit approvals directly. Gasless wallets submit a relayed
        transaction. The returned handle represents the final transaction in the
        setup workflow.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
        """
        env = self._ctx.environment
        collateral = cast(EvmAddress, env.collateral_token)
        conditional = cast(EvmAddress, env.conditional_tokens)
        calls = [
            erc20_approval_call(
                token_address=collateral,
                spender=cast(EvmAddress, env.standard_exchange),
                amount=MAX_UINT256,
            ),
            erc20_approval_call(
                token_address=collateral,
                spender=cast(EvmAddress, env.neg_risk_exchange),
                amount=MAX_UINT256,
            ),
            erc20_approval_call(
                token_address=collateral,
                spender=cast(EvmAddress, env.neg_risk_adapter),
                amount=MAX_UINT256,
            ),
            erc20_approval_call(
                token_address=collateral,
                spender=cast(EvmAddress, env.collateral_adapter),
                amount=MAX_UINT256,
            ),
            erc20_approval_call(
                token_address=collateral,
                spender=cast(EvmAddress, env.neg_risk_collateral_adapter),
                amount=MAX_UINT256,
            ),
            erc1155_set_approval_for_all_call(
                token_address=conditional,
                operator=cast(EvmAddress, env.standard_exchange),
                approved=True,
            ),
            erc1155_set_approval_for_all_call(
                token_address=conditional,
                operator=cast(EvmAddress, env.neg_risk_exchange),
                approved=True,
            ),
            erc1155_set_approval_for_all_call(
                token_address=conditional,
                operator=cast(EvmAddress, env.neg_risk_adapter),
                approved=True,
            ),
            erc1155_set_approval_for_all_call(
                token_address=conditional,
                operator=cast(EvmAddress, env.collateral_adapter),
                approved=True,
            ),
            erc1155_set_approval_for_all_call(
                token_address=conditional,
                operator=cast(EvmAddress, env.neg_risk_collateral_adapter),
                approved=True,
            ),
            erc1155_set_approval_for_all_call(
                token_address=conditional,
                operator=cast(EvmAddress, env.auto_redeem_operator),
                approved=True,
            ),
        ]
        if self._ctx.wallet_type == "EOA":
            for call in calls[:-1]:
                handle = await self._broadcast_eoa_call(call)
                await handle.wait()
            return await self._broadcast_eoa_call(calls[-1])
        return await prepare_gasless_transaction(
            self._ctx, calls=calls, metadata="Trading setup approvals"
        )

    async def setup_gasless_wallet(self) -> Self:
        """Create or reuse the gasless wallet for the signer.

        Returns:
            A new async secure client scoped to the gasless wallet.

        Raises:
            UserInputError: If the client was not created with an API key that
                can authorize gasless wallet workflows.
        """
        ctx = self._ctx
        if ctx.api_key is None:
            raise UserInputError(
                "setup_gasless_wallet requires a Builder API Key or Relayer API Key. "
                "Pass api_key= when constructing the client."
            )
        if ctx.wallet_type != "EOA":
            return type(self)._construct_for_wallet(
                signer=ctx.signer,
                wallet=str(ctx.wallet),
                environment=ctx.environment,
                credentials=ctx.credentials,
                api_key=ctx.api_key,
                logger=self._streams_logger,
            )
        deposit_address = cast(
            EvmAddress,
            await derive_current_deposit_wallet_address(
                ctx.rpc, ctx.signer.address, ctx.environment.wallet_derivation
            ),
        )
        ready = await fetch_deployed(
            ctx.relayer,
            address=str(deposit_address),
            type=RelayerTransactionType.WALLET,
        )
        if not ready:
            handle = await submit_deposit_wallet_create(ctx, metadata="Deploy Deposit Wallet")
            await handle.wait()
        return type(self)._construct_for_wallet(
            signer=ctx.signer,
            wallet=str(deposit_address),
            environment=ctx.environment,
            credentials=ctx.credentials,
            api_key=ctx.api_key,
            logger=self._streams_logger,
        )

    async def is_gasless_ready(self) -> bool:
        """Return whether the signer has a deployed gasless wallet ready to use."""
        ctx = self._ctx
        if ctx.wallet_type != "EOA":
            type_param = (
                RelayerTransactionType.WALLET if ctx.wallet_type == "DEPOSIT_WALLET" else None
            )
            return await fetch_deployed(ctx.relayer, address=str(ctx.wallet), type=type_param)
        deposit_address = await derive_current_deposit_wallet_address(
            ctx.rpc, ctx.signer.address, ctx.environment.wallet_derivation
        )
        return await fetch_deployed(
            ctx.relayer, address=deposit_address, type=RelayerTransactionType.WALLET
        )

    async def _broadcast_eoa_call(self, call: TransactionCall) -> EoaTransactionHandle:
        env = self._ctx.environment
        return await broadcast_eoa_call(
            rpc=self._ctx.rpc,
            signer=self._ctx.signer,
            call=call,
            chain_id=env.chain_id,
            max_polls=env.relayer_max_polls,
            poll_delay_s=env.relayer_poll_frequency_ms / 1000,
        )

    async def _dispatch_single_call(
        self, call: TransactionCall, *, metadata: str
    ) -> TransactionHandle:
        if self._ctx.wallet_type == "EOA":
            return await self._broadcast_eoa_call(call)
        return await prepare_gasless_transaction(self._ctx, calls=[call], metadata=metadata)

    async def split_position(
        self,
        *,
        condition_id: str,
        amount: int,
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Split collateral into outcome positions for a condition.

        Args:
            amount: Base-units collateral amount to split.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
        """
        env = self._ctx.environment
        neg_risk = await self._resolve_market_neg_risk(condition_id)
        call = split_position_call(
            target=self._lifecycle_target_address(neg_risk),
            collateral=cast(EvmAddress, env.collateral_token),
            condition_id=condition_id,
            amount=amount,
        )
        resolved_metadata = (
            metadata
            if metadata is not None
            else f"Split {amount} positions for condition {condition_id}"
        )
        return await self._dispatch_single_call(call, metadata=resolved_metadata)

    async def merge_positions(
        self,
        *,
        condition_id: str,
        amount: int | Literal["max"],
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Merge outcome positions back into collateral.

        Args:
            amount: Base-units position amount to merge, or ``"max"`` to merge
                the largest available balanced amount.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
        """
        env = self._ctx.environment
        binary = await self._fetch_binary_positions(condition_id)
        neg_risk = expect_negative_risk_flag(binary)
        resolved_amount = resolve_merge_amount(binary, amount)
        call = merge_positions_call(
            target=self._lifecycle_target_address(neg_risk),
            collateral=cast(EvmAddress, env.collateral_token),
            condition_id=condition_id,
            amount=resolved_amount,
        )
        resolved_metadata = (
            metadata
            if metadata is not None
            else f"Merge {resolved_amount} positions for condition {condition_id}"
        )
        return await self._dispatch_single_call(call, metadata=resolved_metadata)

    async def redeem_positions(
        self,
        *,
        condition_id: str | None = None,
        market_id: str | None = None,
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Redeem resolved positions for a condition or market.

        Provide exactly one of ``condition_id`` or ``market_id``.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.

        Raises:
            UserInputError: If both identifiers or neither identifier is provided.
        """
        if (condition_id is None) == (market_id is None):
            raise UserInputError("Provide exactly one of condition_id or market_id")
        env = self._ctx.environment
        lookup_id = condition_id if condition_id is not None else market_id
        assert lookup_id is not None
        binary = await self._fetch_binary_positions(lookup_id)
        neg_risk = expect_negative_risk_flag(binary)
        resolved_condition_id = resolve_binary_positions_condition_id(binary)
        call = ctf_redeem_positions_call(
            ctf=self._lifecycle_target_address(neg_risk),
            collateral=cast(EvmAddress, env.collateral_token),
            condition_id=resolved_condition_id,
        )
        resolved_metadata = (
            metadata
            if metadata is not None
            else f"Redeem positions for condition {resolved_condition_id}"
        )
        return await self._dispatch_single_call(call, metadata=resolved_metadata)

    def _lifecycle_target_address(self, neg_risk: bool) -> EvmAddress:
        env = self._ctx.environment
        return cast(
            EvmAddress,
            env.neg_risk_collateral_adapter if neg_risk else env.collateral_adapter,
        )

    async def _resolve_market_neg_risk(self, condition_id: str) -> bool:
        page = await self.list_markets(condition_ids=[condition_id], page_size=2).first_page()
        markets = page.items
        if len(markets) != 1:
            raise UserInputError(
                f"Expected exactly one market for condition {condition_id}, got {len(markets)}"
            )
        market = markets[0]
        if market.state.neg_risk is None:
            raise UnexpectedResponseError(f"Missing negRisk flag for condition {condition_id}")
        return market.state.neg_risk

    async def _fetch_binary_positions(self, market_id_or_condition_id: str):  # type: ignore[no-untyped-def]
        page = await self.list_positions(
            user=str(self._ctx.wallet),
            market=[market_id_or_condition_id],
            size_threshold=0,
        ).first_page()
        return expect_binary_positions(page.items)

    async def post_order(self, signed_order: SignedOrder) -> OrderResponse:
        """Post a signed order for the authenticated account."""
        path, payload = _post_actions.build_post_order_request(
            signed_order, owner_api_key=self._ctx.credentials.key
        )
        return _post_actions.parse_order_response(
            await self._ctx.secure_clob.post_json(path, json=payload)
        )

    async def post_orders(self, signed_orders: Sequence[SignedOrder]) -> tuple[OrderResponse, ...]:
        """Post multiple signed orders for the authenticated account."""
        path, payload = _post_actions.build_post_orders_request(
            signed_orders, owner_api_key=self._ctx.credentials.key
        )
        return _post_actions.parse_order_responses(
            await self._ctx.secure_clob.post_json(path, json=payload)
        )

    async def cancel_order(self, *, order_id: str) -> CancelOrdersResponse:
        """Cancel one open order for the authenticated account."""
        path, body = _cancel_actions.build_cancel_order_request(order_id=order_id)
        return _cancel_actions.parse_cancel_orders_response(
            await self._ctx.secure_clob.delete_json(path, json=body)
        )

    async def cancel_orders(self, *, order_ids: Sequence[str]) -> CancelOrdersResponse:
        """Cancel multiple open orders for the authenticated account."""
        path, body = _cancel_actions.build_cancel_orders_request(order_ids=order_ids)
        return _cancel_actions.parse_cancel_orders_response(
            await self._ctx.secure_clob.delete_json(path, json=body)
        )

    async def cancel_all(self) -> CancelOrdersResponse:
        """Cancel all open orders for the authenticated account."""
        path, body = _cancel_actions.build_cancel_all_request()
        return _cancel_actions.parse_cancel_orders_response(
            await self._ctx.secure_clob.delete_json(path, json=body)
        )

    async def cancel_market_orders(
        self, *, market: str | None = None, token_id: str | None = None
    ) -> CancelOrdersResponse:
        """Cancel open orders matching a market or token filter."""
        path, body = _cancel_actions.build_cancel_market_orders_request(
            market=market, token_id=token_id
        )
        return _cancel_actions.parse_cancel_orders_response(
            await self._ctx.secure_clob.delete_json(path, json=body)
        )

    async def _sign_order(self, draft: OrderDraft, *, post_only: bool) -> SignedOrder:
        unsigned = create_unsigned_order(
            draft, wallet=self._ctx.wallet, wallet_type=self._ctx.wallet_type
        )
        typed_data = build_order_typed_data(unsigned)
        try:
            signed_message = self._ctx.signer.sign_typed_data(full_message=typed_data)
        except Exception as error:
            raise SigningError(f"Failed to sign order: {error}") from error
        raw_hex = signed_message.signature.hex()
        signature_hex = HexString(raw_hex if raw_hex.startswith("0x") else "0x" + raw_hex)
        final_signature = build_order_signature(unsigned, signature_hex)
        return create_signed_order(unsigned, final_signature, post_only=post_only)

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
                condition_id=ConditionId(condition_id), sponsored=sponsored, cursor=cursor
            )
            return _rewards_actions.parse_market_rewards_page(
                await self._ctx.clob.get_json(path, params=params)
            )

        return AsyncPaginator(fetch=fetch)

    async def get_order_scoring(self, *, order_id: str) -> bool:
        """Return whether an order is currently scoring rewards."""
        path, params = _rewards_actions.build_get_order_scoring_request(order_id=order_id)
        return _rewards_actions.parse_order_scoring(
            await self._ctx.secure_clob.get_json(path, params=params)
        )

    async def get_orders_scoring(self, *, order_ids: Sequence[str]) -> dict[str, bool]:
        """Return reward-scoring status for multiple orders."""
        path, body = _rewards_actions.build_get_orders_scoring_request(order_ids=order_ids)
        return _rewards_actions.parse_orders_scoring(
            await self._ctx.secure_clob.post_json(path, json=body)
        )

    def list_user_earnings_for_day(self, *, date: str) -> AsyncPaginator[UserEarning]:
        """List reward earnings for the authenticated user on a date.

        Returns:
            An async paginator over matching earning entries.
        """

        async def fetch(cursor: str | None) -> Page[UserEarning]:
            path, params = _rewards_actions.build_list_user_earnings_for_day_request(
                date=date,
                signature_type=signature_type_for(self._ctx.wallet_type),
                cursor=cursor,
            )
            return _rewards_actions.parse_user_earnings_page(
                await self._ctx.secure_clob.get_json(path, params=params)
            )

        return AsyncPaginator(fetch=fetch)

    async def get_total_earnings_for_user_for_day(
        self, *, date: str
    ) -> tuple[TotalUserEarning, ...]:
        """Get total reward earnings for the authenticated user on a date."""
        path, params = _rewards_actions.build_total_user_earnings_for_day_request(
            date=date, signature_type=signature_type_for(self._ctx.wallet_type)
        )
        return _rewards_actions.parse_total_user_earnings(
            await self._ctx.secure_clob.get_json(path, params=params)
        )

    def list_user_earnings_and_markets_config(
        self,
        *,
        date: str,
        no_competition: bool | None = None,
        order_by: str | None = None,
        position: str | None = None,
        page_size: int | None = None,
    ) -> AsyncPaginator[UserRewardsEarning]:
        """List reward earnings with market configuration for the authenticated user.

        Returns:
            An async paginator over matching reward earning entries.
        """

        async def fetch(cursor: str | None) -> Page[UserRewardsEarning]:
            path, params = _rewards_actions.build_list_user_earnings_and_markets_config_request(
                date=date,
                signature_type=signature_type_for(self._ctx.wallet_type),
                no_competition=no_competition,
                order_by=order_by,
                position=position,
                page_size=page_size,
                cursor=cursor,
            )
            return _rewards_actions.parse_user_rewards_earnings_page(
                await self._ctx.secure_clob.get_json(path, params=params)
            )

        return AsyncPaginator(fetch=fetch)

    async def get_reward_percentages(self) -> RewardsPercentages:
        """Get current reward percentage allocations for the authenticated account."""
        path, params = _rewards_actions.build_get_reward_percentages_request(
            signature_type=signature_type_for(self._ctx.wallet_type)
        )
        return _rewards_actions.parse_reward_percentages(
            await self._ctx.secure_clob.get_json(path, params=params)
        )


def _validate_nonce(nonce: object) -> None:
    if isinstance(nonce, bool) or not isinstance(nonce, int):
        raise UserInputError("nonce must be a non-negative integer.")
    if nonce < 0:
        raise UserInputError("nonce must be a non-negative integer.")


async def _bootstrap_credentials(
    *,
    environment: Environment,
    signer: LocalAccount,
    clob: AsyncTransport,
    provided: ApiKeyCreds | None,
    nonce: int,
    validate: bool,
    logger: logging.Logger | None,
) -> ApiKeyCreds:
    if provided is not None and (
        not validate
        or await _credentials_are_active(
            environment=environment,
            signer=signer,
            credentials=provided,
            logger=logger,
        )
    ):
        return provided

    signature = sign_api_key_auth(
        signer, chain_id=environment.chain_id, timestamp=int(time.time()), nonce=nonce
    )
    return await _auth_actions.create_or_derive_api_key(clob, signature)


async def _credentials_are_active(
    *,
    environment: Environment,
    signer: LocalAccount,
    credentials: ApiKeyCreds,
    logger: logging.Logger | None,
) -> bool:
    probe = AsyncTransport(
        base_url=environment.clob_url,
        logger=logger,
        header_resolver=_make_l2_header_resolver(signer, credentials),
    )
    try:
        keys = await _auth_actions.fetch_api_keys(probe)
    except RequestRejectedError as error:
        if error.status == 401:
            return False
        raise
    finally:
        await probe.close()
    return credentials.key in keys


def _make_l2_header_resolver(signer: LocalAccount, credentials: ApiKeyCreds) -> _L2HeaderResolver:
    async def resolver(method: str, path: str, body: str | None) -> Mapping[str, str]:
        timestamp = int(time.time())
        signature = build_hmac_signature(
            secret=credentials.secret,
            timestamp=timestamp,
            method=method,
            path=path,
            body=body,
        )
        return {
            "POLY_ADDRESS": signer.address,
            "POLY_API_KEY": credentials.key,
            "POLY_PASSPHRASE": credentials.passphrase,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": str(timestamp),
        }

    return resolver
