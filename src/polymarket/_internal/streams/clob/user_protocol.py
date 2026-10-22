from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from polymarket.models import ApiKeyCreds
from polymarket.models.clob.user_events import UserEvent


@dataclass(frozen=True, slots=True)
class UserSubscription:
    markets: tuple[str, ...] = ()

    @property
    def is_all_markets(self) -> bool:
        return len(self.markets) == 0


@dataclass(frozen=True, slots=True)
class UserServerState:
    include_all_markets: bool = False
    markets: tuple[str, ...] = field(default_factory=tuple)


def derive_state(subs: Iterable[UserSubscription]) -> UserServerState:
    include_all = False
    markets: set[str] = set()
    for sub in subs:
        if sub.is_all_markets:
            include_all = True
            continue
        markets.update(sub.markets)
    if include_all:
        return UserServerState(include_all_markets=True, markets=())
    return UserServerState(include_all_markets=False, markets=tuple(sorted(markets)))


def build_initial_frame(state: UserServerState, credentials: ApiKeyCreds) -> dict[str, Any]:
    frame: dict[str, Any] = {
        "type": "user",
        "auth": {
            "apiKey": credentials.key,
            "secret": credentials.secret,
            "passphrase": credentials.passphrase,
        },
    }
    if not state.include_all_markets:
        frame["markets"] = list(state.markets)
    return frame


def _build_subscribe_update(markets: Iterable[str]) -> dict[str, Any]:
    return {"operation": "subscribe", "markets": list(markets)}


def _build_unsubscribe_update(markets: Iterable[str]) -> dict[str, Any]:
    return {"operation": "unsubscribe", "markets": list(markets)}


def diff_state_frames(before: UserServerState, after: UserServerState) -> list[dict[str, Any]]:
    if after.include_all_markets:
        if not before.include_all_markets and before.markets:
            return [_build_unsubscribe_update(before.markets)]
        return []
    if before.include_all_markets:
        if after.markets:
            return [_build_subscribe_update(after.markets)]
        return []
    before_set = set(before.markets)
    after_set = set(after.markets)
    added = sorted(after_set - before_set)
    removed = sorted(before_set - after_set)
    frames: list[dict[str, Any]] = []
    if added:
        frames.append(_build_subscribe_update(added))
    if removed:
        frames.append(_build_unsubscribe_update(removed))
    return frames


def matcher_for(sub: UserSubscription) -> Callable[[UserEvent], bool]:
    if sub.is_all_markets:
        return lambda _event: True
    allowed = frozenset(m.lower() for m in sub.markets)

    def matches(event: UserEvent) -> bool:
        return event.payload.condition_id.lower() in allowed

    return matches


__all__ = [
    "UserServerState",
    "UserSubscription",
    "build_initial_frame",
    "derive_state",
    "diff_state_frames",
    "matcher_for",
]
