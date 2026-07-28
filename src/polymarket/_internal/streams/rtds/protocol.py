from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, assert_never

from polymarket.models.rtds_events import (
    CommentCreatedEvent,
    CommentRemovedEvent,
    CryptoPricesBinanceEvent,
    CryptoPricesChainlinkEvent,
    CryptoPricesChainlinkTwapEvent,
    EquityPricesSubscribeEvent,
    EquityPricesUpdateEvent,
    ReactionCreatedEvent,
    ReactionRemovedEvent,
    RtdsEvent,
    api_topic_to_wire,
)
from polymarket.streams._specs import (
    CommentsSpec,
    CryptoPricesChainlinkTwapSpec,
    CryptoPricesChainlinkTwapWindowSeconds,
    CryptoPricesSpec,
    EquityPricesSpec,
    RtdsSpec,
)

_DEFAULT_COMMENT_TYPES: tuple[str, ...] = ("comment_created",)


@dataclass(frozen=True, slots=True)
class RtdsServerSubscription:
    topic: str
    type: str

    @property
    def key(self) -> str:
        return f"{self.topic}:{self.type}"


def server_subscriptions_for(spec: RtdsSpec) -> tuple[RtdsServerSubscription, ...]:
    if isinstance(spec, CommentsSpec):
        types = spec.types if spec.types else _DEFAULT_COMMENT_TYPES
        return tuple(RtdsServerSubscription(topic="comments", type=t) for t in types)
    if isinstance(spec, CryptoPricesChainlinkTwapSpec):
        return (
            RtdsServerSubscription(
                topic=_twap_wire_topic(spec.window_seconds),
                type="update",
            ),
        )
    if isinstance(spec, CryptoPricesSpec | EquityPricesSpec):  # pyright: ignore[reportUnnecessaryIsInstance]
        wire = api_topic_to_wire(spec.topic)
        return (RtdsServerSubscription(topic=wire, type="update"),)
    assert_never(spec)


def _twap_wire_topic(window_seconds: CryptoPricesChainlinkTwapWindowSeconds) -> str:
    if window_seconds == 30:
        return "crypto_prices_twap_thirty"
    if window_seconds == 60:
        return "crypto_prices_twap_sixty"
    assert_never(window_seconds)


def derive_state(subs: Iterable[RtdsSpec]) -> dict[str, RtdsServerSubscription]:
    state: dict[str, RtdsServerSubscription] = {}
    for sub in subs:
        for srv in server_subscriptions_for(sub):
            state.setdefault(srv.key, srv)
    return state


def build_subscribe_frame(subscriptions: Iterable[RtdsServerSubscription]) -> dict[str, Any]:
    return {
        "action": "subscribe",
        "subscriptions": [{"topic": s.topic, "type": s.type} for s in subscriptions],
    }


def build_unsubscribe_frame(subscriptions: Iterable[RtdsServerSubscription]) -> dict[str, Any]:
    return {
        "action": "unsubscribe",
        "subscriptions": [{"topic": s.topic, "type": s.type} for s in subscriptions],
    }


def diff_state_frames(
    before: dict[str, RtdsServerSubscription],
    after: dict[str, RtdsServerSubscription],
) -> list[dict[str, Any]]:
    added = [s for k, s in after.items() if k not in before]
    removed = [s for k, s in before.items() if k not in after]
    frames: list[dict[str, Any]] = []
    if added:
        frames.append(build_subscribe_frame(added))
    if removed:
        frames.append(build_unsubscribe_frame(removed))
    return frames


def matcher_for(spec: RtdsSpec) -> Callable[[RtdsEvent], bool]:
    if isinstance(spec, CommentsSpec):
        return _comments_matcher(spec)
    if isinstance(spec, CryptoPricesChainlinkTwapSpec):
        return _twap_matcher(spec)
    if isinstance(spec, CryptoPricesSpec):
        return _crypto_matcher(spec)
    return _equity_matcher(spec)


def _comments_matcher(spec: CommentsSpec) -> Callable[[RtdsEvent], bool]:
    allowed_types = frozenset(spec.types or _DEFAULT_COMMENT_TYPES)
    parent_id = spec.parent_entity_id
    parent_id_str = str(parent_id) if parent_id is not None else None
    parent_type = spec.parent_entity_type
    needs_parent_check = parent_id is not None or parent_type is not None

    def matches(event: RtdsEvent) -> bool:
        if not isinstance(
            event,
            CommentCreatedEvent | CommentRemovedEvent | ReactionCreatedEvent | ReactionRemovedEvent,
        ):
            return False
        if event.type not in allowed_types:
            return False
        if not needs_parent_check:
            return True
        if isinstance(event, ReactionCreatedEvent | ReactionRemovedEvent):
            return False
        payload = event.payload
        if parent_id_str is not None:
            payload_parent = payload.parent_entity_id
            if payload_parent is None or str(payload_parent) != parent_id_str:
                return False
        return not (parent_type is not None and payload.parent_entity_type != parent_type)

    return matches


def _crypto_matcher(spec: CryptoPricesSpec) -> Callable[[RtdsEvent], bool]:
    expected_topic = spec.topic
    allowed_symbols = frozenset(spec.symbols) if spec.symbols else None

    def matches(event: RtdsEvent) -> bool:
        if not isinstance(event, CryptoPricesBinanceEvent | CryptoPricesChainlinkEvent):
            return False
        if event.topic != expected_topic:
            return False
        return not (allowed_symbols is not None and event.payload.symbol not in allowed_symbols)

    return matches


def _twap_matcher(spec: CryptoPricesChainlinkTwapSpec) -> Callable[[RtdsEvent], bool]:
    expected_window = spec.window_seconds
    allowed_symbols = frozenset(spec.symbols) if spec.symbols else None

    def matches(event: RtdsEvent) -> bool:
        if not isinstance(event, CryptoPricesChainlinkTwapEvent):
            return False
        if event.payload.window_seconds != expected_window:
            return False
        return not (allowed_symbols is not None and event.payload.symbol not in allowed_symbols)

    return matches


def _equity_matcher(spec: EquityPricesSpec) -> Callable[[RtdsEvent], bool]:
    expected_symbol = spec.symbol.lower()
    allowed_types = frozenset(spec.types) if spec.types else None

    def matches(event: RtdsEvent) -> bool:
        if not isinstance(event, EquityPricesUpdateEvent | EquityPricesSubscribeEvent):
            return False
        if event.payload.symbol.lower() != expected_symbol:
            return False
        return not (allowed_types is not None and event.type not in allowed_types)

    return matches
