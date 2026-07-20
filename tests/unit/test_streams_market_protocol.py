from typing import Any

from polymarket._internal.streams.clob.market_protocol import (
    MarketServerState,
    MarketSubscription,
    build_initial_frame,
    build_subscribe_update,
    build_unsubscribe_update,
    derive_state,
    diff_state_frames,
    match_for,
    parse_events,
)
from polymarket.models.clob.market_events import parse_market_event
from polymarket.models.types import TokenId


def _sub(*tokens: str, custom: bool = False) -> MarketSubscription:
    return MarketSubscription(
        token_ids=tuple(TokenId(t) for t in tokens),
        custom_feature_enabled=custom,
    )


def test_derive_state_sorts_unique_asset_ids() -> None:
    state = derive_state([_sub("b", "a"), _sub("c", "a")])
    assert state.asset_ids == ("a", "b", "c")
    assert state.custom_feature_enabled is False


def test_derive_state_flag_is_logical_or() -> None:
    assert derive_state([_sub("a")]).custom_feature_enabled is False
    assert derive_state([_sub("a", custom=True)]).custom_feature_enabled is True
    assert derive_state([_sub("a"), _sub("b", custom=True)]).custom_feature_enabled is True


def test_build_initial_frame_shape() -> None:
    frame = build_initial_frame(
        MarketServerState(asset_ids=("a", "b"), custom_feature_enabled=True)
    )
    assert frame == {
        "type": "market",
        "assets_ids": ["a", "b"],
        "custom_feature_enabled": True,
    }


def test_build_subscribe_and_unsubscribe_update_shapes() -> None:
    assert build_subscribe_update(["a"], custom_feature_enabled=False) == {
        "operation": "subscribe",
        "assets_ids": ["a"],
        "custom_feature_enabled": False,
    }
    assert build_unsubscribe_update(["b"]) == {
        "operation": "unsubscribe",
        "assets_ids": ["b"],
    }


def test_diff_state_added_assets_emit_subscribe_update() -> None:
    before = MarketServerState(asset_ids=("a",), custom_feature_enabled=False)
    after = MarketServerState(asset_ids=("a", "b"), custom_feature_enabled=False)
    frames = diff_state_frames(before, after)
    assert frames == [
        {"operation": "subscribe", "assets_ids": ["b"], "custom_feature_enabled": False}
    ]


def test_diff_state_removed_assets_emit_unsubscribe_update() -> None:
    before = MarketServerState(asset_ids=("a", "b"), custom_feature_enabled=False)
    after = MarketServerState(asset_ids=("a",), custom_feature_enabled=False)
    frames = diff_state_frames(before, after)
    assert frames == [{"operation": "unsubscribe", "assets_ids": ["b"]}]


def test_diff_state_flag_toggle_up_uses_toggle_hack_frame() -> None:
    before = MarketServerState(asset_ids=("a",), custom_feature_enabled=False)
    after = MarketServerState(asset_ids=("a",), custom_feature_enabled=True)
    frames = diff_state_frames(before, after)
    assert frames == [
        {"operation": "subscribe", "assets_ids": ["a"], "custom_feature_enabled": True}
    ]


def test_diff_state_flag_toggle_down_uses_toggle_hack_frame() -> None:
    before = MarketServerState(asset_ids=("a",), custom_feature_enabled=True)
    after = MarketServerState(asset_ids=("a",), custom_feature_enabled=False)
    frames = diff_state_frames(before, after)
    assert frames == [
        {"operation": "subscribe", "assets_ids": ["a"], "custom_feature_enabled": False}
    ]


def test_diff_state_added_and_removed_in_one_op_emit_both() -> None:
    before = MarketServerState(asset_ids=("a", "b"), custom_feature_enabled=False)
    after = MarketServerState(asset_ids=("a", "c"), custom_feature_enabled=False)
    frames = diff_state_frames(before, after)
    assert frames == [
        {"operation": "subscribe", "assets_ids": ["c"], "custom_feature_enabled": False},
        {"operation": "unsubscribe", "assets_ids": ["b"]},
    ]


