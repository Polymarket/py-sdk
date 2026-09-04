import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Protocol,
    Self,
    TypeAlias,
    assert_never,
    cast,
    overload,
)

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils.address import to_checksum_address

from polymarket._internal.actions import account as _account_actions
from polymarket._internal.actions import auth as _auth_actions
from polymarket._internal.actions import builders as _builders_actions
from polymarket._internal.actions import clob as _clob_actions
from polymarket._internal.actions import combo_rfq as _combo_rfq_actions
from polymarket._internal.actions import combos as _combos_actions
from polymarket._internal.actions import data as _data_actions
from polymarket._internal.actions import gamma as _gamma_actions
from polymarket._internal.actions import rewards as _rewards_actions
from polymarket._internal.actions import rfq as _rfq_actions
from polymarket._internal.actions import session_keys as _session_key_actions
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
from polymarket._internal.actions.orders.cache import AsyncOrderMetadataCache
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
from polymarket._internal.actions.orders.settlement import DEFAULT_SETTLEMENT_TIMEOUT_S
from polymarket._internal.actions.orders.typed_data import (
    build_order_signature,
    build_order_typed_data,
)
from polymarket._internal.actions.orders.types import OrderDraft
from polymarket._internal.actions.perps import credentials as _perps_credentials
from polymarket._internal.actions.perps import funds as _perps_funds
from polymarket._internal.actions.perps import public as _perps_actions
from polymarket._internal.actions.relayer.approvals import (
    build_missing_trading_approval_calls,
    get_trading_approvals_state,
)
from polymarket._internal.actions.relayer.auth import (
    build_builder_key_headers,
    make_relayer_header_resolver,
)
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
from polymarket._internal.actions.relayer.deployed import fetch_deployed
from polymarket._internal.actions.relayer.gasless import (
    prepare_gasless_transaction,
    submit_deposit_wallet_create,
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
from polymarket._internal.context import AsyncSecureClientContext
from polymarket._internal.dispatch import (
    async_dispatch,
    async_paginate_keyset,
    async_paginate_offset,
    async_paginate_page_based,
)
from polymarket._internal.environment import EnvironmentConfig, get_environment_config
from polymarket._internal.eoa.broadcast import broadcast_eoa_call
from polymarket._internal.eoa.rpc import JsonRpcClient
from polymarket._internal.hmac import build_hmac_signature
from polymarket._internal.l1_auth import sign_api_key_auth
from polymarket._internal.rfq import RfqSessionContext
from polymarket._internal.streams.handle import AsyncSubscriptionHandle, SubscriptionHandle
from polymarket._internal.wallet import (
    SignerType,
    WalletType,
    classify_account,
    derive_beacon_deposit_wallet_address,
    derive_uups_deposit_wallet_address,
    signature_type_for,
    wrap_deposit_wallet_signature,
)
from polymarket.auth import ApiKey, BuilderApiKey
from polymarket.clients._transport import AsyncTransport
from polymarket.clients.async_public import AsyncPublicClient
from polymarket.environments import PRODUCTION, Environment
from polymarket.errors import (
    RequestRejectedError,
    SigningError,
    TransportError,
    UnexpectedResponseError,
    UserInputError,
)
from polymarket.models import (
    ApiKeyCreds,
    AssetType,
    BalanceAllowance,
    BuilderFeeRates,
    BuilderTrade,
    ClobTrade,
    ComboMarket,
    Comment,
    Event,
    LastTradePrice,
    LastTradePriceForAsset,
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
    TradingApprovalsState,
)
from polymarket.models.clob.api_key import BuilderApiKeyInfo
from polymarket.models.clob.cancel import CancelOrdersResponse
from polymarket.models.clob.market_events import MarketEvent
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
from polymarket.models.clob.user_events import UserEvent
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
from polymarket.models.perps import (
    PerpsBook,
    PerpsBookDepth,
    PerpsCandle,
    PerpsCredentials,
    PerpsFeeScheduleEntry,
    PerpsFundingRate,
    PerpsInstrument,
    PerpsInstrumentCategory,
    PerpsKlineInterval,
    PerpsMarketEvent,
    PerpsTicker,
    PerpsTrade,
    PerpsWithdrawalId,
)
from polymarket.models.rtds_events import (
    CommentsEvent,
    CryptoPricesChainlinkTwapEvent,
    CryptoPricesEvent,
    EquityPricesEvent,
    RtdsEvent,
)
from polymarket.models.sports_events import SportsEvent
from polymarket.models.types import ClobAssetId, CtfConditionId
from polymarket.pagination import AsyncPaginator, Page
from polymarket.rate_limit import RateLimitUpdateListener
from polymarket.rfq import (
    ComboFillResult,
    ComboQuote,
    ComboQuoteAcceptance,
    ComboQuoteResult,
    RfqDirection,
    RfqSide,
    RfqStatusResult,
)
from polymarket.session_keys import (
    AuthorizedSessionKey,
    AuthorizeSessionKeyResult,
    SessionKeyKnownScope,
    SessionKeyScope,
)
from polymarket.streams._specs import (
    CommentsSpec,
    CryptoPricesChainlinkTwapSpec,
    CryptoPricesSpec,
    EquityPricesSpec,
    MarketSpec,
    PerpsSpec,
    SecureSubscription,
    SportsSpec,
    UserSpec,
    normalize_specs,
)
from polymarket.transactions import (
    DeprecatedTransactionHandle,
    EoaTransactionHandle,
    GaslessTransactionHandle,
    MergePositionRequest,
    TransactionHandle,
)
from polymarket.types import EvmAddress, HexString, TransactionHash

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from polymarket._internal.perps_session import PerpsSession
    from polymarket._internal.rfq import RfqQuoterSession
    from polymarket._internal.streams.clob.market import ClobMarketStreamManager
    from polymarket._internal.streams.clob.user import ClobUserStreamManager
    from polymarket._internal.streams.perps.market import PerpsMarketStreamManager
    from polymarket._internal.streams.rtds.manager import RtdsStreamManager
    from polymarket._internal.streams.sports.manager import SportsStreamManager
    from polymarket.rfq import RfqSession


_CREATE_TOKEN = object()

_L2HeaderResolver: TypeAlias = Callable[[str, str, str | None], Awaitable[Mapping[str, str]]]


class AsyncCloseable(Protocol):
    async def close(self) -> None: ...


class _RfqSessionCloser:
    def __init__(self, close: Callable[[], Awaitable[None]]) -> None:
        self._close = close

    async def close(self) -> None:
        await self._close()


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
        self._perps_manager: PerpsMarketStreamManager | None = None
        self._perps_sessions: set[PerpsSession] = set()
        self._rfq_session: RfqQuoterSession | None = None
        self._rfq_session_connecting: RfqQuoterSession | None = None
        self._rfq_session_opening: asyncio.Task[RfqQuoterSession] | None = None
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
        on_rate_limit_update: RateLimitUpdateListener | None = None,
    ) -> Self:
        """Create an authenticated async client.

        Args:
            private_key: EVM private key used for signing.
            wallet: Wallet address to act for. Defaults to the signer's Deposit Wallet.
            credentials: Existing API credentials. When omitted, credentials are
                derived during client creation.
            api_key: Optional key for gasless wallet and relayed transaction workflows.
            nonce: Credential derivation nonce. Cannot be combined with ``credentials``.
            on_rate_limit_update: Listener invoked whenever a response reports
                per-signer rate-limit state, as order and cancellation responses
                do. Errors raised by the listener are ignored.

        Raises:
            UserInputError: If key material, wallet, nonce, or credentials are invalid.
            RequestRejectedError: If credential derivation or validation is rejected.
        """
        client = await cls._create(
            private_key=private_key,
            wallet=wallet,
            environment=environment,
            credentials=credentials,
            api_key=api_key,
            nonce=nonce,
            validate_credentials=True,
            logger=logger,
            on_rate_limit_update=on_rate_limit_update,
        )
        try:
            return await client._ensure_wallet_ready()
        except BaseException:
            await client.close()
            raise

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
        on_rate_limit_update: RateLimitUpdateListener | None = None,
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

        resolved_wallet = await _resolve_requested_wallet(
            signer=signer,
            wallet=wallet,
            config=config,
            logger=logger,
        )
        account = classify_account(
            signer=signer.address,
            wallet=resolved_wallet,
            config=config.wallet_derivation,
        )
        try:
            wallet_checksum = to_checksum_address(resolved_wallet)
        except ValueError as error:
            raise UserInputError(f"Invalid wallet address: {error}") from error

        bootstrap_clob = AsyncTransport(base_url=config.clob_url, logger=logger)
        try:
            resolved_credentials = await _bootstrap_credentials(
                config=config,
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
            wallet_type=account.wallet_type,
            signer_type=account.signer_type,
            environment=environment,
            config=config,
            credentials=resolved_credentials,
            api_key=api_key,
            logger=logger,
            on_rate_limit_update=on_rate_limit_update,
        )

    @classmethod
    def _construct_for_wallet(
        cls,
        *,
        signer: LocalAccount,
        wallet: str,
        wallet_type: WalletType,
        signer_type: SignerType,
        environment: Environment,
        config: EnvironmentConfig,
        credentials: ApiKeyCreds,
        api_key: ApiKey | None,
        logger: logging.Logger | None,
        on_rate_limit_update: RateLimitUpdateListener | None,
    ) -> Self:
        wallet_checksum = to_checksum_address(wallet)
        branded_wallet = cast(EvmAddress, wallet_checksum)

        gamma = AsyncTransport(base_url=config.gamma_url, logger=logger)
        data = AsyncTransport(base_url=config.data_url, logger=logger)
        rfq = AsyncTransport(base_url=config.rfq_url, logger=logger)
        clob = AsyncTransport(
            base_url=config.clob_url,
            logger=logger,
            on_rate_limit_update=on_rate_limit_update,
        )
        relayer_resolver = make_relayer_header_resolver(api_key) if api_key is not None else None
        relayer = AsyncTransport(
            base_url=config.relayer_url,
            logger=logger,
            header_resolver=relayer_resolver,
        )
        combos = AsyncTransport(
            base_url=config.collateral_return_url,
            logger=logger,
            header_resolver=relayer_resolver,
        )
        builder_gateway = AsyncTransport(
            base_url=config.builder_gateway_url,
            logger=logger,
            header_resolver=_make_builder_gateway_header_resolver(api_key, signer, credentials),
        )
        secure_clob = AsyncTransport(
            base_url=config.clob_url,
            logger=logger,
            header_resolver=_make_l2_header_resolver(signer, credentials),
            on_rate_limit_update=on_rate_limit_update,
        )
        rpc_transport = AsyncTransport(base_url=config.rpc_url, logger=logger)
        rpc = JsonRpcClient(rpc_transport)

        ctx = AsyncSecureClientContext(
            environment=environment,
            _resolved_environment_config=config,
            gamma=gamma,
            data=data,
            rfq=rfq,
            clob=clob,
            perps=AsyncTransport(base_url=config.perps_url, logger=logger),
            signer=signer,
            credentials=credentials,
            secure_clob=secure_clob,
            wallet=branded_wallet,
            wallet_type=wallet_type,
            signer_type=signer_type,
            relayer=relayer,
            combos=combos,
            builder_gateway=builder_gateway,
            api_key=api_key,
            rpc=rpc,
            order_metadata=AsyncOrderMetadataCache(),
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

    async def authorize_session_key(
        self,
        *,
        address: str,
        scopes: Sequence[SessionKeyScope] = (SessionKeyKnownScope.ALL,),
        idempotency_key: str | None = None,
    ) -> AuthorizeSessionKeyResult:
        """Authorize an externally managed signer for selected venues.

        The SDK receives only the public address. The application remains
        responsible for generating, storing, and protecting the private key.
        Requires a :class:`BuilderApiKey` passed as ``api_key=`` when
        constructing the client.
        Scope names are normalized to uppercase. Unknown names remain usable
        before this SDK enumerates them. When scopes are omitted,
        authorization defaults to ``ALL``.
        Authorizations expire 180 days after they are created.

        Resolves after the submitted transaction is confirmed and the session
        key appears in the active session-key list.

        Raises:
            UserInputError: If the client or authorization input is invalid.
            RequestRejectedError: If the authorization request is rejected.
            RateLimitError: If the authorization or transaction request is rate-limited.
            SigningError: If the owner signature cannot be produced.
            TransportError: If a network request fails.
            UnexpectedResponseError: If an authorization or transaction response is malformed.
            TimeoutError: If transaction confirmation exceeds the wait budget.
            TransactionFailedError: If the authorization transaction fails.
        """
        return await _session_key_actions.authorize_session_key(
            self._ctx,
            address=address,
            scopes=scopes,
            idempotency_key=idempotency_key,
        )

    async def fetch_session_keys(self) -> tuple[AuthorizedSessionKey, ...]:
        """Fetch active session keys authorized for the Deposit Wallet.

        Raises:
            UserInputError: If this client is not the Deposit Wallet owner.
            RequestRejectedError: If the request is rejected.
            RateLimitError: If the request is rate-limited.
            SigningError: If request authentication cannot be produced.
            TransportError: If the network request fails.
            UnexpectedResponseError: If the response is malformed.
        """
        return await _session_key_actions.fetch_session_keys(self._ctx)

    async def revoke_session_key(
        self,
        *,
        address: str,
        idempotency_key: str | None = None,
    ) -> None:
        """Revoke a session key authorized for the Deposit Wallet.

        Returns once the key is absent from the active-key registry and unusable.
        Requires an ``api_key=`` that supports gasless transactions.

        Raises:
            UserInputError: If the client or revocation input is invalid.
            RequestRejectedError: If the revocation request is rejected.
            RateLimitError: If a revocation or registry request remains rate-limited.
            SigningError: If the owner signature cannot be produced.
            TransportError: If a network request fails.
            TransactionFailedError: If the revocation transaction fails.
            UnexpectedResponseError: If a revocation or registry response is malformed.
            TimeoutError: If registry removal exceeds the wait budget.
        """
        return await _session_key_actions.revoke_session_key(
            self._ctx,
            address=address,
            idempotency_key=idempotency_key,
        )

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
        self, specs: CryptoPricesChainlinkTwapSpec, /
    ) -> SubscriptionHandle[CryptoPricesChainlinkTwapEvent]: ...
    @overload
    async def subscribe(
        self, specs: EquityPricesSpec, /
    ) -> SubscriptionHandle[EquityPricesEvent]: ...
    @overload
    async def subscribe(self, specs: PerpsSpec, /) -> SubscriptionHandle[PerpsMarketEvent]: ...
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
        self, specs: Sequence[CryptoPricesChainlinkTwapSpec], /
    ) -> SubscriptionHandle[CryptoPricesChainlinkTwapEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[EquityPricesSpec], /
    ) -> SubscriptionHandle[EquityPricesEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[PerpsSpec], /
    ) -> SubscriptionHandle[PerpsMarketEvent]: ...
    @overload
    async def subscribe(self, specs: Sequence[UserSpec], /) -> SubscriptionHandle[UserEvent]: ...
    @overload
    async def subscribe(
        self, specs: Sequence[SecureSubscription], /
    ) -> SubscriptionHandle[
        MarketEvent | SportsEvent | RtdsEvent | PerpsMarketEvent | UserEvent
    ]: ...
    async def subscribe(
        self,
        specs: SecureSubscription | Sequence[SecureSubscription],
    ) -> SubscriptionHandle[MarketEvent | SportsEvent | RtdsEvent | PerpsMarketEvent | UserEvent]:
        """Subscribe to one or more public or authenticated realtime streams.

        Pass a single subscription spec for one stream or a sequence of specs to
        receive events through one merged handle. Authenticated user stream specs
        are supported only by secure clients.

        Returns:
            A subscription handle. Iterate over it to receive events and close it
            when finished.
        """
        items = normalize_specs(specs)
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
                elif isinstance(spec, PerpsSpec):
                    handles.append(await self._get_perps_manager().subscribe(spec))
                elif isinstance(
                    spec,
                    CommentsSpec
                    | CryptoPricesSpec
                    | CryptoPricesChainlinkTwapSpec
                    | EquityPricesSpec,
                ):  # pyright: ignore[reportUnnecessaryIsInstance]
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
                SubscriptionHandle[
                    MarketEvent | SportsEvent | RtdsEvent | PerpsMarketEvent | UserEvent
                ],
                handles[0],
            )
        from polymarket._internal.streams.merged_handle import MergedSubscriptionHandle

        return cast(
            SubscriptionHandle[
                MarketEvent | SportsEvent | RtdsEvent | PerpsMarketEvent | UserEvent
            ],
            MergedSubscriptionHandle(handles),
        )

    def _get_market_manager(self) -> "ClobMarketStreamManager":
        if self._market_manager is None:
            from polymarket._internal.streams.clob.market import ClobMarketStreamManager

            self._market_manager = ClobMarketStreamManager(
                url=self._ctx.environment_config.clob_market_ws_url,
                logger=self._streams_logger,
            )
        return self._market_manager

    def _get_sports_manager(self) -> "SportsStreamManager":
        if self._sports_manager is None:
            from polymarket._internal.streams.sports.manager import SportsStreamManager

            self._sports_manager = SportsStreamManager(
                url=self._ctx.environment_config.sports_ws_url,
                logger=self._streams_logger,
            )
        return self._sports_manager

    def _get_rtds_manager(self) -> "RtdsStreamManager":
        if self._rtds_manager is None:
            from polymarket._internal.streams.rtds.manager import RtdsStreamManager

            self._rtds_manager = RtdsStreamManager(
                url=self._ctx.environment_config.rtds_ws_url,
                logger=self._streams_logger,
            )
        return self._rtds_manager

    def _get_user_manager(self) -> "ClobUserStreamManager":
        if self._user_manager is None:
            from polymarket._internal.streams.clob.user import ClobUserStreamManager

            self._user_manager = ClobUserStreamManager(
                url=self._ctx.environment_config.clob_user_ws_url,
                resolve_credentials=self._resolve_api_key_credentials,
                logger=self._streams_logger,
            )
        return self._user_manager

    def _get_perps_manager(self) -> "PerpsMarketStreamManager":
        if self._perps_manager is None:
            from polymarket._internal.streams.perps.market import PerpsMarketStreamManager

            self._perps_manager = PerpsMarketStreamManager(
                url=self._ctx.environment_config.perps_ws_url,
                logger=self._streams_logger,
            )
        return self._perps_manager

    async def _resolve_api_key_credentials(self) -> ApiKeyCreds:
        return self._ctx.credentials

    async def open_perps_session(
        self,
        *,
        credentials: PerpsCredentials | None = None,
        expires_in: "timedelta | None" = None,
        label: str | None = None,
    ) -> "PerpsSession":
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        Open an authenticated Perps account session.

        With no arguments, new delegated session credentials are created with
        a wallet signature and expire after one week. Pass ``expires_in`` for
        a different credential lifetime, or pass previously returned
        ``credentials`` to validate and resume them without a new wallet
        signature.

        Args:
            credentials: Existing delegated credentials to validate and resume.
            expires_in: Delegated credential lifetime for newly created credentials.
            label: Optional label for newly created credentials.

        Returns:
            A connected session. Use it to place and cancel orders, read
            account state, and iterate over realtime account events. Close it
            when finished.
        """
        from polymarket._internal.perps_session import PerpsSession

        if credentials is not None:
            if expires_in is not None or label is not None:
                raise UserInputError("expires_in and label cannot be combined with credentials")
            resolved = await _perps_credentials.resume_credentials(
                self._ctx.perps,
                signer_address=self._ctx.signer.address,
                credentials=credentials,
            )
        else:
            resolved = await _perps_credentials.create_credentials(
                self._ctx.perps,
                signer=self._ctx.signer,
                chain_id=self._ctx.environment_config.chain_id,
                expires_in=(
                    expires_in
                    if expires_in is not None
                    else _perps_credentials.DEFAULT_CREDENTIAL_TTL
                ),
                label=label,
            )
        session = PerpsSession(
            chain_id=self._ctx.environment_config.chain_id,
            credentials=resolved,
            rest_url=self._ctx.environment_config.perps_url,
            ws_url=self._ctx.environment_config.perps_ws_url,
            logger=self._streams_logger,
            on_close=self._perps_sessions.discard,
        )
        self._perps_sessions.add(session)
        try:
            await session.open()
        except BaseException:
            await session.close()
            raise
        return session

    async def revoke_perps_credentials(self, *, proxy: str) -> None:
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        Revoke delegated Perps session credentials by proxy address.

        The revocation is signed by the owner account and also works for
        credentials that are not currently in use.
        """
        await _perps_credentials.revoke_credentials(
            self._ctx.perps,
            signer=self._ctx.signer,
            chain_id=self._ctx.environment_config.chain_id,
            proxy=proxy,
        )

    async def deposit_to_perps(
        self, *, amount: int, metadata: str | None = None
    ) -> TransactionHandle:
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        Deposit collateral into the Perps account.

        The deposit sends approved collateral into the Perps deposit contract
        and credits the authenticated signer account. It does not approve
        collateral spending; approve the Perps deposit contract first when
        allowance is missing.

        Args:
            amount: Base-units collateral amount to deposit.
            metadata: Optional wallet-visible metadata for gasless deposit workflows.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
        """
        call = _perps_funds.perps_deposit_call(
            deposit_contract=cast(
                EvmAddress, to_checksum_address(self._ctx.environment_config.perps_deposit_contract)
            ),
            token=cast(
                EvmAddress, to_checksum_address(self._ctx.environment_config.collateral_token)
            ),
            amount=amount,
            to=cast(EvmAddress, self._ctx.signer.address),
        )
        resolved_metadata = metadata if metadata is not None else f"Deposit {amount} to Perps"
        return await self._dispatch_single_call(call, metadata=resolved_metadata)

    async def withdraw_from_perps(self, *, amount: int) -> PerpsWithdrawalId:
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        Request a Perps withdrawal to the authenticated wallet.

        The withdrawal is signed by the owner account and sends funds to the
        wallet address associated with this client.

        Args:
            amount: Base-units collateral amount to withdraw.

        Returns:
            The withdrawal identifier. Track its status with the session's
            ``list_withdrawals``.
        """
        return await _perps_funds.withdraw_from_perps(
            self._ctx.perps,
            signer=self._ctx.signer,
            chain_id=self._ctx.environment_config.chain_id,
            deposit_contract=self._ctx.environment_config.perps_deposit_contract,
            token=self._ctx.environment_config.collateral_token,
            amount=amount,
            to=str(self._ctx.wallet),
        )

    def open_rfq_session(self) -> "RfqSession":
        """Open an RFQ event session.

        The returned session is an async iterator of RFQ events and an async
        context manager. Iterate over it to receive quote requests,
        confirmation requests, and execution updates.
        """
        _combo_rfq_actions.assert_combos_supported(self._ctx)
        return RfqSessionContext(self._open_rfq_session)

    async def _open_rfq_session(self) -> "RfqQuoterSession":
        if self._rfq_session is not None:
            if not self._rfq_session.closed:
                return self._rfq_session
            self._rfq_session = None

        if self._rfq_session_opening is not None:
            return await self._rfq_session_opening

        task = asyncio.create_task(self._create_rfq_session())
        self._rfq_session_opening = task
        try:
            session = await task
            if session.closed and self._rfq_session_opening is not task:
                raise TransportError("RFQ quoter websocket closed.")
            self._rfq_session = session
            return session
        finally:
            if self._rfq_session_opening is task:
                self._rfq_session_opening = None

    async def _create_rfq_session(self) -> "RfqQuoterSession":
        from polymarket._internal.rfq import RfqQuoterSession

        session: RfqQuoterSession | None = None

        def clear_session() -> None:
            if self._rfq_session is session:
                self._rfq_session = None

        session = RfqQuoterSession(
            chain_id=self._ctx.environment_config.chain_id,
            credentials=self._ctx.credentials,
            exchange=EvmAddress(self._ctx.environment_config.exchange_v3),
            headers=self._ctx.environment_config.rfq_quoter_ws_headers,
            logger=self._streams_logger,
            on_close=clear_session,
            signer=self._ctx.signer,
            url=self._ctx.environment_config.rfq_quoter_ws_url,
            wallet=self._ctx.wallet,
            wallet_type=self._ctx.wallet_type,
        )
        self._rfq_session_connecting = session
        try:
            return await session.open()
        finally:
            if self._rfq_session_connecting is session:
                self._rfq_session_connecting = None

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
        await _close_all(
            ctx.order_metadata,
            self._market_manager,
            self._sports_manager,
            self._rtds_manager,
            self._user_manager,
            self._perps_manager,
            *tuple(self._perps_sessions),
            _RfqSessionCloser(self._close_rfq_session),
            ctx.gamma,
            ctx.data,
            ctx.rfq,
            ctx.clob,
            ctx.perps,
            ctx.secure_clob,
            ctx.relayer,
            ctx.combos,
            ctx.builder_gateway,
            ctx.rpc,
        )

    async def _close_rfq_session(self) -> None:
        opening = self._rfq_session_opening
        connecting = self._rfq_session_connecting
        session = self._rfq_session
        self._rfq_session_opening = None
        self._rfq_session_connecting = None
        self._rfq_session = None
        first_error: BaseException | None = None
        try:
            await _close_all(connecting, session)
        except BaseException as error:
            first_error = error
        if opening is not None:
            try:
                opened = await opening
            except BaseException:
                pass
            else:
                try:
                    await opened.close()
                except BaseException as error:
                    if first_error is None:
                        first_error = error
            try:
                await _close_all(self._rfq_session_connecting, self._rfq_session)
            except BaseException as error:
                if first_error is None:
                    first_error = error
            self._rfq_session_connecting = None
            self._rfq_session = None
        if first_error is not None:
            raise first_error

    def _user_or_wallet(self, user: str | None) -> str:
        return self._ctx.wallet if user is None else user

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
        asset_id: str | None = None,
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
                asset_id=asset_id,
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
    ) -> AsyncPaginator[ComboPosition]:
        """List combo positions for a user or the authenticated wallet.

        Returns:
            An async paginator over matching combo positions.
        """
        spec = _data_actions.list_combo_positions_spec(
            user=self._user_or_wallet(user),
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
            start=start,
            end=end,
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

    def list_combo_activity(
        self,
        *,
        user: str | None = None,
        condition_id: str | Sequence[str] | None = None,
        page_size: int = 50,
    ) -> AsyncPaginator[ComboActivity]:
        """List combo lifecycle activity for a user or the authenticated wallet.

        Returns:
            An async paginator over matching combo lifecycle activity entries.
        """
        spec = _data_actions.list_combo_activity_spec(
            user=self._user_or_wallet(user), condition_id=condition_id
        )
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

    async def get_midpoint(
        self, *, asset_id: str | None = None, token_id: str | None = None
    ) -> Decimal:
        """Get the midpoint price for a CLOB asset."""
        path, params = _clob_actions.build_midpoint_request(asset_id=asset_id, token_id=token_id)
        return _clob_actions.parse_midpoint(await self._ctx.clob.get_json(path, params=params))

    async def get_midpoints(
        self,
        *,
        asset_ids: Sequence[str] | None = None,
        token_ids: Sequence[str] | None = None,
    ) -> dict[ClobAssetId, Decimal]:
        """Get midpoint prices for multiple CLOB assets."""
        path, body = _clob_actions.build_midpoints_request(asset_ids=asset_ids, token_ids=token_ids)
        return _clob_actions.parse_midpoints(await self._ctx.clob.post_json(path, json=body))

    async def get_price(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
        side: OrderSide,
    ) -> Decimal:
        """Get the executable price for a CLOB asset side."""
        path, params = _clob_actions.build_price_request(
            asset_id=asset_id, token_id=token_id, side=side
        )
        return _clob_actions.parse_price(await self._ctx.clob.get_json(path, params=params))

    async def get_prices(
        self, *, requests: Sequence[PriceRequest]
    ) -> dict[ClobAssetId, dict[OrderSide, Decimal]]:
        """Get executable prices for multiple CLOB asset-side requests."""
        path, body = _clob_actions.build_prices_request(requests=requests)
        return _clob_actions.parse_prices(await self._ctx.clob.post_json(path, json=body))

    async def get_order_book(
        self, *, asset_id: str | None = None, token_id: str | None = None
    ) -> OrderBook:
        """Get the order book for a CLOB asset."""
        path, params = _clob_actions.build_order_book_request(asset_id=asset_id, token_id=token_id)
        return _clob_actions.parse_order_book(await self._ctx.clob.get_json(path, params=params))

    async def get_order_books(
        self,
        *,
        asset_ids: Sequence[str] | None = None,
        token_ids: Sequence[str] | None = None,
    ) -> tuple[OrderBook, ...]:
        """Get order books for multiple CLOB assets."""
        path, body = _clob_actions.build_order_books_request(
            asset_ids=asset_ids, token_ids=token_ids
        )
        return _clob_actions.parse_order_books(await self._ctx.clob.post_json(path, json=body))

    async def get_spread(
        self, *, asset_id: str | None = None, token_id: str | None = None
    ) -> Decimal:
        """Get the bid-ask spread for a CLOB asset."""
        path, params = _clob_actions.build_spread_request(asset_id=asset_id, token_id=token_id)
        return _clob_actions.parse_spread(await self._ctx.clob.get_json(path, params=params))

    async def get_spreads(
        self,
        *,
        asset_ids: Sequence[str] | None = None,
        token_ids: Sequence[str] | None = None,
    ) -> dict[ClobAssetId, Decimal]:
        """Get bid-ask spreads for multiple CLOB assets."""
        path, body = _clob_actions.build_spreads_request(asset_ids=asset_ids, token_ids=token_ids)
        return _clob_actions.parse_spreads(await self._ctx.clob.post_json(path, json=body))

    async def get_last_trade_price(
        self, *, asset_id: str | None = None, token_id: str | None = None
    ) -> LastTradePrice | None:
        """Get the most recent trade price for a CLOB asset.

        Returns ``None`` when the CLOB asset has not traded.
        """
        path, params = _clob_actions.build_last_trade_price_request(
            asset_id=asset_id, token_id=token_id
        )
        return _clob_actions.parse_last_trade_price(
            await self._ctx.clob.get_json(path, params=params)
        )

    async def get_last_trade_prices(
        self,
        *,
        asset_ids: Sequence[str] | None = None,
        token_ids: Sequence[str] | None = None,
    ) -> tuple[LastTradePriceForAsset, ...]:
        """Get the most recent trade prices for multiple CLOB assets.

        Assets without trades are omitted. Match returned entries by ``asset_id``;
        the result is not positionally aligned with ``asset_ids``.
        """
        path, body = _clob_actions.build_last_trade_prices_request(
            asset_ids=asset_ids, token_ids=token_ids
        )
        return _clob_actions.parse_last_trade_prices(
            await self._ctx.clob.post_json(path, json=body)
        )

    async def get_price_history(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
        fidelity: int | None = None,
        interval: PriceHistoryInterval | None = None,
    ) -> tuple[PriceHistoryPoint, ...]:
        """Get historical price points for a CLOB asset."""
        path, params = _clob_actions.build_price_history_request(
            asset_id=asset_id,
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

    async def delete_api_key(self) -> None:
        """Delete the API key currently used by this client."""
        await _auth_actions.delete_api_key(self._ctx.secure_clob)

    async def create_builder_api_key(self) -> BuilderApiKey:
        """Create a new builder API key for the authenticated account."""
        return await _auth_actions.create_builder_api_key(self._ctx.secure_clob)

    async def fetch_builder_api_keys(self) -> tuple[BuilderApiKeyInfo, ...]:
        """List the builder API keys for the authenticated account."""
        return await _auth_actions.fetch_builder_api_keys(self._ctx.secure_clob)

    async def revoke_builder_api_key(self) -> None:
        """Revoke the builder API key this client is configured with.

        The revocation is authenticated by the builder key itself, so the client must have been
        created with the key to revoke (``AsyncSecureClient.create(api_key=BuilderApiKey(...))``).
        """
        builder_key = self._ctx.api_key
        if not isinstance(builder_key, BuilderApiKey):
            raise UserInputError(
                "revoke_builder_api_key requires a client created with the builder key to "
                "revoke (pass api_key=BuilderApiKey(...) to AsyncSecureClient.create)."
            )
        await _auth_actions.revoke_builder_api_key(self._ctx.clob, builder_key)

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
        asset_id: str | None = None,
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
                asset_id=asset_id, token_id=token_id, id=id, market=market, cursor=cursor
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
        asset_id: str | None = None,
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
                asset_id=asset_id,
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
        self,
        *,
        asset_type: AssetType,
        asset_id: str | None = None,
        token_id: str | None = None,
    ) -> BalanceAllowance:
        """Get balance and allowance information for an asset.

        Use ``COLLATERAL`` for collateral, ``CONDITIONAL`` for a CTF token ID,
        or ``CONDITIONAL-V2`` for a Polymarket V2 position ID.
        """
        path, params = _account_actions.build_balance_allowance_request(
            asset_type=asset_type,
            asset_id=asset_id,
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
        asset_id: str | None = None,
        token_id: str | None = None,
        side: Literal["BUY"],
        amount: Decimal | int | float | str,
        order_type: MarketOrderType = "FOK",
    ) -> Decimal: ...
    @overload
    async def estimate_market_price(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
        side: Literal["SELL"],
        shares: Decimal | int | float | str,
        order_type: MarketOrderType = "FOK",
    ) -> Decimal: ...
    async def estimate_market_price(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
        side: OrderSide,
        amount: Decimal | int | float | str | None = None,
        shares: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FOK",
    ) -> Decimal:
        """Estimate the limiting price level for a market order.

        BUY orders use ``amount`` as the spend amount. SELL orders use ``shares``
        as the number of shares to sell.
        """
        return await _estimate_market_price(
            self._ctx,
            asset_id=asset_id,
            token_id=token_id,
            side=side,
            amount=amount,
            shares=shares,
            order_type=order_type,
        )

    async def create_limit_order(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
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
        """
        params = validate_limit_order_params(
            asset_id=asset_id,
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
        asset_id: str | None = None,
        token_id: str | None = None,
        side: Literal["BUY"],
        amount: Decimal | int | float | str,
        max_spend: Decimal | int | float | str | None = None,
        max_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder: ...
    @overload
    async def create_market_order(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
        side: Literal["SELL"],
        shares: Decimal | int | float | str,
        min_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder: ...
    async def create_market_order(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
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
        """
        return await self._prepare_and_sign_market_order(
            asset_id=asset_id,
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

    async def _prepare_and_sign_market_order(
        self,
        *,
        asset_id: str | None,
        token_id: str | None,
        side: OrderSide,
        amount: Decimal | int | float | str | None = None,
        shares: Decimal | int | float | str | None = None,
        max_spend: Decimal | int | float | str | None = None,
        max_price: Decimal | int | float | str | None = None,
        min_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> SignedOrder:
        params = validate_market_order_params(
            asset_id=asset_id,
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
        draft = await prepare_market_order_draft(self._ctx, params)
        return await self._sign_order(draft, post_only=False)

    async def place_limit_order(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
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
        """
        signed = await self.create_limit_order(
            asset_id=asset_id,
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
        asset_id: str | None = None,
        token_id: str | None = None,
        side: Literal["BUY"],
        amount: Decimal | int | float | str,
        max_spend: Decimal | int | float | str | None = None,
        max_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> OrderResponse: ...
    @overload
    async def place_market_order(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
        side: Literal["SELL"],
        shares: Decimal | int | float | str,
        min_price: Decimal | int | float | str | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> OrderResponse: ...
    async def place_market_order(
        self,
        *,
        asset_id: str | None = None,
        token_id: str | None = None,
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
        """
        signed = await self._prepare_and_sign_market_order(
            asset_id=asset_id,
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

    async def get_trading_approvals_state(
        self, *, wallet: str | None = None
    ) -> TradingApprovalsState:
        """Get missing trading approvals for a wallet or the authenticated wallet."""
        return await get_trading_approvals_state(
            self._ctx.rpc,
            wallet=self._ctx.wallet if wallet is None else wallet,
            config=self._ctx.environment_config,
        )

    async def setup_trading_approvals(self) -> DeprecatedTransactionHandle:
        """Approve the standard set of trading allowances for the wallet.

        EOA wallets submit approvals directly. Gasless wallets submit a relayed
        transaction. Already-approved allowances are skipped, and the method waits
        internally for any submitted transactions.

        Returns:
            A deprecated compatibility handle whose ``wait()`` returns immediately.
        """
        state = await self.get_trading_approvals_state()
        calls = build_missing_trading_approval_calls(state.missing)
        if not calls:
            return DeprecatedTransactionHandle()
        if self._ctx.wallet_type == "EOA":
            for call in calls:
                handle = await self._broadcast_eoa_call(call)
                await handle.wait()
            return DeprecatedTransactionHandle()
        handle = await prepare_gasless_transaction(
            self._ctx, calls=calls, metadata="Trading setup approvals"
        )
        await handle.wait()
        return DeprecatedTransactionHandle()

    async def setup_gasless_wallet(self) -> Self:
        """Return this client.

        Deprecated. Secure client creation now sets up the wallet required for
        the selected trading flow.
        """
        return self

    async def is_gasless_ready(self) -> bool:
        """Return True.

        Deprecated. Secure client creation now performs the required wallet setup.
        """
        return True

    async def execute_transaction(
        self,
        *,
        calls: Sequence[TransactionCall],
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Submit one or more transaction calls for the authenticated wallet.

        Use this low-level escape hatch to combine supported transaction calls
        differently than the higher-level SDK workflows. Calls are executed in order.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
        """
        return await self._dispatch_calls(
            list(calls), metadata=metadata if metadata is not None else "Execute transaction"
        )

    async def _broadcast_eoa_call(self, call: TransactionCall) -> EoaTransactionHandle:
        return await broadcast_eoa_call(
            rpc=self._ctx.rpc,
            signer=self._ctx.signer,
            call=call,
            chain_id=self._ctx.environment_config.chain_id,
            max_polls=self._ctx.environment_config.relayer_max_polls,
            poll_delay_s=self._ctx.environment_config.relayer_poll_frequency_ms / 1000,
        )

    async def _dispatch_single_call(
        self, call: TransactionCall, *, metadata: str
    ) -> TransactionHandle:
        if self._ctx.wallet_type == "EOA":
            return await self._broadcast_eoa_call(call)
        return await prepare_gasless_transaction(self._ctx, calls=[call], metadata=metadata)

    async def _dispatch_calls(
        self, calls: list[TransactionCall], *, metadata: str
    ) -> TransactionHandle:
        if not calls:
            raise UserInputError("At least one transaction call is required")
        if self._ctx.wallet_type == "EOA":
            for call in calls[:-1]:
                handle = await self._broadcast_eoa_call(call)
                await handle.wait()
            return await self._broadcast_eoa_call(calls[-1])
        return await prepare_gasless_transaction(self._ctx, calls=calls, metadata=metadata)

    async def _ensure_wallet_ready(self) -> Self:
        ctx = self._ctx
        if ctx.wallet_type == "EOA":
            return self
        deployed = await fetch_deployed(
            ctx.relayer,
            address=str(ctx.wallet),
            type=_relayer_transaction_type_for_wallet(ctx.wallet_type),
        )
        if deployed:
            return self
        if ctx.wallet_type == "DEPOSIT_WALLET":
            await self._deploy_default_deposit_wallet()
            return self
        raise UserInputError(
            f"Wallet {ctx.wallet} does not exist. Provide an existing wallet address, "
            "or omit wallet to use the default Deposit Wallet flow."
        )

    async def _deploy_default_deposit_wallet(self) -> None:
        ctx = self._ctx
        current_deposit_wallet = derive_beacon_deposit_wallet_address(
            ctx.signer.address, ctx.environment_config.wallet_derivation
        )
        if str(ctx.wallet).lower() != current_deposit_wallet.lower():
            raise UserInputError(
                f"Wallet {ctx.wallet} does not match the expected Deposit Wallet "
                f"{current_deposit_wallet} for this signer, nor a deployed wallet address."
            )
        handle = await submit_deposit_wallet_create(ctx, metadata="Deploy Deposit Wallet")
        await handle.wait()

    async def split_position(
        self,
        *,
        condition_id: str | None = None,
        legs: Sequence[str] | None = None,
        amount: int,
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Split collateral into market or combo positions.

        Provide exactly one of ``condition_id`` for market positions or ``legs``
        for combo positions.

        Args:
            amount: Base-units collateral amount to split.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
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
            return await self._dispatch_calls(calls, metadata=resolved_metadata)
        assert condition_id is not None
        context = await self._resolve_market_position_context(condition_id=condition_id)
        if context.protocol == "ctf":
            assert context.adapter_address is not None
            call = split_position_call(
                target=context.adapter_address,
                collateral=cast(EvmAddress, self._ctx.environment_config.collateral_token),
                condition_id=context.condition_id,
                amount=amount,
            )
        else:
            call = split_v2_call(
                router=cast(EvmAddress, self._ctx.environment_config.protocol_v2_router),
                condition_id=context.condition_id,
                amount=amount,
            )
        resolved_metadata = (
            metadata
            if metadata is not None
            else f"Split {amount} positions for condition {context.condition_id}"
        )
        return await self._dispatch_single_call(call, metadata=resolved_metadata)

    async def merge_positions(
        self,
        *,
        condition_id: str | None = None,
        legs: Sequence[str] | None = None,
        amount: int | Literal["max"],
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Merge market or combo positions back into collateral.

        Provide exactly one of ``condition_id`` for market positions or ``legs``
        for combo positions.

        Args:
            amount: Base-units position amount to merge, or ``"max"`` to merge
                the largest available balanced amount.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
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
                await self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
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
            return await self._dispatch_calls(calls, metadata=resolved_metadata)
        assert condition_id is not None
        context = await self._resolve_market_position_context(condition_id=condition_id)
        balance_call = erc1155_balance_of_batch_call(
            token_address=context.position_erc1155_address,
            owners=[self._ctx.wallet, self._ctx.wallet],
            token_ids=[str(token_id) for token_id in context.token_ids],
        )
        balances = decode_erc1155_balance_of_batch_result(
            await self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
        )
        resolved_amount = resolve_merge_amount_from_balances(context.condition_id, balances, amount)
        if context.protocol == "ctf":
            assert context.adapter_address is not None
            call = merge_positions_call(
                target=context.adapter_address,
                collateral=cast(EvmAddress, self._ctx.environment_config.collateral_token),
                condition_id=context.condition_id,
                amount=resolved_amount,
            )
        else:
            call = merge_v2_call(
                router=cast(EvmAddress, self._ctx.environment_config.protocol_v2_router),
                condition_id=context.condition_id,
                amount=resolved_amount,
            )
        resolved_metadata = (
            metadata
            if metadata is not None
            else f"Merge {resolved_amount} positions for condition {context.condition_id}"
        )
        return await self._dispatch_single_call(call, metadata=resolved_metadata)

    async def merge_multiple_positions(
        self,
        *,
        positions: Sequence[MergePositionRequest],
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Merge multiple market positions or Polymarket V2 positions into collateral.

        Args:
            positions: Position merge requests. Use ``position_id`` for a
                Polymarket V2 position, or ``condition_id`` / ``market_id`` for
                market positions. Do not mix identifier styles in the same batch.
                Omit ``amount`` or pass ``"max"`` to merge the largest available
                balanced amount for that condition.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.
        """
        if not positions:
            raise UserInputError("positions must include at least one merge request")

        normalized = [
            normalize_batch_merge_position_request(cast(Mapping[str, object], position))
            for position in positions
        ]
        batch_kinds = {position.kind for position in normalized}
        if len(batch_kinds) != 1:
            raise UserInputError("Cannot mix market and Polymarket V2 positions in one merge batch")

        seen_conditions: set[str] = set()
        calls: list[TransactionCall] = []
        for position in normalized:
            if position.kind == "combo":
                assert position.position_id is not None
                decoded = decode_combo_outcome_position_id(position.position_id)
                condition_key = str(decoded.condition_id)
                if condition_key in seen_conditions:
                    raise UserInputError(
                        "position_ids must reference distinct Polymarket V2 conditions"
                    )
                seen_conditions.add(condition_key)
                token_ids = derive_combo_outcome_position_ids(decoded.condition_id)
                balance_call = erc1155_balance_of_batch_call(
                    token_address=cast(EvmAddress, self._ctx.environment_config.position_manager),
                    owners=[self._ctx.wallet, self._ctx.wallet],
                    token_ids=list(token_ids),
                )
                balances = decode_erc1155_balance_of_batch_result(
                    await self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
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

            context = await self._resolve_market_position_context(
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
                await self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
            )
            resolved_amount = resolve_merge_amount_from_balances(
                context.condition_id, balances, position.amount
            )
            if context.protocol == "ctf":
                assert context.adapter_address is not None
                calls.append(
                    merge_positions_call(
                        target=context.adapter_address,
                        collateral=cast(EvmAddress, self._ctx.environment_config.collateral_token),
                        condition_id=context.condition_id,
                        amount=resolved_amount,
                    )
                )
            else:
                calls.append(
                    merge_v2_call(
                        router=cast(EvmAddress, self._ctx.environment_config.protocol_v2_router),
                        condition_id=context.condition_id,
                        amount=resolved_amount,
                    )
                )

        batch_label = "Polymarket V2 positions" if "combo" in batch_kinds else "positions"
        resolved_metadata = (
            metadata if metadata is not None else f"Merge {len(calls)} {batch_label}"
        )
        return await self.execute_transaction(calls=calls, metadata=resolved_metadata)

    @overload
    async def redeem_positions(
        self, *, condition_id: str, metadata: str | None = None
    ) -> TransactionHandle: ...
    @overload
    async def redeem_positions(
        self, *, market_id: str, metadata: str | None = None
    ) -> TransactionHandle: ...
    @overload
    async def redeem_positions(
        self, *, position_id: str, metadata: str | None = None
    ) -> TransactionHandle: ...
    async def redeem_positions(
        self,
        *,
        condition_id: str | None = None,
        market_id: str | None = None,
        position_id: str | None = None,
        metadata: str | None = None,
    ) -> TransactionHandle:
        """Redeem resolved market positions or a Polymarket V2 position.

        Provide exactly one of ``condition_id``, ``market_id``, or ``position_id``.
        A ``position_id`` identifies a specific Polymarket V2 YES/NO position.

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.

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
                await self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
            )
            if balance == 0:
                raise UserInputError("Position has no balance to redeem")
            call = redeem_v2_call(
                router=cast(EvmAddress, self._ctx.environment_config.protocol_v2_router),
                condition_id=decoded.condition_id,
                outcome_index=decoded.outcome_index,
                amount=balance,
            )
            resolved_metadata = (
                metadata if metadata is not None else f"Redeem position {position_id}"
            )
            return await self._dispatch_single_call(call, metadata=resolved_metadata)
        context = await self._resolve_market_position_context(
            condition_id=condition_id,
            market_id=market_id,
            closed=True,
        )
        if context.protocol == "ctf":
            assert context.adapter_address is not None
            calls = [
                ctf_redeem_positions_call(
                    ctf=context.adapter_address,
                    collateral=cast(EvmAddress, self._ctx.environment_config.collateral_token),
                    condition_id=context.condition_id,
                )
            ]
        else:
            balance_call = erc1155_balance_of_batch_call(
                token_address=context.position_erc1155_address,
                owners=[self._ctx.wallet, self._ctx.wallet],
                token_ids=[str(asset_id) for asset_id in context.outcome_ids],
            )
            balances = decode_erc1155_balance_of_batch_result(
                await self._ctx.rpc.eth_call(to=str(balance_call.to), data=balance_call.data)
            )
            if len(balances) != 2:
                raise UnexpectedResponseError("Expected two position balances")
            calls = [
                redeem_v2_call(
                    router=cast(EvmAddress, self._ctx.environment_config.protocol_v2_router),
                    condition_id=context.condition_id,
                    outcome_index=outcome_index,
                    amount=balance,
                )
                for outcome_index, balance in enumerate(balances)
                if balance > 0
            ]
            if not calls:
                raise UserInputError(
                    f"Market positions have no balance to redeem for condition "
                    f"{context.condition_id}"
                )
        resolved_metadata = (
            metadata
            if metadata is not None
            else f"Redeem positions for condition {context.condition_id}"
        )
        return await self._dispatch_calls(calls, metadata=resolved_metadata)

    async def plan_collateral_return(self) -> CollateralReturnPlanResponse:
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
        return await _combos_actions.plan_collateral_return(self._ctx)

    async def execute_collateral_return_plan(
        self, *, plan: CollateralReturnPlanResponse
    ) -> GaslessTransactionHandle:
        """Execute a collateral return plan.

        The plan executes exactly as returned by
        :meth:`plan_collateral_return`; nothing is recomputed client-side.
        No approval transactions are submitted implicitly.

        Example::

            plan = await client.plan_collateral_return()
            while plan.net_pusd_out > 0:
                handle = await client.execute_collateral_return_plan(plan=plan)
                await handle.wait()
                if not plan.truncated:
                    break
                plan = await client.plan_collateral_return()

        Returns:
            A transaction handle. Await ``wait()`` to wait for a terminal outcome.

        Raises:
            RequestRejectedError: With ``status`` 409 if the plan no longer
                matches current wallet state; request a fresh plan and
                execute that instead.
        """
        return await _combos_actions.execute_collateral_return_plan(self._ctx, plan=plan)

    async def request_combo_quote(
        self,
        *,
        leg_position_ids: list[str] | tuple[str, ...],
        direction: RfqDirection | str,
        amount: Decimal | int | float | str | None = None,
        size: Decimal | int | float | str | None = None,
        side: RfqSide | str = RfqSide.YES,
    ) -> ComboQuoteResult:
        """Request a quote for a combo of positions.

        BUY requests are sized in collateral via ``amount``; SELL requests
        are sized in outcome tokens via ``size``. Amounts are human-readable:
        ``1`` means one dollar or one full share, not one 6-decimal base
        unit. Requires a Builder API Key passed as ``api_key=`` when
        constructing the client.

        The call resolves when the quote competition window closes. A request
        that attracts no usable quotes is a normal outcome, returned with
        ``quote=None`` and a ``reason`` rather than raised.

        Returns:
            The quote result. Pass ``result.quote`` to
            :meth:`accept_combo_quote` to
            execute the winning quote before ``quote.expires_at``.

        Raises:
            UserInputError: If the legs, direction/sizing pair, or side are
                invalid, or the client has no Builder API Key.
            RfqRequestRejectedError: If the request is rejected; inspect
                ``code`` to distinguish permanent input problems from
                transient conditions.
        """
        return await _combo_rfq_actions.request_combo_quote(
            self._ctx,
            leg_position_ids=leg_position_ids,
            direction=direction,
            amount=amount,
            size=size,
            side=side,
        )

    async def accept_combo_quote(
        self, quote: ComboQuote | Mapping[str, object]
    ) -> ComboQuoteAcceptance:
        """Accept a self-contained combo quote and sign its order automatically.

        The call resolves at the maker last-look outcome. A maker declining
        or the acceptance window expiring is a normal outcome returned with
        ``status="failed"`` and a ``reason``. ``status="executing"`` means
        the trade was handed off for onchain execution; follow it with
        :meth:`wait_for_combo_fill`.

        A retry after an interrupted request or invalid response is safe: an
        already-accepted RFQ reports its current status instead of executing
        twice. In that case ``taker_order_hash`` is ``None`` because the
        retry's order was not the one recorded.

        Quotes can be persisted with ``quote.model_dump_json()`` and restored
        with ``ComboQuote.model_validate_json(...)``. A JSON-decoded mapping is
        also accepted directly. The accepting client must represent the same
        account and builder identity used to request the quote. Treat restored
        quote fields as signing-sensitive data and do not accept values modified
        by an untrusted client.

        Returns:
            The acceptance outcome.

        Raises:
            UserInputError: If the quote is invalid or the client has no
                Builder API Key.
            RfqRequestRejectedError: If the acceptance is rejected.
            TimeoutError: If the outcome is still pending after the wait
                window; resume with :meth:`fetch_rfq_status`.
        """
        return await _combo_rfq_actions.accept_combo_quote(self._ctx, quote)

    async def wait_for_combo_fill(
        self,
        *,
        rfq_id: str,
        timeout: float = 30.0,
        polling_interval: float = 1.0,
    ) -> ComboFillResult:
        """Wait for an accepted RFQ to reach a terminal state.

        Polls the RFQ status until it is filled (or confirmed onchain),
        failed, expired, or canceled. Terminal failure is a normal outcome
        and is returned, not raised.

        Returns:
            The terminal state. ``tx_hash`` is set when the RFQ filled.

        Raises:
            TimeoutError: If the RFQ stays non-terminal past ``timeout``
                seconds. This does not mean the trade failed; resume with
                :meth:`fetch_rfq_status`.
            RfqRequestRejectedError: If the RFQ is unknown or not accepted.
        """
        return await _combo_rfq_actions.wait_for_combo_fill(
            self._ctx, rfq_id=rfq_id, timeout=timeout, polling_interval=polling_interval
        )

    async def fetch_rfq_status(self, *, rfq_id: str) -> RfqStatusResult:
        """Fetch the status of an accepted RFQ.

        Status is available once an acceptance has been recorded; earlier
        reads are rejected.

        Returns:
            The RFQ status. Onchain execution progress is merged into
            ``status``.

        Raises:
            RfqRequestRejectedError: If the RFQ is unknown or not accepted.
        """
        return await _combo_rfq_actions.fetch_rfq_status(self._ctx, rfq_id=rfq_id)

    async def _resolve_market_position_context(
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
                page = await self.list_markets(
                    condition_ids=[condition_id], page_size=1
                ).first_page()
            else:
                page = await self.list_markets(
                    condition_ids=[condition_id], closed=closed, page_size=1
                ).first_page()
        else:
            assert market_id is not None
            context = f"market {market_id}"
            if closed is None:
                page = await self.list_markets(
                    ids=[parse_market_id(market_id)], page_size=1
                ).first_page()
            else:
                page = await self.list_markets(
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
            position_manager=cast(EvmAddress, self._ctx.environment_config.position_manager),
        )

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

    async def wait_for_order_fill_settlement(
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
        return await _settlement_actions.wait_for_order_fill_settlement(
            self._ctx.secure_clob, order, timeout_s=timeout_s
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
        self,
        *,
        market: str | None = None,
        asset_id: str | None = None,
        token_id: str | None = None,
    ) -> CancelOrdersResponse:
        """Cancel open orders matching a market or CLOB asset filter."""
        path, body = _cancel_actions.build_cancel_market_orders_request(
            market=market,
            asset_id=asset_id,
            token_id=token_id,
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
        final_signature = wrap_deposit_wallet_signature(
            signer=self._ctx.signer.address,
            signer_type=self._ctx.signer_type,
            signature=build_order_signature(unsigned, signature_hex),
        )
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
                condition_id=CtfConditionId(condition_id), sponsored=sponsored, cursor=cursor
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

    async def fetch_perps_instruments(
        self,
        *,
        instrument_id: int | None = None,
        category: PerpsInstrumentCategory | None = None,
    ) -> tuple[PerpsInstrument, ...]:
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        Fetch Perps instruments, optionally filtered by instrument or category.
        """
        return await _perps_actions.fetch_instruments(
            self._ctx.perps, instrument_id=instrument_id, category=category
        )

    async def fetch_perps_ticker(self, *, instrument_id: int) -> PerpsTicker:
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        Fetch the current Perps ticker for an instrument.
        """
        return await _perps_actions.fetch_ticker(self._ctx.perps, instrument_id=instrument_id)

    async def fetch_perps_tickers(
        self, *, instrument_id: int | None = None
    ) -> tuple[PerpsTicker, ...]:
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        Fetch current Perps tickers.
        """
        return await _perps_actions.fetch_tickers(self._ctx.perps, instrument_id=instrument_id)

    async def fetch_perps_book(
        self, *, instrument_id: int, depth: PerpsBookDepth = 100
    ) -> PerpsBook:
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        Fetch a Perps order book snapshot.

        ``depth`` controls the number of price levels returned on each side.
        """
        return await _perps_actions.fetch_book(
            self._ctx.perps, instrument_id=instrument_id, depth=depth
        )

    async def fetch_perps_fees(self) -> tuple[PerpsFeeScheduleEntry, ...]:
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        Fetch the Perps fee schedule.
        """
        return await _perps_actions.fetch_fees(self._ctx.perps)

    def list_perps_candles(
        self,
        *,
        instrument_id: int,
        interval: PerpsKlineInterval,
        start: "datetime | int | None" = None,
        end: "datetime | int | None" = None,
    ) -> AsyncPaginator[PerpsCandle]:
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        List Perps candles for an instrument with SDK-owned pagination.

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
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        List Perps funding-rate history with SDK-owned pagination.

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
        """Experimental: This API may change in a breaking way in any release,
        including patch releases.

        List recent public Perps trades with SDK-owned pagination.

        Defaults to the past 24 hours when ``start`` is omitted. ``start`` and
        ``end`` accept a ``datetime`` or an epoch-milliseconds int.

        Returns:
            An async paginator over matching trades.
        """
        return _perps_actions.list_trades(
            self._ctx.perps, instrument_id=instrument_id, start=start, end=end
        )


def _validate_nonce(nonce: object) -> None:
    if isinstance(nonce, bool) or not isinstance(nonce, int):
        raise UserInputError("nonce must be a non-negative integer.")
    if nonce < 0:
        raise UserInputError("nonce must be a non-negative integer.")


async def _close_all(*resources: AsyncCloseable | None) -> None:
    first_error: BaseException | None = None

    for resource in resources:
        if resource is None:
            continue
        try:
            await resource.close()
        except BaseException as error:
            if first_error is None:
                first_error = error

    if first_error is not None:
        raise first_error


async def _bootstrap_credentials(
    *,
    config: EnvironmentConfig,
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
    return await _auth_actions.create_or_derive_api_key(clob, signature)


async def _resolve_requested_wallet(
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
    relayer = AsyncTransport(base_url=config.relayer_url, logger=logger)
    try:
        if await fetch_deployed(
            relayer,
            address=legacy_deposit_wallet,
            type=RelayerTransactionType.WALLET,
        ):
            return legacy_deposit_wallet
        return derive_beacon_deposit_wallet_address(signer.address, config.wallet_derivation)
    finally:
        await relayer.close()


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


async def _credentials_are_active(
    *,
    config: EnvironmentConfig,
    signer: LocalAccount,
    credentials: ApiKeyCreds,
    logger: logging.Logger | None,
) -> bool:
    probe = AsyncTransport(
        base_url=config.clob_url,
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


def _make_builder_gateway_header_resolver(
    api_key: ApiKey | None, signer: LocalAccount, credentials: ApiKeyCreds
) -> _L2HeaderResolver:
    l2_resolver = _make_l2_header_resolver(signer, credentials)

    async def resolver(method: str, path: str, body: str | None) -> Mapping[str, str]:
        headers = dict(await l2_resolver(method, path, body))
        # Status reads authenticate with account headers only; builder
        # headers are required on the mutating requests.
        if method != "GET" and isinstance(api_key, BuilderApiKey):
            headers.update(
                build_builder_key_headers(creds=api_key, method=method, path=path, body=body)
            )
        return headers

    return resolver


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
