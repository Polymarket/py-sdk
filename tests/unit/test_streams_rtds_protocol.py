from polymarket._internal.streams.rtds.protocol import (
    build_subscribe_frame,
    build_unsubscribe_frame,
    derive_state,
    diff_state_frames,
    matcher_for,
    server_subscriptions_for,
)
from polymarket.models.rtds_events import RtdsEvent, parse_rtds_event
from polymarket.streams._specs import (
    CommentsSpec,
    CryptoPricesChainlinkTwapSpec,
    CryptoPricesSpec,
    EquityPricesSpec,
)


def test_comments_defaults_to_comment_created_only_when_unspecified() -> None:
    srvs = server_subscriptions_for(CommentsSpec())
    assert {s.type for s in srvs} == {"comment_created"}
    assert all(s.topic == "comments" for s in srvs)


def test_comments_expands_only_requested_types() -> None:
    srvs = server_subscriptions_for(CommentsSpec(types=["comment_created", "reaction_created"]))
    assert {s.type for s in srvs} == {"comment_created", "reaction_created"}


def test_comments_all_four_types_when_explicitly_requested() -> None:
    srvs = server_subscriptions_for(
        CommentsSpec(
            types=["comment_created", "comment_removed", "reaction_created", "reaction_removed"]
        )
    )
    assert {s.type for s in srvs} == {
        "comment_created",
        "comment_removed",
        "reaction_created",
        "reaction_removed",
    }


def test_crypto_uses_wire_topic_name() -> None:
    binance = server_subscriptions_for(CryptoPricesSpec(topic="prices.crypto.binance"))
    chainlink = server_subscriptions_for(CryptoPricesSpec(topic="prices.crypto.chainlink"))
    assert binance == (type(binance[0])(topic="crypto_prices", type="update"),)
    assert chainlink == (type(chainlink[0])(topic="crypto_prices_chainlink", type="update"),)


def test_chainlink_twap_uses_window_specific_wire_topic() -> None:
    thirty = server_subscriptions_for(CryptoPricesChainlinkTwapSpec(window_seconds=30))
    sixty = server_subscriptions_for(CryptoPricesChainlinkTwapSpec(window_seconds=60))

    assert thirty == (type(thirty[0])(topic="crypto_prices_twap_thirty", type="update"),)
    assert sixty == (type(sixty[0])(topic="crypto_prices_twap_sixty", type="update"),)


def test_equity_always_server_subscribes_to_update_only() -> None:
    srvs = server_subscriptions_for(EquityPricesSpec(symbol="AAPL"))
    assert srvs == (type(srvs[0])(topic="equity_prices", type="update"),)


def test_equity_types_filter_does_not_change_server_subscribe() -> None:
    srvs = server_subscriptions_for(EquityPricesSpec(symbol="AAPL", types=["subscribe"]))
    assert srvs == (type(srvs[0])(topic="equity_prices", type="update"),)


def test_dedup_collapses_overlapping_specs_by_key() -> None:
    state = derive_state(
        [
            CryptoPricesSpec(topic="prices.crypto.binance", symbols=["btcusdt"]),
            CryptoPricesSpec(topic="prices.crypto.binance", symbols=["ethusdt"]),
        ]
    )
    assert list(state.keys()) == ["crypto_prices:update"]


def test_dedup_keeps_distinct_topics_separately() -> None:
    state = derive_state(
        [
            CryptoPricesSpec(topic="prices.crypto.binance"),
            CryptoPricesSpec(topic="prices.crypto.chainlink"),
        ]
    )
    assert set(state.keys()) == {"crypto_prices:update", "crypto_prices_chainlink:update"}


def test_chainlink_twap_dedup_shares_a_window_but_keeps_windows_distinct() -> None:
    state = derive_state(
        [
            CryptoPricesChainlinkTwapSpec(window_seconds=30, symbols=["btc/usd"]),
            CryptoPricesChainlinkTwapSpec(window_seconds=30, symbols=["eth/usd"]),
            CryptoPricesChainlinkTwapSpec(window_seconds=60, symbols=["btc/usd"]),
        ]
    )

    assert set(state) == {
        "crypto_prices_twap_thirty:update",
        "crypto_prices_twap_sixty:update",
    }


