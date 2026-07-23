# pyright: reportUnnecessaryIsInstance=false
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeVar

from polymarket.errors import UserInputError

_COMMENT_EVENT_TYPES: frozenset[str] = frozenset(
    {"comment_created", "comment_removed", "reaction_created", "reaction_removed"}
)
_PARENT_ENTITY_TYPES: frozenset[str] = frozenset({"Event", "Market"})
_CRYPTO_PRICES_TOPICS: frozenset[str] = frozenset(
    {"prices.crypto.binance", "prices.crypto.chainlink"}
)
_EQUITY_EVENT_TYPES: frozenset[str] = frozenset({"update", "subscribe"})
_PERPS_CANDLE_INTERVALS: frozenset[str] = frozenset({"1m", "5m", "15m", "1h", "4h", "1d", "1w"})


def _validate_perps_instrument_id(instrument_id: object, *, optional: bool = False) -> None:
    if instrument_id is None and optional:
        return
    if isinstance(instrument_id, bool) or not isinstance(instrument_id, int):
        raise UserInputError("instrument_id must be an int")
    if instrument_id < 0:
        raise UserInputError("instrument_id must be non-negative")


CommentsEventType = Literal[
    "comment_created", "comment_removed", "reaction_created", "reaction_removed"
]
ParentEntityType = Literal["Event", "Market"]
CryptoPricesTopic = Literal["prices.crypto.binance", "prices.crypto.chainlink"]
EquityPricesEventType = Literal["update", "subscribe"]


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketSpec:
    """Subscribe to realtime market updates for one or more token ids.

    Set ``custom_feature_enabled=True`` to additionally receive
    ``MarketBestBidAskEvent``, ``NewMarketEvent``, and ``MarketResolvedEvent``.
    """

    token_ids: Sequence[str]
    """Token ids whose market events should be delivered."""
    custom_feature_enabled: bool = False
    """Whether to enable top-of-book and market lifecycle events."""
    topic: Literal["market"] = field(default="market", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.custom_feature_enabled, bool):
            raise UserInputError("custom_feature_enabled must be a bool")
        if isinstance(self.token_ids, str | bytes):
            raise UserInputError("token_ids must be a sequence of token ids, not a single string")
        normalized: list[str] = []
        for tid in self.token_ids:
            if not isinstance(tid, str):
                raise UserInputError(f"token_id must be a string, got {type(tid).__name__}")
            if not tid:
                raise UserInputError("token_id must be non-empty")
            normalized.append(tid)
        if not normalized:
            raise UserInputError("token_ids must be a non-empty sequence")
        object.__setattr__(self, "token_ids", tuple(normalized))


@dataclass(frozen=True, slots=True, kw_only=True)
class SportsSpec:
    """Subscription for the Sports stream.

    Sports has no per-subscription filtering — every subscriber receives
    every event the server broadcasts.
    """

    topic: Literal["sports"] = field(default="sports", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class CommentsSpec:
    """Subscribe to realtime comment and reaction events.

    Filters are optional. When provided, ``types`` limits event kinds and the
    parent entity fields limit events to a specific market or event.
    """

    types: Sequence[CommentsEventType] | None = None
    parent_entity_id: int | None = None
    parent_entity_type: ParentEntityType | None = None
    topic: Literal["comments"] = field(default="comments", init=False)

    def __post_init__(self) -> None:
        if self.types is not None:
            if isinstance(self.types, str | bytes):
                raise UserInputError("types must be a sequence, not a single string")
            normalized: list[CommentsEventType] = []
            for t in self.types:
                if not isinstance(t, str) or t not in _COMMENT_EVENT_TYPES:
                    raise UserInputError(f"invalid comments event type: {t!r}")
                normalized.append(t)  # type: ignore[arg-type]
            if not normalized:
                raise UserInputError("types must be non-empty when provided")
            object.__setattr__(self, "types", tuple(normalized))
        if self.parent_entity_id is not None and (
            isinstance(self.parent_entity_id, bool) or not isinstance(self.parent_entity_id, int)
        ):
            raise UserInputError("parent_entity_id must be an int")
        if (
            self.parent_entity_type is not None
            and self.parent_entity_type not in _PARENT_ENTITY_TYPES
        ):
            raise UserInputError(
                f"parent_entity_type must be 'Event' or 'Market', got {self.parent_entity_type!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CryptoPricesSpec:
    """Subscribe to realtime crypto price updates for a topic.

    When ``symbols`` is omitted, the subscription receives all symbols for the
    selected topic.
    """

    topic: CryptoPricesTopic
    symbols: Sequence[str] | None = None

    def __post_init__(self) -> None:
        if self.topic not in _CRYPTO_PRICES_TOPICS:
            raise UserInputError(
                f"topic must be one of {sorted(_CRYPTO_PRICES_TOPICS)}, got {self.topic!r}"
            )
        if self.symbols is not None:
            if isinstance(self.symbols, str | bytes):
                raise UserInputError("symbols must be a sequence of symbols, not a single string")
            normalized: list[str] = []
            for s in self.symbols:
                if not isinstance(s, str):
                    raise UserInputError(f"symbol must be a string, got {type(s).__name__}")
                if not s:
                    raise UserInputError("symbol must be non-empty")
                normalized.append(s)
            if not normalized:
                raise UserInputError("symbols must be non-empty when provided")
            object.__setattr__(self, "symbols", tuple(normalized))


@dataclass(frozen=True, slots=True, kw_only=True)
class EquityPricesSpec:
    """Subscribe to realtime equity price updates for one symbol."""

    symbol: str
    types: Sequence[EquityPricesEventType] | None = None
    topic: Literal["prices.equity.pyth"] = field(default="prices.equity.pyth", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise UserInputError("symbol must be a non-empty string")
        if self.types is not None:
            if isinstance(self.types, str | bytes):
                raise UserInputError("types must be a sequence, not a single string")
            normalized: list[EquityPricesEventType] = []
            for t in self.types:
                if not isinstance(t, str) or t not in _EQUITY_EVENT_TYPES:
                    raise UserInputError(f"invalid equity event type: {t!r}")
                normalized.append(t)  # type: ignore[arg-type]
            if not normalized:
                raise UserInputError("types must be non-empty when provided")
            object.__setattr__(self, "types", tuple(normalized))


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


RtdsSpec = CommentsSpec | CryptoPricesSpec | EquityPricesSpec
PerpsSpec = (
    PerpsTradesSpec
    | PerpsBboSpec
    | PerpsBookSpec
    | PerpsCandlesSpec
    | PerpsTickersSpec
    | PerpsStatisticsSpec
)
PublicSubscription = MarketSpec | SportsSpec | RtdsSpec | PerpsSpec
SecureSubscription = PublicSubscription | UserSpec
Subscription = SecureSubscription


_SPEC_TYPES: tuple[type[Subscription], ...] = (
    MarketSpec,
    SportsSpec,
    CommentsSpec,
    CryptoPricesSpec,
    EquityPricesSpec,
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
    "PublicSubscription",
    "SecureSubscription",
    "CommentsEventType",
    "CommentsSpec",
    "CryptoPricesSpec",
    "CryptoPricesTopic",
    "EquityPricesEventType",
    "EquityPricesSpec",
    "MarketSpec",
    "ParentEntityType",
    "PerpsBboSpec",
    "PerpsBookSpec",
    "PerpsCandlesSpec",
    "PerpsSpec",
    "PerpsStatisticsSpec",
    "PerpsTickersSpec",
    "PerpsTradesSpec",
    "RtdsSpec",
    "SportsSpec",
    "Subscription",
    "UserSpec",
    "normalize_specs",
]
