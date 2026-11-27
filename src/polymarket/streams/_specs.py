# pyright: reportUnnecessaryIsInstance=false
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias, TypeVar

from polymarket.errors import UserInputError
from polymarket.models.price_events import KnownPriceSource

_EQUITY_EVENT_TYPES: frozenset[str] = frozenset({"update", "subscribe"})
_PERPS_CANDLE_INTERVALS: frozenset[str] = frozenset({"1m", "5m", "15m", "1h", "4h", "1d", "1w"})


def _validate_perps_instrument_id(instrument_id: object, *, optional: bool = False) -> None:
    if instrument_id is None and optional:
        return
    if isinstance(instrument_id, bool) or not isinstance(instrument_id, int):
        raise UserInputError("instrument_id must be an int")
    if instrument_id < 0:
        raise UserInputError("instrument_id must be non-negative")


EquityPricesEventType = Literal["update", "subscribe"]
PriceProviderInput: TypeAlias = (
    Literal["chainlink", "pyth", "binance"]
    | Literal[KnownPriceSource.CHAINLINK, KnownPriceSource.PYTH, KnownPriceSource.BINANCE]
)


def _normalize_price_provider(provider: PriceProviderInput | None) -> PriceProviderInput | None:
    if provider is None:
        return None
    if isinstance(provider, str):
        if provider == "chainlink":
            return "chainlink"
        if provider == "pyth":
            return "pyth"
        if provider == "binance":
            return "binance"
    raise UserInputError("provider must be 'chainlink', 'pyth' or 'binance'")


def _validate_price_api_key(provider_api_key: str | None) -> None:
    if provider_api_key is None:
        return
    if not isinstance(provider_api_key, str):
        raise UserInputError("provider_api_key must be a string")


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class MarketSpec:
    """Subscribe to realtime market updates for one or more CLOB asset IDs.

    Set ``custom_feature_enabled=True`` to additionally receive
    ``MarketBestBidAskEvent``, ``NewMarketEvent``, and ``MarketResolvedEvent``.
    """

    asset_ids: Sequence[str]
    """Asset IDs whose market events should be delivered."""
    custom_feature_enabled: bool = False
    """Whether to enable top-of-book and market lifecycle events."""
    topic: Literal["market"] = field(default="market", init=False)

    def __init__(
        self,
        *,
        asset_ids: Sequence[str] | None = None,
        token_ids: Sequence[str] | None = None,
        custom_feature_enabled: bool = False,
    ) -> None:
        if asset_ids is not None and token_ids is not None:
            raise UserInputError("asset_ids and token_ids are mutually exclusive")
        values = asset_ids if asset_ids is not None else token_ids
        if values is None:
            raise UserInputError("Provide exactly one of asset_ids or token_ids")
        if not isinstance(custom_feature_enabled, bool):
            raise UserInputError("custom_feature_enabled must be a bool")
        if isinstance(values, str | bytes):
            raise UserInputError("asset_ids must be a sequence of asset ids, not a single string")
        normalized: list[str] = []
        for asset_id in values:
            if not isinstance(asset_id, str):
                raise UserInputError(f"asset_id must be a string, got {type(asset_id).__name__}")
            if not asset_id:
                raise UserInputError("asset_id must be non-empty")
            normalized.append(asset_id)
        if not normalized:
            raise UserInputError("asset_ids must be a non-empty sequence")
        object.__setattr__(self, "asset_ids", tuple(normalized))
        object.__setattr__(self, "custom_feature_enabled", custom_feature_enabled)
        object.__setattr__(self, "topic", "market")

    @property
    def token_ids(self) -> Sequence[str]:
        """Deprecated alias for :attr:`asset_ids`."""

        return self.asset_ids