def test_dedup_keeps_distinct_comment_types() -> None:
    state = derive_state(
        [
            CommentsSpec(types=["comment_created"]),
            CommentsSpec(types=["reaction_created"]),
        ]
    )
    assert set(state.keys()) == {"comments:comment_created", "comments:reaction_created"}


def test_subscribe_frame_shape() -> None:
    srvs = server_subscriptions_for(CryptoPricesSpec(topic="prices.crypto.binance"))
    assert build_subscribe_frame(srvs) == {
        "action": "subscribe",
        "subscriptions": [{"topic": "crypto_prices", "type": "update"}],
    }


def test_unsubscribe_frame_shape() -> None:
    srvs = server_subscriptions_for(CryptoPricesSpec(topic="prices.crypto.chainlink"))
    assert build_unsubscribe_frame(srvs) == {
        "action": "unsubscribe",
        "subscriptions": [{"topic": "crypto_prices_chainlink", "type": "update"}],
    }


def test_diff_added_emits_subscribe_only() -> None:
    before = derive_state([CryptoPricesSpec(topic="prices.crypto.binance")])
    after = derive_state(
        [
            CryptoPricesSpec(topic="prices.crypto.binance"),
            CryptoPricesSpec(topic="prices.crypto.chainlink"),
        ]
    )
    frames = diff_state_frames(before, after)
    assert len(frames) == 1
    assert frames[0]["action"] == "subscribe"
    assert frames[0]["subscriptions"] == [{"topic": "crypto_prices_chainlink", "type": "update"}]


def test_diff_removed_emits_unsubscribe_only() -> None:
    before = derive_state(
        [
            CryptoPricesSpec(topic="prices.crypto.binance"),
            CryptoPricesSpec(topic="prices.crypto.chainlink"),
        ]
    )
    after = derive_state([CryptoPricesSpec(topic="prices.crypto.binance")])
    frames = diff_state_frames(before, after)
    assert len(frames) == 1
    assert frames[0]["action"] == "unsubscribe"
    assert frames[0]["subscriptions"] == [{"topic": "crypto_prices_chainlink", "type": "update"}]


def test_diff_no_change_emits_nothing() -> None:
    state = derive_state([CryptoPricesSpec(topic="prices.crypto.binance")])
    assert diff_state_frames(state, state) == []


def _crypto_event(symbol: str, topic: str = "crypto_prices") -> RtdsEvent:
    return parse_rtds_event(
        {
            "topic": topic,
            "type": "update",
            "timestamp": "1710000000000",
            "payload": {"symbol": symbol, "timestamp": 1710000000000, "value": "1"},
        }
    )


def _twap_event(symbol: str, window_seconds: int) -> RtdsEvent:
    topic = "crypto_prices_twap_thirty" if window_seconds == 30 else "crypto_prices_twap_sixty"
    return parse_rtds_event(
        {
            "topic": topic,
            "type": "update",
            "timestamp": 1772752582004,
            "payload": {
                "symbol": symbol,
                "value": 1.0,
                "full_accuracy_value": "1000000000000000000",
                "timestamp": 1772752581815,
                "window_s": window_seconds,
            },
        }
    )


def _comment_created(parent_entity_id: int = 1, parent_entity_type: str = "Event") -> RtdsEvent:
    return parse_rtds_event(
        {
            "topic": "comments",
            "type": "comment_created",
            "timestamp": "1710000000000",
            "payload": {
                "id": "1",
                "body": "hi",
                "parentEntityType": parent_entity_type,
                "parentEntityID": parent_entity_id,
            },
        }
    )


def _reaction_created() -> RtdsEvent:
    return parse_rtds_event(
        {
            "topic": "comments",
            "type": "reaction_created",
            "timestamp": "1710000000000",
            "payload": {"id": "1", "commentID": 99},
        }
    )


def _equity_event(symbol: str, event_type: str) -> RtdsEvent:
    return parse_rtds_event(
        {
            "topic": "equity_prices",
            "type": event_type,
            "timestamp": "1710000000000",
            "payload": (
                {"symbol": symbol, "value": "1", "timestamp": 1710000000000}
                if event_type == "update"
                else {"symbol": symbol, "data": []}
            ),
        }
    )


