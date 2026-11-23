from polymarket._internal.streams.clob.user_protocol import (
    UserServerState,
    UserSubscription,
    build_initial_frame,
    derive_state,
    diff_state_frames,
    matcher_for,
)
from polymarket.models.clob.user_events import UserEvent, parse_user_event

_ACCESS_TOKEN = "access-token"


def _order_event(market: str) -> UserEvent:
    return parse_user_event(
        {
            "event_type": "order",
            "id": "x",
            "owner": "0xowner",
            "market": market,
            "asset_id": "tid",
            "side": "BUY",
            "original_size": "1",
            "size_matched": "0",
            "price": "0.5",
            "type": "PLACEMENT",
            "timestamp": "1710000000000",
        }
    )


def test_derive_state_empty() -> None:
    assert derive_state([]) == UserServerState(include_all_markets=False, markets=())


def test_derive_state_single_narrow() -> None:
    state = derive_state([UserSubscription(markets=("m1",))])
    assert state.include_all_markets is False
    assert state.markets == ("m1",)


def test_derive_state_union_of_narrows() -> None:
    state = derive_state(
        [UserSubscription(markets=("m1",)), UserSubscription(markets=("m2", "m1"))]
    )
    assert state.include_all_markets is False
    assert state.markets == ("m1", "m2")


def test_derive_state_promotes_to_all_when_any_sub_is_all() -> None:
    state = derive_state([UserSubscription(markets=("m1",)), UserSubscription(markets=())])
    assert state.include_all_markets is True
    assert state.markets == ()


def test_initial_frame_shape() -> None:
    state = UserServerState(include_all_markets=False, markets=("m1",))
    assert build_initial_frame(state, _ACCESS_TOKEN) == {
        "type": "user",
        "auth": {"accessToken": "access-token"},
        "markets": ["m1"],
    }


def test_initial_frame_all_markets_omits_market_filter() -> None:
    state = UserServerState(include_all_markets=True, markets=())
    assert build_initial_frame(state, _ACCESS_TOKEN) == {
        "type": "user",
        "auth": {"accessToken": "access-token"},
    }


def test_diff_no_change() -> None:
    s = UserServerState(include_all_markets=False, markets=("m1",))
    assert diff_state_frames(s, s) == []


def test_diff_add_market() -> None:
    before = UserServerState(include_all_markets=False, markets=("m1",))
    after = UserServerState(include_all_markets=False, markets=("m1", "m2"))
    frames = diff_state_frames(before, after)
    assert frames == [{"operation": "subscribe", "markets": ["m2"]}]


def test_diff_remove_market() -> None:
    before = UserServerState(include_all_markets=False, markets=("m1", "m2"))
    after = UserServerState(include_all_markets=False, markets=("m1",))
    frames = diff_state_frames(before, after)
    assert frames == [{"operation": "unsubscribe", "markets": ["m2"]}]


def test_diff_add_and_remove_simultaneous() -> None:
    before = UserServerState(include_all_markets=False, markets=("m1",))
    after = UserServerState(include_all_markets=False, markets=("m2",))
    frames = diff_state_frames(before, after)
    assert frames == [
        {"operation": "subscribe", "markets": ["m2"]},
        {"operation": "unsubscribe", "markets": ["m1"]},
    ]


def test_diff_promotion_to_all_markets_unsubscribes_prior() -> None:
    before = UserServerState(include_all_markets=False, markets=("m1", "m2"))
    after = UserServerState(include_all_markets=True, markets=())
    frames = diff_state_frames(before, after)
    assert frames == [{"operation": "unsubscribe", "markets": ["m1", "m2"]}]


def test_diff_promotion_from_empty_to_all_sends_nothing() -> None:
    before = UserServerState(include_all_markets=False, markets=())
    after = UserServerState(include_all_markets=True, markets=())
    assert diff_state_frames(before, after) == []


def test_diff_demotion_from_all_re_narrows() -> None:
    before = UserServerState(include_all_markets=True, markets=())
    after = UserServerState(include_all_markets=False, markets=("m1",))
    frames = diff_state_frames(before, after)
    assert frames == [{"operation": "subscribe", "markets": ["m1"]}]


def test_diff_demotion_from_all_to_empty_sends_nothing() -> None:
    before = UserServerState(include_all_markets=True, markets=())
    after = UserServerState(include_all_markets=False, markets=())
    assert diff_state_frames(before, after) == []


def test_matcher_all_markets_accepts_everything() -> None:
    matches = matcher_for(UserSubscription(markets=()))
    assert matches(_order_event("0xANY")) is True


def test_matcher_specific_market_accepts_only_match() -> None:
    matches = matcher_for(UserSubscription(markets=("0xM1",)))
    assert matches(_order_event("0xM1")) is True
    assert matches(_order_event("0xM2")) is False


def test_matcher_is_case_insensitive() -> None:
    matches = matcher_for(UserSubscription(markets=("0xABCD",)))
    assert matches(_order_event("0xabcd")) is True
    assert matches(_order_event("0xABCD")) is True
