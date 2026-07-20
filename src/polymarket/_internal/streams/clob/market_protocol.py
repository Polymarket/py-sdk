from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, cast

from pydantic import ValidationError

from polymarket.models.clob.market_events import (
    MarketBestBidAskEvent,
    MarketEvent,
    MarketPriceChangeEvent,
    MarketResolvedEvent,
    NewMarketEvent,
    parse_market_event,
)
from polymarket.models.types import TokenId


@dataclass(frozen=True, slots=True)
class MarketSubscription:
    token_ids: tuple[TokenId, ...]
    custom_feature_enabled: bool = False


@dataclass(frozen=True, slots=True)
class MarketServerState:
    asset_ids: tuple[str, ...]
    custom_feature_enabled: bool


def derive_state(subs: Iterable[MarketSubscription]) -> MarketServerState:
    assets: set[str] = set()
    custom = False
    for sub in subs:
        assets.update(sub.token_ids)
        custom = custom or sub.custom_feature_enabled
    return MarketServerState(
        asset_ids=tuple(sorted(assets)),
        custom_feature_enabled=custom,
    )


def build_initial_frame(state: MarketServerState) -> dict[str, Any]:
    return {
        "type": "market",
        "assets_ids": list(state.asset_ids),
        "custom_feature_enabled": state.custom_feature_enabled,
    }


def build_subscribe_update(
    asset_ids: Iterable[str], *, custom_feature_enabled: bool
) -> dict[str, Any]:
    return {
        "operation": "subscribe",
        "assets_ids": list(asset_ids),
        "custom_feature_enabled": custom_feature_enabled,
    }


def build_unsubscribe_update(asset_ids: Iterable[str]) -> dict[str, Any]:
    return {
        "operation": "unsubscribe",
        "assets_ids": list(asset_ids),
    }


def diff_state_frames(before: MarketServerState, after: MarketServerState) -> list[dict[str, Any]]:
    before_assets = set(before.asset_ids)
    after_assets = set(after.asset_ids)
    added = sorted(after_assets - before_assets)
    removed = sorted(before_assets - after_assets)
    frames: list[dict[str, Any]] = []
    if added:
        frames.append(
            build_subscribe_update(added, custom_feature_enabled=after.custom_feature_enabled)
        )
    elif before.custom_feature_enabled != after.custom_feature_enabled and after.asset_ids:
        # CLOB applies custom_feature_enabled before its "duplicate assets"
        # reject, so re-naming any active asset toggles the flag in place.
        frames.append(
            build_subscribe_update(
                [after.asset_ids[0]],
                custom_feature_enabled=after.custom_feature_enabled,
            )
        )
    if removed:
        frames.append(build_unsubscribe_update(removed))
    return frames


def match_for(sub: MarketSubscription) -> Callable[[MarketEvent], bool]:
    token_ids = frozenset(sub.token_ids)
    custom = sub.custom_feature_enabled

    def matches(event: MarketEvent) -> bool:
        if isinstance(event, MarketPriceChangeEvent):
            return any(change.token_id in token_ids for change in event.payload.price_changes)
        if isinstance(event, NewMarketEvent):
            return custom
        if isinstance(event, MarketResolvedEvent):
            if not custom:
                return False
            return any(tid in token_ids for tid in (event.payload.token_ids or ()))
        if isinstance(event, MarketBestBidAskEvent):
            return custom and event.payload.token_id in token_ids
        return event.payload.token_id in token_ids

    return matches


def parse_events(raw: object) -> tuple[list[MarketEvent], int]:
    """Parse a decoded JSON value (object or array) into MarketEvents.

    Returns ``(events, dropped_count)``; malformed entries are dropped.
    """
    items: list[object] = list(cast(list[object], raw)) if isinstance(raw, list) else [raw]
    parsed: list[MarketEvent] = []
    dropped = 0
    for item in items:
        try:
            parsed.append(parse_market_event(item))
        except ValidationError:
            dropped += 1
    return parsed, dropped