def test_crypto_matcher_filters_by_symbol() -> None:
    matches = matcher_for(CryptoPricesSpec(topic="prices.crypto.binance", symbols=["btcusdt"]))
    assert matches(_crypto_event("btcusdt")) is True
    assert matches(_crypto_event("ethusdt")) is False


def test_crypto_matcher_no_symbol_filter_accepts_all_symbols() -> None:
    matches = matcher_for(CryptoPricesSpec(topic="prices.crypto.binance"))
    assert matches(_crypto_event("btcusdt")) is True
    assert matches(_crypto_event("anything")) is True


def test_crypto_matcher_filters_by_topic_source() -> None:
    matches = matcher_for(CryptoPricesSpec(topic="prices.crypto.binance"))
    assert matches(_crypto_event("btcusdt", topic="crypto_prices_chainlink")) is False


def test_chainlink_twap_matcher_filters_by_window_and_symbol() -> None:
    matches = matcher_for(CryptoPricesChainlinkTwapSpec(window_seconds=30, symbols=["btc/usd"]))

    assert matches(_twap_event("btc/usd", 30)) is True
    assert matches(_twap_event("eth/usd", 30)) is False
    assert matches(_twap_event("BTC/USD", 30)) is False
    assert matches(_twap_event("btc/usd", 60)) is False
    assert matches(_crypto_event("btc/usd", topic="crypto_prices_chainlink")) is False


def test_chainlink_twap_matcher_without_symbols_accepts_all_for_its_window() -> None:
    matches = matcher_for(CryptoPricesChainlinkTwapSpec(window_seconds=60))

    assert matches(_twap_event("btc/usd", 60)) is True
    assert matches(_twap_event("eth/usd", 60)) is True
    assert matches(_twap_event("btc/usd", 30)) is False


def test_comments_matcher_filters_by_type() -> None:
    matches = matcher_for(CommentsSpec(types=["comment_created"]))
    assert matches(_comment_created()) is True
    assert matches(_reaction_created()) is False


def test_default_commentsspec_matcher_drops_non_default_types() -> None:
    matches = matcher_for(CommentsSpec())
    assert matches(_comment_created()) is True
    assert matches(_reaction_created()) is False


def _comment_removed(parent_entity_id: int = 1, parent_entity_type: str = "Event") -> RtdsEvent:
    return parse_rtds_event(
        {
            "topic": "comments",
            "type": "comment_removed",
            "timestamp": "1710000000000",
            "payload": {
                "id": "99",
                "parentEntityType": parent_entity_type,
                "parentEntityID": parent_entity_id,
            },
        }
    )


def test_comments_parent_filter_matches_removed_event_with_int_parent_id() -> None:
    matches = matcher_for(CommentsSpec(types=["comment_removed"], parent_entity_id=1))
    assert matches(_comment_removed(parent_entity_id=1)) is True
    assert matches(_comment_removed(parent_entity_id=2)) is False


def test_comments_parent_filter_drops_reactions_without_parent_context() -> None:
    matches = matcher_for(CommentsSpec(parent_entity_id=1, parent_entity_type="Event"))
    assert matches(_comment_created(parent_entity_id=1, parent_entity_type="Event")) is True
    assert matches(_reaction_created()) is False


def test_comments_parent_filter_rejects_non_matching_parent() -> None:
    matches = matcher_for(CommentsSpec(parent_entity_id=1))
    assert matches(_comment_created(parent_entity_id=2)) is False


def test_equity_matcher_filters_by_symbol_case_insensitive() -> None:
    matches = matcher_for(EquityPricesSpec(symbol="AAPL"))
    assert matches(_equity_event("AAPL", "update")) is True
    assert matches(_equity_event("aapl", "update")) is True
    assert matches(_equity_event("MSFT", "update")) is False


def test_equity_matcher_filters_by_type_client_side() -> None:
    matches = matcher_for(EquityPricesSpec(symbol="AAPL", types=["update"]))
    assert matches(_equity_event("AAPL", "update")) is True
    assert matches(_equity_event("AAPL", "subscribe")) is False