def test_diff_state_no_change_no_frames() -> None:
    s = MarketServerState(asset_ids=("a",), custom_feature_enabled=False)
    assert diff_state_frames(s, s) == []


def test_diff_state_toggle_with_empty_after_emits_only_unsub() -> None:
    before = MarketServerState(asset_ids=("a",), custom_feature_enabled=True)
    after = MarketServerState(asset_ids=(), custom_feature_enabled=False)
    frames = diff_state_frames(before, after)
    assert frames == [{"operation": "unsubscribe", "assets_ids": ["a"]}]


def test_matcher_default_event_matches_only_when_token_in_subscription() -> None:
    sub = _sub("a")
    event = parse_market_event(
        {
            "event_type": "book",
            "market": "m",
            "asset_id": "a",
            "bids": [],
            "asks": [],
        }
    )
    other = parse_market_event(
        {
            "event_type": "book",
            "market": "m",
            "asset_id": "x",
            "bids": [],
            "asks": [],
        }
    )
    matches = match_for(sub)
    assert matches(event) is True
    assert matches(other) is False


def test_matcher_price_change_fans_when_any_change_matches() -> None:
    sub = _sub("a")
    event = parse_market_event(
        {
            "event_type": "price_change",
            "market": "m",
            "price_changes": [
                {"asset_id": "z", "price": "0.1", "size": "1", "side": "BUY"},
                {"asset_id": "a", "price": "0.2", "size": "1", "side": "BUY"},
            ],
        }
    )
    assert match_for(sub)(event) is True


def test_matcher_new_market_gated_by_custom_feature() -> None:
    plain = _sub("a")
    custom = _sub("a", custom=True)
    event = parse_market_event({"event_type": "new_market", "id": "1", "market": "m"})
    assert match_for(plain)(event) is False
    assert match_for(custom)(event) is True


def test_matcher_market_resolved_requires_custom_and_intersection() -> None:
    event = parse_market_event(
        {
            "event_type": "market_resolved",
            "id": "1",
            "market": "m",
            "assets_ids": ["a"],
        }
    )
    assert match_for(_sub("a"))(event) is False  # no custom
    assert match_for(_sub("a", custom=True))(event) is True
    assert match_for(_sub("b", custom=True))(event) is False  # no intersection


def test_matcher_best_bid_ask_requires_custom_and_token_match() -> None:
    event = parse_market_event({"event_type": "best_bid_ask", "market": "m", "asset_id": "a"})
    assert match_for(_sub("a"))(event) is False
    assert match_for(_sub("a", custom=True))(event) is True
    assert match_for(_sub("b", custom=True))(event) is False


def test_parse_events_handles_single_object() -> None:
    raw: dict[str, Any] = {
        "event_type": "book",
        "market": "m",
        "asset_id": "a",
        "bids": [],
        "asks": [],
    }
    events, dropped = parse_events(raw)
    assert len(events) == 1
    assert dropped == 0


def test_parse_events_handles_array() -> None:
    raw: list[dict[str, Any]] = [
        {"event_type": "book", "market": "m", "asset_id": "a", "bids": [], "asks": []},
        {"event_type": "book", "market": "m", "asset_id": "b", "bids": [], "asks": []},
    ]
    events, dropped = parse_events(raw)
    assert len(events) == 2
    assert dropped == 0


def test_parse_events_drops_malformed_entries_and_counts() -> None:
    raw: list[dict[str, Any]] = [
        {"event_type": "book", "market": "m", "asset_id": "a", "bids": [], "asks": []},
        {"event_type": "unknown", "garbage": True},
    ]
    events, dropped = parse_events(raw)
    assert len(events) == 1
    assert dropped == 1
