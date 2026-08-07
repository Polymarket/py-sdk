"""Synchronous secure Polymarket client."""

import logging
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Self, cast, overload

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils.address import to_checksum_address

from polymarket._internal.actions import account as _account_actions
from polymarket._internal.actions import auth as _auth_actions
from polymarket._internal.actions import builders as _builders_actions
from polymarket._internal.actions import clob as _clob_actions
from polymarket._internal.actions import combos as _combos_actions
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
from polymarket._internal.actions.orders import cancel as _cancel_actions
from polymarket._internal.actions.orders import post as _post_actions
from polymarket._internal.actions.orders import settlement as _settlement_actions
from polymarket._internal.actions.orders.cache import SyncOrderMetadataCache
from polymarket._internal.actions.orders.estimate import (
    estimate_market_price_sync as _estimate_market_price_sync,
)
from polymarket._internal.actions.orders.limit import (
    prepare_limit_order_draft_sync,
    validate_limit_order_params,
)
from polymarket._internal.actions.orders.market import (
    prepare_market_order_draft_sync,
    validate_market_order_params,
)
from polymarket._internal.actions.orders.orders import (
    create_signed_order,
    create_unsigned_order,
)
from polymarket._internal.actions.orders.place import (
    post_order_with_allowance_recovery_sync,
)
from polymarket._internal.actions.orders.settlement import DEFAULT_SETTLEMENT_TIMEOUT_S
from polymarket._internal.actions.orders.typed_data import (
    build_order_signature,
    build_order_typed_data,
)
from polymarket._internal.actions.orders.types import OrderDraft
from polymarket._internal.actions.relayer.approvals import (
    resolve_missing_trading_approval_calls_sync,
)
from polymarket._internal.actions.relayer.auth import make_relayer_header_resolver_sync
from polymarket._internal.actions.relayer.calls import (
    MAX_UINT256,
    TransactionCall,
    combinatorial_prepare_condition_call,
    ctf_redeem_positions_call,
    decode_erc1155_balance_of_batch_result,
    decode_erc1155_balance_of_result,
    erc20_approval_call,
    erc20_transfer_call,
    erc1155_balance_of_batch_call,
    erc1155_balance_of_call,
    erc1155_set_approval_for_all_call,
    merge_positions_call,
    merge_v2_call,
    redeem_v2_call,
    split_position_call,
    split_v2_call,
)
from polymarket._internal.actions.relayer.deployed import fetch_deployed_sync
from polymarket._internal.actions.relayer.gasless import (
    prepare_gasless_transaction_sync,
    submit_deposit_wallet_create_sync,
)
from polymarket._internal.actions.relayer.positions import (
    MarketPositionContext,
    canonicalize_combo_legs,
    decode_combo_outcome_position_id,
    derive_combo_outcome_position_ids,
    derive_combo_position_context,
    normalize_batch_merge_position_request,
    normalize_market_position_context,
    parse_market_id,
    resolve_merge_amount_from_balances,
)
from polymarket._internal.context import SyncSecureClientContext
from polymarket._internal.dispatch import (
    sync_dispatch,
    sync_paginate_keyset,
    sync_paginate_offset,
    sync_paginate_page_based,
)
from polymarket._internal.environment import EnvironmentConfig, get_environment_config
from polymarket._internal.eoa.broadcast import broadcast_eoa_call_sync
from polymarket._internal.eoa.rpc import SyncJsonRpcClient
from polymarket._internal.hmac import build_hmac_signature
from polymarket._internal.l1_auth import sign_api_key_auth
from polymarket._internal.wallet import (
    WalletType,
    classify_wallet_type,
    derive_beacon_deposit_wallet_address,
    derive_uups_deposit_wallet_address,
    signature_type_for,
)
from polymarket.auth import ApiKey, BuilderApiKey
from polymarket.clients._transport import SyncHeaderResolver, SyncTransport
from polymarket.environments import PRODUCTION, Environment
from polymarket.errors import (
    RequestRejectedError,
    SigningError,
    UserInputError,
)
from polymarket.models import (
    ApiKeyCreds,
    AssetType,
    BalanceAllowance,
    BuilderFeeRates,
    ClobTrade,
    ComboMarket,
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
from polymarket.models.clob import BuilderApiKeyInfo, BuilderTrade
from polymarket.models.clob.cancel import CancelOrdersResponse
from polymarket.models.clob.order_response import AcceptedOrder, OrderResponse
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
from polymarket.models.collateral_return import CollateralReturnPlanResponse
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
from polymarket.transactions import (
    MergePositionRequest,
    SyncDeprecatedTransactionHandle,
    SyncEoaTransactionHandle,
    SyncGaslessTransactionHandle,
    SyncTransactionHandle,
)
from polymarket.types import EvmAddress, HexString, TransactionHash

if TYPE_CHECKING:
    from polymarket.clients.public import PublicClient

_CREATE_TOKEN = object()


def _validate_nonce(nonce: object) -> None:
    if isinstance(nonce, bool) or not isinstance(nonce, int):
        raise UserInputError("nonce must be a non-negative integer.")
    if nonce < 0:
        raise UserInputError("nonce must be a non-negative integer.")


class SecureClient:
    """Synchronous client for authenticated account, trading, and wallet workflows.

    Create instances with :meth:`SecureClient.create` so the SDK can derive or
    validate credentials before authenticated requests are made.
    """

    def __init__(
        self,
        *,
        ctx: SyncSecureClientContext,
        _create_token: object | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if _create_token is not _CREATE_TOKEN:
            raise RuntimeError("Use SecureClient.create(...) to create a secure client")
        self._ended = False
        self._ctx_inner = ctx

    @property
    def _ctx(self) -> SyncSecureClientContext:
        if self._ended:
            raise RuntimeError(
                "SecureClient has ended authentication; use the returned PublicClient "
                "or create a new SecureClient."
            )
        return self._ctx_inner

    @_ctx.setter
    def _ctx(self, value: SyncSecureClientContext) -> None:
        self._ctx_inner = value

    @classmethod
    def create(
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
        """Create an authenticated synchronous client.

        Args:
            private_key: EVM private key used for signing.
            wallet: Wallet address to act for. Defaults to the signer's Deposit Wallet.
            credentials: Existing API credentials. When omitted, credentials are
                derived during client creation.
            api_key: Optional key for gasless wallet and relayed transaction workflows.
            nonce: Credential derivation nonce. Cannot be combined with ``credentials``.

        Raises:
            UserInputError: If key material, wallet, nonce, or credentials are invalid.
            RequestRejectedError: If credential derivation or validation is rejected.
        """
        client = cls._create(
            private_key=private_key,
            wallet=wallet,
            environment=environment,
            credentials=credentials,
            api_key=api_key,
            nonce=nonce,
            validate_credentials=True,
            logger=logger,
        )
        try:
            return client._ensure_wallet_ready()
        except BaseException:
            client.close()
            raise

    @classmethod
    def _create(
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
        config = get_environment_config(environment)
        try:
            signer = cast(LocalAccount, Account.from_key(private_key))
        except (ValueError, TypeError) as error:
            raise UserInputError(f"Invalid private_key: {error}") from error

        resolved_wallet = _resolve_requested_wallet_sync(
            signer=signer,
            wallet=wallet,
            config=config,
            logger=logger,
        )

        bootstrap_clob = SyncTransport(base_url=config.clob_url, logger=logger)
        try:
            resolved_credentials = _bootstrap_credentials_sync(
                config=config,
                signer=signer,
                clob=bootstrap_clob,
                provided=credentials,
                nonce=nonce,
                validate=validate_credentials,
                logger=logger,
            )
        finally:
            bootstrap_clob.close()

        return cls._construct_for_wallet(
            signer=signer,
            wallet=resolved_wallet,
            environment=environment,
            config=config,
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
        config: EnvironmentConfig,
        credentials: ApiKeyCreds,
        api_key: ApiKey | None,
        logger: logging.Logger | None,
    ) -> Self:
        try:
            wallet_checksum = to_checksum_address(wallet)
        except ValueError as error:
            raise UserInputError(f"Invalid wallet address: {error}") from error
        wallet_type = classify_wallet_type(
            signer=signer.address,
            wallet=wallet_checksum,
            config=config.wallet_derivation,
        )
        branded_wallet = cast(EvmAddress, wallet_checksum)

        gamma = SyncTransport(base_url=config.gamma_url, logger=logger)
        data = SyncTransport(base_url=config.data_url, logger=logger)
        rfq = SyncTransport(base_url=config.rfq_url, logger=logger)
        clob = SyncTransport(base_url=config.clob_url, logger=logger)
        relayer_resolver = (
            make_relayer_header_resolver_sync(api_key) if api_key is not None else None
        )
        relayer = SyncTransport(
            base_url=config.relayer_url,
            logger=logger,
            header_resolver=relayer_resolver,
        )
        combos = SyncTransport(
            base_url=config.collateral_return_url,
            logger=logger,
            header_resolver=relayer_resolver,
        )
        try:
            secure_clob = SyncTransport(
                base_url=config.clob_url,
                logger=logger,
                header_resolver=_make_l2_header_resolver_sync(signer, credentials),
            )
            rpc_transport = SyncTransport(base_url=config.rpc_url, logger=logger)
            rpc = SyncJsonRpcClient(rpc_transport)
        except BaseException:
            gamma.close()
            data.close()
            rfq.close()
            clob.close()
            relayer.close()
            combos.close()
            raise

        ctx = SyncSecureClientContext(
            environment=environment,
            _resolved_environment_config=config,
            gamma=gamma,
            data=data,
            rfq=rfq,
            clob=clob,
            signer=signer,
            credentials=credentials,
            secure_clob=secure_clob,
            wallet=branded_wallet,
            wallet_type=wallet_type,
            relayer=relayer,
            combos=combos,
            api_key=api_key,
            rpc=rpc,
            order_metadata=SyncOrderMetadataCache(),
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
        ctx = self._ctx_inner
        try:
            ctx.gamma.close()
        finally:
            try:
                ctx.data.close()
            finally:
                try:
                    ctx.clob.close()
                finally:
                    try:
                        ctx.rfq.close()
                    finally:
                        try:
                            ctx.secure_clob.close()
                        finally:
                            try:
                                ctx.relayer.close()
                            finally:
                                try:
                                    ctx.combos.close()
                                finally:
                                    ctx.rpc.close()

    def _user_or_wallet(self, user: str | None) -> str:
        return self._ctx.wallet if user is None else user

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
        """Get a market by id, slug, or Polymarket URL.

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
        """Get an event by id, slug, or Polymarket URL."""
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
        """Get a tag by id or slug."""
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
        self,
        *,
        user: str | None = None,
        market: Sequence[str] | None = None,
    ) -> tuple[PortfolioValue, ...]:
        """Get portfolio value snapshots for a user or the authenticated wallet."""
        return sync_dispatch(
            self._ctx,
            _data_actions.get_portfolio_values_spec(user=self._user_or_wallet(user), market=market),
        )

    def get_traded_market_count(self, *, user: str | None = None) -> TradedMarketCount:
        """Get the number of markets traded by a user or the authenticated wallet."""
        return sync_dispatch(
            self._ctx,
            _data_actions.get_traded_market_count_spec(user=self._user_or_wallet(user)),
        )

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
            A paginator over matching builder-attributed trades.
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
    ) -> Paginator[Position]:
        """List open positions for a user or the authenticated wallet.

        Returns:
            A paginator over matching positions.
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
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

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
    ) -> Paginator[ClosedPosition]:
        """List closed positions for a user or the authenticated wallet.

        Returns:
            A paginator over matching closed positions.
        """
        spec = _data_actions.list_closed_positions_spec(
            user=self._user_or_wallet(user),
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
        user: str | None = None,
        status: ComboPositionStatus | None = None,
        sort: ComboPositionSort | None = None,
        condition_id: str | Sequence[str] | None = None,
        updated_after: int | None = None,
        updated_before: int | None = None,
        page_size: int = 20,
    ) -> Paginator[ComboPosition]:
        """List combo positions for a user or the authenticated wallet.

        Returns:
            A paginator over matching combo positions.
        """
        spec = _data_actions.list_combo_positions_spec(
            user=self._user_or_wallet(user),
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
        """List trades for a user or the authenticated wallet.

        Returns:
            A paginator over matching trades.
        """
        spec = _data_actions.list_trades_spec(
            user=self._user_or_wallet(user),
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
    ) -> Paginator[Activity]:
        """List activity for a user or the authenticated wallet.

        Returns:
            A paginator over matching activity entries.
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
        return sync_paginate_offset(self._ctx, spec, page_size=page_size)

    def list_combo_activity(
        self,
        *,
        user: str | None = None,
        condition_id: str | Sequence[str] | None = None,
        page_size: int = 50,
    ) -> Paginator[ComboActivity]:
        """List combo lifecycle activity for a user or the authenticated wallet.

        Returns:
            A paginator over matching combo lifecycle activity entries.
        """
        spec = _data_actions.list_combo_activity_spec(
            user=self._user_or_wallet(user), condition_id=condition_id
        )
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

    def download_accounting_snapshot(self, *, user: str | None = None) -> bytes:
        """Download the accounting snapshot archive for a user or the authenticated wallet."""
        path, params = _data_actions.build_accounting_snapshot_request(
            user=self._user_or_wallet(user)
        )
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

    def get_last_trade_price(self, *, token_id: str) -> LastTradePrice:
        """Get the most recent trade price for a token."""
        path, params = _clob_actions.build_last_trade_price_request(token_id=token_id)
        return _clob_actions.parse_last_trade_price(self._ctx.clob.get_json(path, params=params))

    def get_last_trade_prices(
        self, *, token_ids: Sequence[str]
    ) -> tuple[LastTradePriceForToken, ...]:
        """Get the most recent trade prices for multiple tokens."""
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

    def fetch_api_keys(self) -> tuple[str, ...]:
        """Fetch API key identifiers for the authenticated account."""
        return _auth_actions.fetch_api_keys_sync(self._ctx.secure_clob)

    def delete_api_key(self) -> None:
        """Delete the API key currently used by this client."""
        _auth_actions.delete_api_key_sync(self._ctx.secure_clob)

    def create_builder_api_key(self) -> BuilderApiKey:
        """Create a new builder API key for the authenticated account."""
        return _auth_actions.create_builder_api_key_sync(self._ctx.secure_clob)

    def fetch_builder_api_keys(self) -> tuple[BuilderApiKeyInfo, ...]:
        """List the builder API keys for the authenticated account."""
        return _auth_actions.fetch_builder_api_keys_sync(self._ctx.secure_clob)

    def revoke_builder_api_key(self) -> None:
        """Revoke the builder API key this client is configured with.

        The revocation is authenticated by the builder key itself, so the client must have been
        created with the key to revoke (``SecureClient.create(api_key=BuilderApiKey(...))``).
        """
        builder_key = self._ctx.api_key
        if not isinstance(builder_key, BuilderApiKey):
            raise UserInputError(
                "revoke_builder_api_key requires a client created with the builder key to "
                "revoke (pass api_key=BuilderApiKey(...) to SecureClient.create)."
            )
        _auth_actions.revoke_builder_api_key_sync(self._ctx.clob, builder_key)

    def end_authentication(self) -> "PublicClient":
        """Delete current credentials, close this client, and return a public client."""
        from polymarket.clients.public import PublicClient

        environment = self._ctx.environment
        try:
            self.delete_api_key()
        except RequestRejectedError as error:
            if error.status not in (401, 404):
                raise
        finally:
            self.close()
            self._ended = True
        return PublicClient(environment=environment)

    def get_closed_only_mode(self) -> bool:
        """Return whether the authenticated account is in closed-only mode."""
        path, params = _account_actions.build_closed_only_mode_request()
        return _account_actions.parse_closed_only_mode(
            self._ctx.secure_clob.get_json(path, params=params)
        )

    def list_open_orders(
        self,
        *,
        token_id: str | None = None,
        id: str | None = None,
        market: str | None = None,
    ) -> Paginator[OpenOrder]:
        """List open orders for the authenticated account.

        Returns:
            A paginator over matching open orders.
        """

        def fetch(cursor: str | None) -> Page[OpenOrder]:
            path, params = _account_actions.build_list_open_orders_request(
                token_id=token_id, id=id, market=market, cursor=cursor
            )
            payload = self._ctx.secure_clob.get_json(path, params=params)
            return _account_actions.parse_open_orders_page(payload)

        return Paginator(fetch=fetch)

    def get_order(self, *, order_id: str) -> OpenOrder:
        """Get one open order for the authenticated account."""
        path, params = _account_actions.build_get_order_request(order_id=order_id)
        return _account_actions.parse_open_order(
            self._ctx.secure_clob.get_json(path, params=params)
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
    ) -> Paginator[ClobTrade]:
        """List trades for the authenticated account.

        Returns:
            A paginator over matching trades.
        """

        def fetch(cursor: str | None) -> Page[ClobTrade]:
            path, params = _account_actions.build_list_account_trades_request(
                token_id=token_id,
                id=id,
                market=market,
                maker_address=maker_address,
                after=after,
                before=before,
                cursor=cursor,
            )
            payload = self._ctx.secure_clob.get_json(path, params=params)
            return _account_actions.parse_account_trades_page(payload)

        return Paginator(fetch=fetch)

    def get_notifications(self) -> tuple[Notification, ...]:
        """Get notifications for the authenticated account."""
        path, params = _account_actions.build_notifications_request(
            signature_type=signature_type_for(self._ctx.wallet_type)
        )
        return _account_actions.parse_notifications(
            self._ctx.secure_clob.get_json(path, params=params)
        )

    def drop_notifications(self, *, ids: Sequence[int | str]) -> None:
        """Delete notifications for the authenticated account."""
        path, params = _account_actions.build_drop_notifications_request(
            ids=ids, signature_type=signature_type_for(self._ctx.wallet_type)
        )
        self._ctx.secure_clob.delete(path, params=params)

    def get_balance_allowance(
        self, *, asset_type: AssetType, token_id: str | None = None
    ) -> BalanceAllowance:
        """Get balance and allowance information for an asset."""
        path, params = _account_actions.build_balance_allowance_request(
            asset_type=asset_type,
            token_id=token_id,
            signature_type=signature_type_for(self._ctx.wallet_type),
        )
        return _account_actions.parse_balance_allowance(
            self._ctx.secure_clob.get_json(path, params=params)
        )

    def create_limit_order(
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
        3 minutes in the future. Use extra buffer for immediate submissions to
        account for latency and clock skew.

        Raises:
            UserInputError: If order parameters are invalid.
            SigningError: If the order cannot be signed.
        """
        return self._prepare_and_sign_limit_order(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            post_only=post_only,
            expiration=expiration,
            builder_code=builder_code,
        )

    @overload
    def create_market_order(
        self,
        *,
        token_id: str,
        side: Literal["BUY"],
        amount: Decimal | int | float | str,
        max_spend: Decimal | int | float | str | None = None,
        max_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder: ...
    @overload
    def create_market_order(
        self,
        *,
        token_id: str,
        side: Literal["SELL"],
        shares: Decimal | int | float | str,
        min_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder: ...
    def create_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | int | float | str | None = None,
        shares: Decimal | int | float | str | None = None,
        max_spend: Decimal | int | float | str | None = None,
        max_price: Decimal | int | float | str | None = None,
        min_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder:
        """Create and sign a market order without posting it.

        BUY orders use ``amount`` as the spend amount and may include
        ``max_spend`` and ``max_price``. SELL orders use ``shares`` as the
        number of shares to sell and may include ``min_price``.

        ``max_spend`` is an estimated all-in spend target based on recently
        resolved platform and builder fee rates. Actual fees may change before
        execution.

        Raises:
            UserInputError: If side-specific order parameters are invalid.
            InsufficientLiquidityError: If available liquidity cannot fill the order.
            SigningError: If the order cannot be signed.
        """
        return self._prepare_and_sign_market_order(
            token_id=token_id,
            side=side,
            amount=amount,
            shares=shares,
            max_spend=max_spend,
            max_price=max_price,
            min_price=min_price,
            order_type=order_type,
            builder_code=builder_code,
        )

    def place_limit_order(
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
        3 minutes in the future. Use extra buffer for immediate submissions to
        account for latency and clock skew.

        Raises:
            UserInputError: If order parameters are invalid.
            InsufficientAllowanceError: If required allowance cannot be recovered.
            SigningError: If the order cannot be signed.
            RequestRejectedError: If posting the order is rejected.
        """
        signed = self._prepare_and_sign_limit_order(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            post_only=post_only,
            expiration=expiration,
            builder_code=builder_code,
        )
        return post_order_with_allowance_recovery_sync(self, signed)

    @overload
    def place_market_order(
        self,
        *,
        token_id: str,
        side: Literal["BUY"],
        amount: Decimal | int | float | str,
        max_spend: Decimal | int | float | str | None = None,
        max_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> OrderResponse: ...
    @overload
    def place_market_order(
        self,
        *,
        token_id: str,
        side: Literal["SELL"],
        shares: Decimal | int | float | str,
        min_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> OrderResponse: ...
    def place_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | int | float | str | None = None,
        shares: Decimal | int | float | str | None = None,
        max_spend: Decimal | int | float | str | None = None,
        max_price: Decimal | int | float | str | None = None,
        min_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> OrderResponse:
        """Create, sign, and post a market order.

        BUY orders use ``amount`` as the spend amount and may include
        ``max_spend`` and ``max_price``. SELL orders use ``shares`` as the
        number of shares to sell and may include ``min_price``.

        ``max_spend`` is an estimated all-in spend target based on recently
        resolved platform and builder fee rates. Actual fees may change before
        execution.

        Raises:
            UserInputError: If side-specific order parameters are invalid.
            InsufficientLiquidityError: If available liquidity cannot fill the order.
            InsufficientAllowanceError: If required allowance cannot be recovered.
            SigningError: If the order cannot be signed.
            RequestRejectedError: If posting the order is rejected.
        """
        signed = self._prepare_and_sign_market_order(
            token_id=token_id,
            side=side,
            amount=amount,
            shares=shares,
            max_spend=max_spend,
            max_price=max_price,
            min_price=min_price,
            order_type=order_type,
            builder_code=builder_code,
        )
        return post_order_with_allowance_recovery_sync(self, signed)

    def get_builder_fee_rates(self, builder_code: str) -> BuilderFeeRates:
        """Get fee rates for a builder code."""
        from polymarket._internal.actions.orders.market_data import fetch_builder_fee_rates_sync

        return fetch_builder_fee_rates_sync(self._ctx, builder_code=builder_code)

    def post_order(self, signed_order: SignedOrder) -> OrderResponse:
        """Post a signed order for the authenticated account."""
        path, payload = _post_actions.build_post_order_request(
            signed_order, owner_api_key=self._ctx.credentials.key
        )
        return _post_actions.parse_order_response(
            self._ctx.secure_clob.post_json(path, json=payload)
        )

    def post_orders(self, signed_orders: Sequence[SignedOrder]) -> tuple[OrderResponse, ...]:
        """Post multiple signed orders for the authenticated account."""
        path, payload = _post_actions.build_post_orders_request(
            signed_orders, owner_api_key=self._ctx.credentials.key
        )
        return _post_actions.parse_order_responses(
            self._ctx.secure_clob.post_json(path, json=payload)
        )

    def wait_for_order_fill_settlement(
        self,
        order: AcceptedOrder,
        *,
        timeout_s: float = DEFAULT_SETTLEMENT_TIMEOUT_S,
    ) -> tuple[TransactionHash, ...]:
        """Wait until every fill listed in an order response settles.

        Settlement covers the fills listed in this order response, identified
        by the order's ``trade_ids``. These are the fills that happened
        immediately when the order was accepted. This method does not wait for
        later fills of any remaining quantity resting on the book. Fills that
        fail execution contribute no hash.

        Returns:
            The settlement transaction hashes of the order's fills.

        Raises:
            TimeoutError: If fills are still settling when the timeout elapses.
                The order placement itself is unaffected.
            TransactionFailedError: If every fill failed execution.
        """
        return _settlement_actions.wait_for_order_fill_settlement_sync(
            self._ctx.secure_clob, order, timeout_s=timeout_s
        )

    def cancel_order(self, *, order_id: str) -> CancelOrdersResponse:
        """Cancel one open order for the authenticated account."""
        path, body = _cancel_actions.build_cancel_order_request(order_id=order_id)
        return _cancel_actions.parse_cancel_orders_response(
            self._ctx.secure_clob.delete_json(path, json=body)
        )

    def cancel_orders(self, *, order_ids: Sequence[str]) -> CancelOrdersResponse:
        """Cancel multiple open orders for the authenticated account."""
        path, body = _cancel_actions.build_cancel_orders_request(order_ids=order_ids)
        return _cancel_actions.parse_cancel_orders_response(
            self._ctx.secure_clob.delete_json(path, json=body)
        )

    def cancel_all(self) -> CancelOrdersResponse:
        """Cancel all open orders for the authenticated account."""
        path, body = _cancel_actions.build_cancel_all_request()
        return _cancel_actions.parse_cancel_orders_response(
            self._ctx.secure_clob.delete_json(path, json=body)
        )

    def cancel_market_orders(
        self, *, market: str | None = None, token_id: str | None = None
    ) -> CancelOrdersResponse:
        """Cancel open orders matching a market or token filter."""
        path, body = _cancel_actions.build_cancel_market_orders_request(
            market=market, token_id=token_id
        )
        return _cancel_actions.parse_cancel_orders_response(
            self._ctx.secure_clob.delete_json(path, json=body)
        )

    def _prepare_and_sign_limit_order(
        self,
        *,
        token_id: str,
        price: Decimal | int | float | str,
        size: Decimal | int | float | str,
        side: OrderSide,
        post_only: bool,
        expiration: int | None,
        builder_code: str | None,
    ) -> SignedOrder:
        params = validate_limit_order_params(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            post_only=post_only,
            expiration=expiration,
            builder_code=builder_code,
        )
        draft = prepare_limit_order_draft_sync(self._ctx, params)
        return self._sign_order(draft, post_only=params.post_only)

    def _prepare_and_sign_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | int | float | str | None,
        shares: Decimal | int | float | str | None,
        max_spend: Decimal | int | float | str | None,
        max_price: Decimal | int | float | str | None,
        min_price: Decimal | int | float | str | None,
        order_type: MarketOrderType,
        builder_code: str | None,
    ) -> SignedOrder:
        params = validate_market_order_params(
            token_id=token_id,
            side=side,
            amount=amount,
            shares=shares,
            max_spend=max_spend,
            max_price=max_price,
            min_price=min_price,
            order_type=order_type,
            builder_code=builder_code,
        )
        draft = prepare_market_order_draft_sync(self._ctx, params)
        return self._sign_order(draft, post_only=False)

    def _sign_order(self, draft: OrderDraft, *, post_only: bool) -> SignedOrder:
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

    def get_order_scoring(self, *, order_id: str) -> bool:
        """Return whether an order is currently scoring rewards."""
        path, params = _rewards_actions.build_get_order_scoring_request(order_id=order_id)
        return _rewards_actions.parse_order_scoring(
            self._ctx.secure_clob.get_json(path, params=params)
        )

    def get_orders_scoring(self, *, order_ids: Sequence[str]) -> dict[str, bool]:
        """Return reward-scoring status for multiple orders."""
        path, body = _rewards_actions.build_get_orders_scoring_request(order_ids=order_ids)
        return _rewards_actions.parse_orders_scoring(
            self._ctx.secure_clob.post_json(path, json=body)
        )

    def list_user_earnings_for_day(self, *, date: str) -> Paginator[UserEarning]:
        """List reward earnings for the authenticated user on a date.

        Returns:
            A paginator over matching earning entries.
        """

        def fetch(cursor: str | None) -> Page[UserEarning]:
            path, params = _rewards_actions.build_list_user_earnings_for_day_request(
                date=date,
                signature_type=signature_type_for(self._ctx.wallet_type),
                cursor=cursor,
            )
            return _rewards_actions.parse_user_earnings_page(
                self._ctx.secure_clob.get_json(path, params=params)
            )

        return Paginator(fetch=fetch)

    def get_total_earnings_for_user_for_day(self, *, date: str) -> tuple[TotalUserEarning, ...]:
        """Get total reward earnings for the authenticated user on a date."""
        path, params = _rewards_actions.build_total_user_earnings_for_day_request(
            date=date, signature_type=signature_type_for(self._ctx.wallet_type)
        )
        return _rewards_actions.parse_total_user_earnings(
            self._ctx.secure_clob.get_json(path, params=params)
        )

    def list_user_earnings_and_markets_config(
        self,
        *,
        date: str,
        no_competition: bool | None = None,
        order_by: str | None = None,
        position: str | None = None,
        page_size: int | None = None,
    ) -> Paginator[UserRewardsEarning]:
        """List reward earnings with market configuration for the authenticated user.

        Returns:
            A paginator over matching reward earning entries.
        """

        def fetch(cursor: str | None) -> Page[UserRewardsEarning]:
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
                self._ctx.secure_clob.get_json(path, params=params)
            )

        return Paginator(fetch=fetch)

    def get_reward_percentages(self) -> RewardsPercentages:
        """Get current reward percentage allocations for the authenticated account."""
        path, params = _rewards_actions.build_get_reward_percentages_request(
            signature_type=signature_type_for(self._ctx.wallet_type)
        )
        return _rewards_actions.parse_reward_percentages(
            self._ctx.secure_clob.get_json(path, params=params)
        )

    def approve_erc20(
        self,
        *,
        token_address: str,
        spender_address: str,
        amount: int | Literal["max"],
        metadata: str | None = None,
    ) -> SyncTransactionHandle:
        """Submit an ERC-20 approval transaction.

        Args:
            amount: Base-units amount to approve, or ``"max"`` for the maximum value.

        Returns:
            A transaction handle. Call ``wait()`` to wait for a terminal outcome.
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
        return self._dispatch_single_call(call, metadata=resolved_metadata)

    def approve_erc1155_for_all(
        self,
        *,
        token_address: str,
        operator_address: str,
        approved: bool = True,
        metadata: str | None = None,
    ) -> SyncTransactionHandle:
        """Approve or revoke an ERC-1155 operator for all tokens.

        Returns:
            A transaction handle. Call ``wait()`` to wait for a terminal outcome.
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
        return self._dispatch_single_call(call, metadata=resolved_metadata)

    def transfer_erc20(
        self,
        *,
        token_address: str,
        recipient_address: str,
        amount: int,
        metadata: str | None = None,
    ) -> SyncTransactionHandle:
        """Submit an ERC-20 transfer transaction.

        Args:
            amount: Base-units amount to transfer.

        Returns:
            A transaction handle. Call ``wait()`` to wait for a terminal outcome.
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
        return self._dispatch_single_call(call, metadata=resolved_metadata)

    def setup_trading_approvals(self) -> SyncDeprecatedTransactionHandle:
        """Approve the standard set of trading allowances for the wallet.

        EOA wallets submit approvals directly. Gasless wallets submit a relayed
        transaction. Already-approved allowances are skipped, and the method waits
        internally for any submitted transactions.

        Returns:
            A deprecated compatibility handle whose ``wait()`` returns immediately.
        """
        calls = resolve_missing_trading_approval_calls_sync(
            self._ctx.rpc,
            wallet=self._ctx.wallet,
            config=self._ctx.environment_config,
        )
        if not calls:
            return SyncDeprecatedTransactionHandle()
        if self._ctx.wallet_type == "EOA":
            for call in calls:
                handle = self._broadcast_eoa_call(call)
                handle.wait()
            return SyncDeprecatedTransactionHandle()
        handle = prepare_gasless_transaction_sync(
            self._ctx, calls=calls, metadata="Trading setup approvals"
        )
        handle.wait()
        return SyncDeprecatedTransactionHandle()

    def setup_gasless_wallet(self) -> Self:
        """Return this client.

        Deprecated. Secure client creation now sets up the wallet required for
        the selected trading flow.
        """
        return self

    def is_gasless_ready(self) -> bool:
        """Return True.

        Deprecated. Secure client creation now performs the required wallet setup.
        """
        return True

    def execute_transaction(
        self,
        *,
        calls: Sequence[TransactionCall],
        metadata: str | None = None,
    ) -> SyncTransactionHandle:
        """Submit one or more transaction calls for the authenticated wallet.

        Use this low-level escape hatch to combine supported transaction calls
        differently than the higher-level SDK workflows. Calls are executed in order.

        Returns:
            A transaction handle. Call ``wait()`` to wait for a terminal outcome.
        """
        return self._dispatch_calls(
            list(calls), metadata=metadata if metadata is not None else "Execute transaction"
        )

    def split_position(
        self,
        *,
        condition_id: str | None = None,
        legs: Sequence[str] | None = None,
        amount: int,
        metadata: str | None = None,
    ) -> SyncTransactionHandle:
        """Split collateral into market or combo positions.

        Provide exactly one of ``condition_id`` for market positions or ``legs``
        for combo positions.

        Args:
            amount: Base-units collateral amount to split.

        Returns:
            A transaction handle. Call ``wait()`` to wait for a terminal outcome.
        """
        if (condition_id is None) == (legs is None):
            raise UserInputError("Provide exactly one of condition_id or legs")
        if legs is not None:
            if amount <= 0:
                raise UserInputError("Split amount must be positive for combo positions")
            canonical_legs = canonicalize_combo_legs(legs)
            combo = derive_combo_position_context(canonical_legs)
            calls = [
                combinatorial_prepare_condition_call(
                    combinatorial_module=cast(
                        EvmAddress, self._ctx.environment_config.combinatorial_module
                    ),
                    legs=list(canonical_legs),
                ),
                split_v2_call(
                    router=cast(EvmAddress, self._ctx.environment_config.protocol_v2_router),
                    condition_id=combo.condition_id,
                    amount=amount,
                ),
            ]
            resolved_metadata = (
                metadata
                if metadata is not None
                else f"Split {amount} combo positions for condition {combo.condition_id}"
            )
            return self._dispatch_calls(calls, metadata=resolved_metadata)
        assert condition_id is not None
        context = self._resolve_market_position_context(condition_id=condition_id)
        call = split_position_call(
            target=context.adapter_address,
            collateral=cast(EvmAddress, self._ctx.environment_config.collateral_token),
            condition_id=context.condition_id,
            amount=amount,
        )
        resolved_metadata = (
            metadata
            if metadata is not None
            else f"Split {amount} positions for condition {context.condition_id}"
        )
        return self._dispatch_single_call(call, metadata=resolved_metadata)

    def merge_positions(
        self,
        *,
        condition_id: str | None = None,
        legs: Sequence[str] | None = None,
        amount: int | Literal["max"],
        metadata: str | None = None,
    ) -> SyncTransactionHandle:
        """Merge market or combo positions back into collateral.

        Provide exactly one of ``condition_id`` for market positions or ``legs``
        for combo positions.

        Args:
            amount: Base-units position amount to merge, or ``"max"`` to merge
                the largest available balanced amount.

        Returns:
            A transaction handle. Call ``wait()`` to wait for a terminal outcome.
        """
        if (condition_id is None) == (legs is None):
            raise UserInputError("Provide exactly one of condition_id or legs")
        if legs is not None:
            canonical_legs = canonicalize_combo_legs(legs)
            combo = derive_combo_position_context(canonical_legs)
            balance_call = erc1155_balance_of_batch_call(
                token_address=cast(EvmAddress, self._ctx.environment_config.position_manager),
                owners=[self._ctx.wallet, self._ctx.wallet],
                token_ids=list(combo.position_ids),
            )
            balances = decode_erc1155_balance_of_batch_result(
                self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
            )
            resolved_amount = resolve_merge_amount_from_balances(
                combo.condition_id, balances, amount
            )
            calls = [
                combinatorial_prepare_condition_call(
                    combinatorial_module=cast(
                        EvmAddress, self._ctx.environment_config.combinatorial_module
                    ),
                    legs=list(canonical_legs),
                ),
                merge_v2_call(
                    router=cast(EvmAddress, self._ctx.environment_config.protocol_v2_router),
                    condition_id=combo.condition_id,
                    amount=resolved_amount,
                ),
            ]
            resolved_metadata = (
                metadata
                if metadata is not None
                else f"Merge {resolved_amount} combo positions for condition {combo.condition_id}"
            )
            return self._dispatch_calls(calls, metadata=resolved_metadata)
        assert condition_id is not None
        context = self._resolve_market_position_context(condition_id=condition_id)
        balance_call = erc1155_balance_of_batch_call(
            token_address=context.position_erc1155_address,
            owners=[self._ctx.wallet, self._ctx.wallet],
            token_ids=[str(token_id) for token_id in context.token_ids],
        )
        balances = decode_erc1155_balance_of_batch_result(
            self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
        )
        resolved_amount = resolve_merge_amount_from_balances(context.condition_id, balances, amount)
        call = merge_positions_call(
            target=context.adapter_address,
            collateral=cast(EvmAddress, self._ctx.environment_config.collateral_token),
            condition_id=context.condition_id,
            amount=resolved_amount,
        )
        resolved_metadata = (
            metadata
            if metadata is not None
            else f"Merge {resolved_amount} positions for condition {context.condition_id}"
        )
        return self._dispatch_single_call(call, metadata=resolved_metadata)

    def merge_multiple_positions(
        self,
        *,
        positions: Sequence[MergePositionRequest],
        metadata: str | None = None,
    ) -> SyncTransactionHandle:
        """Merge multiple market positions or multiple combo positions back into collateral.

        Args:
            positions: Position merge requests. Use ``position_id`` for combo
                positions, or ``condition_id`` / ``market_id`` for market positions.
                Do not mix combo and market requests in the same batch.
                Omit ``amount`` or pass ``"max"`` to merge the largest available
                balanced amount for that condition.

        Returns:
            A transaction handle. Call ``wait()`` to wait for a terminal outcome.
        """
        if not positions:
            raise UserInputError("positions must include at least one merge request")

        normalized = [
            normalize_batch_merge_position_request(cast(Mapping[str, object], position))
            for position in positions
        ]
        batch_kinds = {position.kind for position in normalized}
        if len(batch_kinds) != 1:
            raise UserInputError("Cannot mix market and combo positions in one merge batch")

        seen_conditions: set[str] = set()
        calls: list[TransactionCall] = []
        for position in normalized:
            if position.kind == "combo":
                assert position.position_id is not None
                decoded = decode_combo_outcome_position_id(position.position_id)
                condition_key = str(decoded.condition_id)
                if condition_key in seen_conditions:
                    raise UserInputError("position_ids must reference distinct combo conditions")
                seen_conditions.add(condition_key)
                token_ids = derive_combo_outcome_position_ids(decoded.condition_id)
                balance_call = erc1155_balance_of_batch_call(
                    token_address=cast(EvmAddress, self._ctx.environment_config.position_manager),
                    owners=[self._ctx.wallet, self._ctx.wallet],
                    token_ids=list(token_ids),
                )
                balances = decode_erc1155_balance_of_batch_result(
                    self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
                )
                resolved_amount = resolve_merge_amount_from_balances(
                    decoded.condition_id, balances, position.amount
                )
                calls.append(
                    merge_v2_call(
                        router=cast(EvmAddress, self._ctx.environment_config.protocol_v2_router),
                        condition_id=decoded.condition_id,
                        amount=resolved_amount,
                    )
                )
                continue

            context = self._resolve_market_position_context(
                condition_id=position.condition_id,
                market_id=position.market_id,
            )
            condition_key = str(context.condition_id)
            if condition_key in seen_conditions:
                raise UserInputError("positions must reference distinct market conditions")
            seen_conditions.add(condition_key)
            balance_call = erc1155_balance_of_batch_call(
                token_address=context.position_erc1155_address,
                owners=[self._ctx.wallet, self._ctx.wallet],
                token_ids=[str(token_id) for token_id in context.token_ids],
            )
            balances = decode_erc1155_balance_of_batch_result(
                self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
            )
            resolved_amount = resolve_merge_amount_from_balances(
                context.condition_id, balances, position.amount
            )
            calls.append(
                merge_positions_call(
                    target=context.adapter_address,
                    collateral=cast(EvmAddress, self._ctx.environment_config.collateral_token),
                    condition_id=context.condition_id,
                    amount=resolved_amount,
                )
            )

        batch_label = "combo positions" if "combo" in batch_kinds else "positions"
        resolved_metadata = (
            metadata if metadata is not None else f"Merge {len(calls)} {batch_label}"
        )
        return self.execute_transaction(calls=calls, metadata=resolved_metadata)

    @overload
    def redeem_positions(
        self, *, condition_id: str, metadata: str | None = None
    ) -> SyncTransactionHandle: ...
    @overload
    def redeem_positions(
        self, *, market_id: str, metadata: str | None = None
    ) -> SyncTransactionHandle: ...
    @overload
    def redeem_positions(
        self, *, position_id: str, metadata: str | None = None
    ) -> SyncTransactionHandle: ...
    def redeem_positions(
        self,
        *,
        condition_id: str | None = None,
        market_id: str | None = None,
        position_id: str | None = None,
        metadata: str | None = None,
    ) -> SyncTransactionHandle:
        """Redeem resolved market or combo positions.

        Provide exactly one of ``condition_id``, ``market_id``, or combo
        ``position_id``.

        Returns:
            A transaction handle. Call ``wait()`` to wait for a terminal outcome.

        Raises:
            UserInputError: If both identifiers or neither identifier is provided.
        """
        if sum(value is not None for value in (condition_id, market_id, position_id)) != 1:
            raise UserInputError("Provide exactly one of condition_id, market_id, or position_id")
        if position_id is not None:
            decoded = decode_combo_outcome_position_id(position_id)
            balance_call = erc1155_balance_of_call(
                token_address=cast(EvmAddress, self._ctx.environment_config.position_manager),
                owner=self._ctx.wallet,
                token_id=position_id,
            )
            balance = decode_erc1155_balance_of_result(
                self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
            )
            if balance == 0:
                raise UserInputError("Combo position has no balance to redeem")
            call = redeem_v2_call(
                router=cast(EvmAddress, self._ctx.environment_config.protocol_v2_router),
                condition_id=decoded.condition_id,
                outcome_index=decoded.outcome_index,
                amount=balance,
            )
            resolved_metadata = (
                metadata if metadata is not None else f"Redeem combo position {position_id}"
            )
            return self._dispatch_single_call(call, metadata=resolved_metadata)
        context = self._resolve_market_position_context(
            condition_id=condition_id,
            market_id=market_id,
            closed=True,
        )
        call = ctf_redeem_positions_call(
            ctf=context.adapter_address,
            collateral=cast(EvmAddress, self._ctx.environment_config.collateral_token),
            condition_id=context.condition_id,
        )
        resolved_metadata = (
            metadata
            if metadata is not None
            else f"Redeem positions for condition {context.condition_id}"
        )
        return self._dispatch_single_call(call, metadata=resolved_metadata)

    def plan_collateral_return(self) -> CollateralReturnPlanResponse:
        """Plan a collateral return for the authenticated wallet.

        Builds an executable plan that unwinds redundant position value and
        returns it to the wallet as collateral. Planning can take several
        minutes for wallets with many positions. Inspect the plan — notably
        ``net_pusd_out`` and ``position_summary`` — before executing it
        with :meth:`execute_collateral_return_plan`.

        Returns:
            The collateral return plan. When ``truncated`` is True the plan
            covers only the first executable chunk; execute it, then request
            a fresh plan for the remainder.
        """
        return _combos_actions.plan_collateral_return_sync(self._ctx)

    def execute_collateral_return_plan(
        self, *, plan: CollateralReturnPlanResponse
    ) -> SyncGaslessTransactionHandle:
        """Execute a collateral return plan.

        The plan executes exactly as returned by
        :meth:`plan_collateral_return`; nothing is recomputed client-side.
        No approval transactions are submitted implicitly.

        Example::

            plan = client.plan_collateral_return()
            while plan.net_pusd_out > 0:
                handle = client.execute_collateral_return_plan(plan=plan)
                handle.wait()
                if not plan.truncated:
                    break
                plan = client.plan_collateral_return()

        Returns:
            A transaction handle. Call ``wait()`` to wait for a terminal outcome.

        Raises:
            RequestRejectedError: With ``status`` 409 if the plan no longer
                matches current wallet state; request a fresh plan and
                execute that instead.
        """
        return _combos_actions.execute_collateral_return_plan_sync(self._ctx, plan=plan)

    def _broadcast_eoa_call(self, call: TransactionCall) -> SyncEoaTransactionHandle:
        return broadcast_eoa_call_sync(
            rpc=self._ctx.rpc,
            signer=self._ctx.signer,
            call=call,
            chain_id=self._ctx.environment_config.chain_id,
            max_polls=self._ctx.environment_config.relayer_max_polls,
            poll_delay_s=self._ctx.environment_config.relayer_poll_frequency_ms / 1000,
        )

    def _dispatch_single_call(
        self, call: TransactionCall, *, metadata: str
    ) -> SyncTransactionHandle:
        if self._ctx.wallet_type == "EOA":
            return self._broadcast_eoa_call(call)
        return prepare_gasless_transaction_sync(self._ctx, calls=[call], metadata=metadata)

    def _dispatch_calls(
        self, calls: list[TransactionCall], *, metadata: str
    ) -> SyncTransactionHandle:
        if not calls:
            raise UserInputError("At least one transaction call is required")
        if self._ctx.wallet_type == "EOA":
            for call in calls[:-1]:
                self._broadcast_eoa_call(call).wait()
            return self._broadcast_eoa_call(calls[-1])
        return prepare_gasless_transaction_sync(self._ctx, calls=calls, metadata=metadata)

    def _ensure_wallet_ready(self) -> Self:
        ctx = self._ctx
        if ctx.wallet_type == "EOA":
            return self
        deployed = fetch_deployed_sync(
            ctx.relayer,
            address=str(ctx.wallet),
            type=_relayer_transaction_type_for_wallet(ctx.wallet_type),
        )
        if deployed:
            return self
        if ctx.wallet_type == "DEPOSIT_WALLET":
            self._deploy_default_deposit_wallet()
            return self
        raise UserInputError(
            f"Wallet {ctx.wallet} does not exist. Provide an existing wallet address, "
            "or omit wallet to use the default Deposit Wallet flow."
        )

    def _deploy_default_deposit_wallet(self) -> None:
        ctx = self._ctx
        current_deposit_wallet = derive_beacon_deposit_wallet_address(
            ctx.signer.address, ctx.environment_config.wallet_derivation
        )
        if str(ctx.wallet).lower() != current_deposit_wallet.lower():
            raise UserInputError(
                f"Wallet {ctx.wallet} does not match the expected Deposit Wallet "
                f"{current_deposit_wallet} for this signer, nor a deployed wallet address."
            )
        handle = submit_deposit_wallet_create_sync(ctx, metadata="Deploy Deposit Wallet")
        handle.wait()

    def _resolve_market_position_context(
        self,
        *,
        condition_id: str | None = None,
        market_id: str | None = None,
        closed: bool | None = None,
    ) -> MarketPositionContext:
        if (condition_id is None) == (market_id is None):
            raise UserInputError("Provide exactly one of condition_id or market_id")
        if condition_id is not None:
            context = f"condition {condition_id}"
            if closed is None:
                page = self.list_markets(condition_ids=[condition_id], page_size=1).first_page()
            else:
                page = self.list_markets(
                    condition_ids=[condition_id], closed=closed, page_size=1
                ).first_page()
        else:
            assert market_id is not None
            context = f"market {market_id}"
            if closed is None:
                page = self.list_markets(ids=[parse_market_id(market_id)], page_size=1).first_page()
            else:
                page = self.list_markets(
                    ids=[parse_market_id(market_id)], closed=closed, page_size=1
                ).first_page()
        markets = page.items
        if not markets:
            raise UserInputError(f"No market found for {context}")
        if len(markets) != 1:
            raise UserInputError(f"Expected exactly one market for {context}, got {len(markets)}")
        return normalize_market_position_context(
            markets[0],
            context=context,
            collateral_adapter=cast(EvmAddress, self._ctx.environment_config.collateral_adapter),
            neg_risk_collateral_adapter=cast(
                EvmAddress, self._ctx.environment_config.neg_risk_collateral_adapter
            ),
            conditional_tokens=cast(EvmAddress, self._ctx.environment_config.conditional_tokens),
            neg_risk_adapter=cast(EvmAddress, self._ctx.environment_config.neg_risk_adapter),
        )


def _bootstrap_credentials_sync(
    *,
    config: EnvironmentConfig,
    signer: LocalAccount,
    clob: SyncTransport,
    provided: ApiKeyCreds | None,
    nonce: int,
    validate: bool,
    logger: logging.Logger | None,
) -> ApiKeyCreds:
    if provided is not None and (
        not validate
        or _credentials_are_active_sync(
            config=config,
            signer=signer,
            credentials=provided,
            logger=logger,
        )
    ):
        return provided

    signature = sign_api_key_auth(
        signer,
        chain_id=config.chain_id,
        timestamp=int(time.time()),
        nonce=nonce,
    )
    return _auth_actions.create_or_derive_api_key_sync(clob, signature)


def _resolve_requested_wallet_sync(
    *,
    signer: LocalAccount,
    wallet: str | None,
    config: EnvironmentConfig,
    logger: logging.Logger | None,
) -> str:
    if wallet is not None:
        return wallet
    legacy_deposit_wallet = derive_uups_deposit_wallet_address(
        signer.address, config.wallet_derivation
    )
    relayer = SyncTransport(base_url=config.relayer_url, logger=logger)
    try:
        if fetch_deployed_sync(
            relayer,
            address=legacy_deposit_wallet,
            type=RelayerTransactionType.WALLET,
        ):
            return legacy_deposit_wallet
        return derive_beacon_deposit_wallet_address(signer.address, config.wallet_derivation)
    finally:
        relayer.close()


def _relayer_transaction_type_for_wallet(
    wallet_type: WalletType,
) -> RelayerTransactionType | None:
    if wallet_type == "DEPOSIT_WALLET":
        return RelayerTransactionType.WALLET
    if wallet_type == "POLY_PROXY":
        return RelayerTransactionType.PROXY
    if wallet_type == "GNOSIS_SAFE":
        return RelayerTransactionType.SAFE
    return None


def _credentials_are_active_sync(
    *,
    config: EnvironmentConfig,
    signer: LocalAccount,
    credentials: ApiKeyCreds,
    logger: logging.Logger | None,
) -> bool:
    probe = SyncTransport(
        base_url=config.clob_url,
        logger=logger,
        header_resolver=_make_l2_header_resolver_sync(signer, credentials),
    )
    try:
        keys = _auth_actions.fetch_api_keys_sync(probe)
    except RequestRejectedError as error:
        if error.status == 401:
            return False
        raise
    finally:
        probe.close()
    return credentials.key in keys


def _make_l2_header_resolver_sync(
    signer: LocalAccount, credentials: ApiKeyCreds
) -> SyncHeaderResolver:
    def resolver(method: str, path: str, body: str | None) -> Mapping[str, str]:
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