@dataclass(frozen=True, slots=True, kw_only=True)
class SportsSpec:
    """Subscription for the Sports stream.

    Sports has no per-subscription filtering — every subscriber receives
    every event the server broadcasts.
    """

    topic: Literal["sports"] = field(default="sports", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class UserSpec:
    """Subscribe to authenticated user order and trade events.

    When ``markets`` is omitted, the subscription receives user events for all
    markets available to the authenticated account.
    """

    markets: Sequence[str] | None = None
    topic: Literal["user"] = field(default="user", init=False)

    def __post_init__(self) -> None:
        if self.markets is None:
            return
        if isinstance(self.markets, str | bytes):
            raise UserInputError("markets must be a sequence of market ids, not a single string")
        normalized: list[str] = []
        for m in self.markets:
            if isinstance(m, bool) or not isinstance(m, str):
                raise UserInputError(f"market must be a string, got {type(m).__name__}")
            if not m:
                raise UserInputError("market must be non-empty")
            normalized.append(m)
        object.__setattr__(self, "markets", tuple(normalized) if normalized else None)


@dataclass(frozen=True, slots=True, kw_only=True)
class PerpsTradesSpec:
    """Experimental: This API may change in a breaking way in any release,
    including patch releases.

    Subscribe to public trades for one Perps instrument.
    """

    instrument_id: int
    topic: Literal["perps.trades"] = field(default="perps.trades", init=False)

    def __post_init__(self) -> None:
        _validate_perps_instrument_id(self.instrument_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class PerpsBboSpec:
    """Experimental: This API may change in a breaking way in any release,
    including patch releases.

    Subscribe to best bid/ask updates for one Perps instrument.
    """

    instrument_id: int
    topic: Literal["perps.bbo"] = field(default="perps.bbo", init=False)

    def __post_init__(self) -> None:
        _validate_perps_instrument_id(self.instrument_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class PerpsBookSpec:
    """Experimental: This API may change in a breaking way in any release,
    including patch releases.

    Subscribe to order book deltas for one Perps instrument.
    """

    instrument_id: int
    topic: Literal["perps.book"] = field(default="perps.book", init=False)

    def __post_init__(self) -> None:
        _validate_perps_instrument_id(self.instrument_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class PerpsCandlesSpec:
    """Experimental: This API may change in a breaking way in any release,
    including patch releases.

    Subscribe to streaming candles for one Perps instrument and interval.
    """

    instrument_id: int
    interval: Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
    topic: Literal["perps.candles"] = field(default="perps.candles", init=False)

    def __post_init__(self) -> None:
        _validate_perps_instrument_id(self.instrument_id)
        if self.interval not in _PERPS_CANDLE_INTERVALS:
            raise UserInputError(
                f"interval must be one of {sorted(_PERPS_CANDLE_INTERVALS)}, got {self.interval!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class PerpsTickersSpec:
    """Experimental: This API may change in a breaking way in any release,
    including patch releases.

    Subscribe to ticker updates for one Perps instrument or all instruments.

    When ``instrument_id`` is omitted, the subscription receives ticker
    updates for every instrument.
    """

    instrument_id: int | None = None
    topic: Literal["perps.tickers"] = field(default="perps.tickers", init=False)

    def __post_init__(self) -> None:
        _validate_perps_instrument_id(self.instrument_id, optional=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class PerpsStatisticsSpec:
    """Experimental: This API may change in a breaking way in any release,
    including patch releases.

    Subscribe to statistics updates for one Perps instrument or all instruments.

    When ``instrument_id`` is omitted, the subscription receives statistics
    updates for every instrument.
    """

    instrument_id: int | None = None
    topic: Literal["perps.statistics"] = field(default="perps.statistics", init=False)

    def __post_init__(self) -> None:
        _validate_perps_instrument_id(self.instrument_id, optional=True)


def _normalize_price_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(symbols, Sequence) or isinstance(symbols, str | bytes) or not symbols:
        raise UserInputError("symbols must be a non-empty sequence of canonical USD pairs")
    for symbol in symbols:
        if (
            not isinstance(symbol, str)
            or len(symbol) > 64
            or re.fullmatch(r"[a-z0-9]+usd", symbol) is None
        ):
            raise UserInputError(
                "Use canonical lowercase USD pairs such as btcusd; slash and USDT pairs "
                "are not supported"
            )
    return tuple(dict.fromkeys(symbols))


def _normalize_equity_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise UserInputError("symbol must be a string")
    symbol = symbol.strip()
    if not 1 <= len(symbol) <= 64 or re.fullmatch(r"[a-zA-Z0-9._:/-]+", symbol) is None:
        raise UserInputError("symbol must contain 1 to 64 supported symbol characters")
    return symbol.lower()


@dataclass(frozen=True, slots=True, kw_only=True)
class CryptoPriceSpec:
    """Subscribe to authenticated USD crypto prices and recent history.

    Use explicit canonical lowercase symbols such as ``btcusd`` and ``ethusd``.
    Requires ``AsyncSecureClient``; subscription waits for server acceptance.

    Set ``provider="binance"`` for Binance USDT spot closes under USD symbols.
    Omit the provider to follow the default. An unavailable pin may fall back;
    check the payload ``source`` for the provider actually serving prices.
    """

    symbols: Sequence[str]
    provider: PriceProviderInput | None = None
    """Optional provider preference. Check payload ``source`` for the actual source."""
    provider_api_key: str | None = field(default=None, repr=False)
    """Chainlink API key. Used only with ``provider="chainlink"``; ignored otherwise."""
    topic: Literal["prices.crypto"] = field(default="prices.crypto", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _normalize_price_symbols(self.symbols))
        object.__setattr__(self, "provider", _normalize_price_provider(self.provider))
        _validate_price_api_key(self.provider_api_key)


@dataclass(frozen=True, slots=True, kw_only=True)
class CryptoTwapPriceSpec:
    """Subscribe to authenticated 60-second USD crypto TWAPs and recent history.

    Use explicit canonical lowercase USD pairs such as ``btcusd``.
    The averaging window is fixed at 60 seconds. Requires ``AsyncSecureClient``.
    """

    symbols: Sequence[str]
    provider: PriceProviderInput | None = None
    """Optional provider preference. Check payload ``source`` for the actual source."""
    provider_api_key: str | None = field(default=None, repr=False)
    """Chainlink API key. Used only with ``provider="chainlink"``; ignored otherwise."""
    topic: Literal["prices.crypto.twap"] = field(default="prices.crypto.twap", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _normalize_price_symbols(self.symbols))
        object.__setattr__(self, "provider", _normalize_price_provider(self.provider))
        _validate_price_api_key(self.provider_api_key)


@dataclass(frozen=True, slots=True, kw_only=True)
class EquityPriceSpec:
    """Subscribe to authenticated prices for one symbol, such as ``aapl`` or ``usdjpy``.

    Prices use the instrument's quote currency: ``usdjpy`` is JPY per USD and
    ``usdcad`` is CAD per USD.
    Symbols are trimmed and lowercased. Omitted or empty ``types`` receives both
    history (``subscribe``) and live (``update``) events. Requires ``AsyncSecureClient``.
    """

    symbol: str
    types: Sequence[EquityPricesEventType] | None = None
    provider: PriceProviderInput | None = None
    """Optional provider preference. Check payload ``source`` for the actual source."""
    provider_api_key: str | None = field(default=None, repr=False)
    """Chainlink API key. Used only with ``provider="chainlink"``; ignored otherwise."""
    topic: Literal["prices.equity"] = field(default="prices.equity", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _normalize_equity_symbol(self.symbol))
        object.__setattr__(self, "provider", _normalize_price_provider(self.provider))
        _validate_price_api_key(self.provider_api_key)
        if self.types is not None:
            if (
                not isinstance(self.types, Sequence)
                or isinstance(self.types, str | bytes)
                or any(not isinstance(t, str) or t not in _EQUITY_EVENT_TYPES for t in self.types)
            ):
                raise UserInputError("types must be a sequence of 'update' or 'subscribe'")
            object.__setattr__(self, "types", tuple(self.types))


@dataclass(frozen=True, slots=True, kw_only=True)
class EquityTwapPriceSpec:
    """Subscribe to authenticated 60-second TWAPs for one symbol and recent history.

    Prices use the instrument's quote currency: ``usdjpy`` is JPY per USD.
    Symbols are trimmed and lowercased. The averaging window is fixed at 60 seconds.
    Requires ``AsyncSecureClient``; subscription waits for server acceptance.
    """

    symbol: str
    provider: PriceProviderInput | None = None
    """Optional provider preference. Check payload ``source`` for the actual source."""
    provider_api_key: str | None = field(default=None, repr=False)
    """Chainlink API key. Used only with ``provider="chainlink"``; ignored otherwise."""
    topic: Literal["prices.equity.twap"] = field(default="prices.equity.twap", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _normalize_equity_symbol(self.symbol))
        object.__setattr__(self, "provider", _normalize_price_provider(self.provider))
        _validate_price_api_key(self.provider_api_key)


PriceSpec = CryptoPriceSpec | CryptoTwapPriceSpec | EquityPriceSpec | EquityTwapPriceSpec
PerpsSpec = (
    PerpsTradesSpec
    | PerpsBboSpec
    | PerpsBookSpec
    | PerpsCandlesSpec
    | PerpsTickersSpec
    | PerpsStatisticsSpec
)
PublicSubscription = MarketSpec | SportsSpec | PerpsSpec
SecureSubscription = PublicSubscription | UserSpec | PriceSpec
Subscription = SecureSubscription


_SPEC_TYPES: tuple[type[Subscription], ...] = (
    CryptoPriceSpec,
    CryptoTwapPriceSpec,
    EquityPriceSpec,
    EquityTwapPriceSpec,
    MarketSpec,
    SportsSpec,
    PerpsTradesSpec,
    PerpsBboSpec,
    PerpsBookSpec,
    PerpsCandlesSpec,
    PerpsTickersSpec,
    PerpsStatisticsSpec,
    UserSpec,
)


_S = TypeVar("_S", bound=Subscription)


def normalize_specs(specs: _S | Sequence[_S]) -> list[_S]:
    if isinstance(specs, _SPEC_TYPES):
        return [specs]
    if not isinstance(specs, Sequence) or isinstance(specs, str | bytes):
        raise UserInputError("subscribe() expects a Subscription or a sequence of Subscriptions")
    items: list[_S] = []
    for spec in specs:
        if not isinstance(spec, _SPEC_TYPES):
            raise UserInputError(f"unsupported subscription type: {type(spec).__name__}")
        items.append(spec)
    if not items:
        raise UserInputError("subscribe() requires at least one subscription")
    return items


__all__ = [
    "CryptoPriceSpec",
    "CryptoTwapPriceSpec",
    "EquityPriceSpec",
    "EquityTwapPriceSpec",
    "PriceProviderInput",
    "PriceSpec",
    "PublicSubscription",
    "SecureSubscription",
    "EquityPricesEventType",
    "MarketSpec",
    "PerpsBboSpec",
    "PerpsBookSpec",
    "PerpsCandlesSpec",
    "PerpsSpec",
    "PerpsStatisticsSpec",
    "PerpsTickersSpec",
    "PerpsTradesSpec",
    "SportsSpec",
    "Subscription",
    "UserSpec",
    "normalize_specs",
]
