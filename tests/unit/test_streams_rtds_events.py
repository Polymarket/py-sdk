from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from polymarket.models.rtds_events import (
    CommentCreatedEvent,
    CommentRemovedEvent,
    CryptoPricesBinanceEvent,
    CryptoPricesChainlinkEvent,
    CryptoPricesChainlinkTwapEvent,
    CryptoPricesChainlinkTwapPayload,
    EquityPricesSubscribeEvent,
    EquityPricesUpdateEvent,
    ReactionCreatedEvent,
    api_topic_to_wire,
    parse_rtds_event,
    wire_topic_to_api,
)

_COMMENT_CREATED: dict[str, Any] = {
    "topic": "comments",
    "type": "comment_created",
    "timestamp": "1710000000000",
    "payload": {
        "id": "42",
        "body": "hi",
        "parentEntityType": "Event",
        "parentEntityID": 123,
        "userAddress": "0xabc",
        "createdAt": "2024-03-09T00:00:00Z",
    },
}

_REACTION_CREATED: dict[str, Any] = {
    "topic": "comments",
    "type": "reaction_created",
    "timestamp": "1710000000000",
    "payload": {
        "id": "7",
        "commentID": 42,
        "reactionType": "like",
        "userAddress": "0xdef",
    },
}

_CRYPTO_BINANCE: dict[str, Any] = {
    "topic": "crypto_prices",
    "type": "update",
    "timestamp": "1710000000000",
    "payload": {"symbol": "btcusdt", "timestamp": 1710000000000, "value": "65000.5"},
}

_CRYPTO_CHAINLINK: dict[str, Any] = {
    "topic": "crypto_prices_chainlink",
    "type": "update",
    "timestamp": "1710000000000",
    "payload": {"symbol": "ETH/USD", "timestamp": 1710000000000, "value": "3500.25"},
}

_CRYPTO_CHAINLINK_TWAP: dict[str, Any] = {
    "topic": "crypto_prices_twap_thirty",
    "type": "update",
    "timestamp": 1772752582004,
    "payload": {
        "symbol": "btc/usd",
        "value": 65000.12345678901,
        "full_accuracy_value": "65000123456789012345678",
        "timestamp": 1772752581815,
        "window_s": 30,
    },
}

_EQUITY_UPDATE: dict[str, Any] = {
    "topic": "equity_prices",
    "type": "update",
    "timestamp": "1710000000000",
    "payload": {
        "symbol": "AAPL",
        "value": "180.42",
        "timestamp": 1710000000000,
        "received_at": 1710000000050,
        "is_carried_forward": False,
    },
}

_EQUITY_SUBSCRIBE: dict[str, Any] = {
    "topic": "equity_prices",
    "type": "subscribe",
    "timestamp": "1710000000000",
    "payload": {
        "symbol": "AAPL",
        "data": [
            {"timestamp": 1710000000000, "value": "180.00"},
            {"timestamp": 1710000060000, "value": "180.42"},
        ],
    },
}


def test_wire_to_api_topic_mapping() -> None:
    assert wire_topic_to_api("comments") == "comments"
    assert wire_topic_to_api("crypto_prices") == "prices.crypto.binance"
    assert wire_topic_to_api("crypto_prices_chainlink") == "prices.crypto.chainlink"
    assert wire_topic_to_api("crypto_prices_twap_thirty") == "prices.crypto.chainlink.twap"
    assert wire_topic_to_api("crypto_prices_twap_sixty") == "prices.crypto.chainlink.twap"
    assert wire_topic_to_api("equity_prices") == "prices.equity.pyth"
    assert wire_topic_to_api("unknown") is None


def test_api_to_wire_topic_mapping() -> None:
    assert api_topic_to_wire("comments") == "comments"
    assert api_topic_to_wire("prices.crypto.binance") == "crypto_prices"
    assert api_topic_to_wire("prices.crypto.chainlink") == "crypto_prices_chainlink"
    assert api_topic_to_wire("prices.equity.pyth") == "equity_prices"


def test_comment_created_parses_with_camelcase_aliases() -> None:
    event = parse_rtds_event(_COMMENT_CREATED)
    assert isinstance(event, CommentCreatedEvent)
    assert event.topic == "comments"
    assert event.type == "comment_created"
    assert event.payload.id == "42"
    assert event.payload.parent_entity_type == "Event"
    assert event.payload.parent_entity_id == "123"
    assert event.payload.user_address == "0xabc"


def test_comment_removed_parses_full_payload_mirroring_ts() -> None:
    event = parse_rtds_event(
        {
            "topic": "comments",
            "type": "comment_removed",
            "timestamp": "1710000000000",
            "payload": {
                "id": "99",
                "body": "deleted body",
                "parentEntityType": "Event",
                "parentEntityID": 7,
                "parentCommentID": "pc-1",
                "userAddress": "0xabc",
                "replyAddress": "0xdef",
                "createdAt": "2024-03-09T00:00:00Z",
                "updatedAt": "2024-03-10T00:00:00Z",
                "reportCount": 2,
                "reactionCount": 5,
                "tradeAsset": "asset-1",
            },
        }
    )
    assert isinstance(event, CommentRemovedEvent)
    p = event.payload
    assert p.id == "99"
    assert p.body == "deleted body"
    assert p.parent_entity_type == "Event"
    assert p.parent_entity_id == 7  # noqa: PLR2004
    assert p.parent_comment_id == "pc-1"
    assert p.user_address == "0xabc"
    assert p.reply_address == "0xdef"
    assert p.created_at == datetime(2024, 3, 9, tzinfo=UTC)
    assert p.updated_at == datetime(2024, 3, 10, tzinfo=UTC)
    assert p.report_count == 2  # noqa: PLR2004
    assert p.reaction_count == 5  # noqa: PLR2004
    assert p.trade_asset == "asset-1"


def test_reaction_created_parses() -> None:
    event = parse_rtds_event(_REACTION_CREATED)
    assert isinstance(event, ReactionCreatedEvent)
    assert event.payload.comment_id == 42
    assert event.payload.reaction_type == "like"


def test_crypto_binance_wire_topic_remapped_to_api_topic() -> None:
    event = parse_rtds_event(_CRYPTO_BINANCE)
    assert isinstance(event, CryptoPricesBinanceEvent)
    assert event.topic == "prices.crypto.binance"
    assert event.payload.symbol == "btcusdt"


def test_crypto_chainlink_wire_topic_remapped_to_api_topic() -> None:
    event = parse_rtds_event(_CRYPTO_CHAINLINK)
    assert isinstance(event, CryptoPricesChainlinkEvent)
    assert event.topic == "prices.crypto.chainlink"
    assert event.payload.symbol == "ETH/USD"


@pytest.mark.parametrize(
    ("wire_topic", "window_seconds"),
    [
        ("crypto_prices_twap_thirty", 30),
        ("crypto_prices_twap_sixty", 60),
    ],
)
def test_crypto_chainlink_twap_normalizes_topic_window_and_exact_value(
    wire_topic: str, window_seconds: int
) -> None:
    event = parse_rtds_event(
        {
            **_CRYPTO_CHAINLINK_TWAP,
            "topic": wire_topic,
            "payload": {
                **_CRYPTO_CHAINLINK_TWAP["payload"],
                "window_s": window_seconds,
            },
        }
    )

    assert isinstance(event, CryptoPricesChainlinkTwapEvent)
    assert event.topic == "prices.crypto.chainlink.twap"
    assert event.type == "update"
    assert event.timestamp == datetime.fromtimestamp(1772752582004 / 1000, tz=UTC)
    assert event.payload.symbol == "btc/usd"
    assert event.payload.timestamp == 1772752581815
    assert event.payload.window_seconds == window_seconds
    assert event.payload.value == Decimal("65000.123456789012345678")
    assert "full_accuracy_value" not in event.payload.model_dump()
    assert "window_s" not in event.payload.model_dump()


@pytest.mark.parametrize(
    ("wire_topic", "window_seconds"),
    [
        ("crypto_prices_twap_thirty", 60),
        ("crypto_prices_twap_sixty", 30),
    ],
)
def test_crypto_chainlink_twap_rejects_wire_topic_window_mismatch(
    wire_topic: str, window_seconds: int
) -> None:
    with pytest.raises(ValueError, match="requires window_s"):
        parse_rtds_event(
            {
                **_CRYPTO_CHAINLINK_TWAP,
                "topic": wire_topic,
                "payload": {
                    **_CRYPTO_CHAINLINK_TWAP["payload"],
                    "window_s": window_seconds,
                },
            }
        )


@pytest.mark.parametrize("window_seconds", ["30", 30.0, True, None])
def test_crypto_chainlink_twap_requires_an_integer_wire_window(window_seconds: object) -> None:
    with pytest.raises(ValueError, match="requires window_s"):
        parse_rtds_event(
            {
                **_CRYPTO_CHAINLINK_TWAP,
                "payload": {
                    **_CRYPTO_CHAINLINK_TWAP["payload"],
                    "window_s": window_seconds,
                },
            }
        )


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("0", "0"),
        ("-0", "0"),
        ("1", "0.000000000000000001"),
        ("-1", "-0.000000000000000001"),
        ("1000000000000000000", "1"),
        ("-1000000000000000000", "-1"),
        ("1230000000000000000", "1.23"),
        (
            "1234567890123456789012345678901234567890",
            "1234567890123456789012.345678901234567890",
        ),
    ],
)
def test_crypto_chainlink_twap_normalizes_signed_e18_boundaries(
    raw_value: str, expected: str
) -> None:
    event = parse_rtds_event(
        {
            **_CRYPTO_CHAINLINK_TWAP,
            "payload": {
                **_CRYPTO_CHAINLINK_TWAP["payload"],
                "full_accuracy_value": raw_value,
            },
        }
    )

    assert isinstance(event, CryptoPricesChainlinkTwapEvent)
    assert event.payload.value == Decimal(expected)
    if raw_value == "-0":
        assert event.payload.value.is_signed() is False


@pytest.mark.parametrize("full_accuracy_value", [None, "1.2", "1e18", "+1", "", 1])
def test_crypto_chainlink_twap_requires_signed_integer_full_accuracy_value(
    full_accuracy_value: object,
) -> None:
    payload = dict(_CRYPTO_CHAINLINK_TWAP["payload"])
    if full_accuracy_value is None:
        payload.pop("full_accuracy_value")
    else:
        payload["full_accuracy_value"] = full_accuracy_value

    with pytest.raises(ValueError):
        parse_rtds_event({**_CRYPTO_CHAINLINK_TWAP, "payload": payload})


def test_crypto_chainlink_twap_raw_shape_cannot_bypass_exact_value_requirement() -> None:
    payload = dict(_CRYPTO_CHAINLINK_TWAP["payload"])
    payload.pop("full_accuracy_value")
    payload["window_seconds"] = 30

    with pytest.raises(ValueError, match="full_accuracy_value is required"):
        parse_rtds_event({**_CRYPTO_CHAINLINK_TWAP, "payload": payload})


@pytest.mark.parametrize("display_value", [None, True, object()])
def test_crypto_chainlink_twap_still_validates_display_value(display_value: object) -> None:
    payload = dict(_CRYPTO_CHAINLINK_TWAP["payload"])
    if display_value is None:
        payload.pop("value")
    else:
        payload["value"] = display_value

    with pytest.raises(ValueError):
        parse_rtds_event({**_CRYPTO_CHAINLINK_TWAP, "payload": payload})


def test_crypto_chainlink_twap_payload_round_trips_public_shape() -> None:
    payload = CryptoPricesChainlinkTwapPayload(
        symbol="btc/usd",
        value=Decimal("65000.123456789012345678"),
        timestamp=1772752581815,
        window_seconds=30,
    )

    assert CryptoPricesChainlinkTwapPayload.model_validate(payload.model_dump()) == payload


def test_equity_update_parses_with_aliases() -> None:
    event = parse_rtds_event(_EQUITY_UPDATE)
    assert isinstance(event, EquityPricesUpdateEvent)
    assert event.topic == "prices.equity.pyth"
    assert event.payload.symbol == "AAPL"
    assert event.payload.received_at == 1710000000050
    assert event.payload.is_carried_forward is False


def test_equity_update_prefers_full_accuracy_value_when_present() -> None:
    from decimal import Decimal

    event = parse_rtds_event(
        {
            "topic": "equity_prices",
            "type": "update",
            "timestamp": "1710000000000",
            "payload": {
                "symbol": "AAPL",
                "value": 180.42,
                "full_accuracy_value": "180.42178100000",
                "timestamp": 1710000000000,
            },
        }
    )
    assert isinstance(event, EquityPricesUpdateEvent)
    assert event.payload.value == Decimal("180.42178100000")


def test_equity_update_falls_back_to_value_when_full_accuracy_missing() -> None:
    from decimal import Decimal

    event = parse_rtds_event(_EQUITY_UPDATE)
    assert isinstance(event, EquityPricesUpdateEvent)
    assert event.payload.value == Decimal("180.42")


def test_equity_subscribe_parses_snapshot_data() -> None:
    event = parse_rtds_event(_EQUITY_SUBSCRIBE)
    assert isinstance(event, EquityPricesSubscribeEvent)
    assert event.topic == "prices.equity.pyth"
    assert event.payload.symbol == "AAPL"
    assert len(event.payload.data) == 2
    assert event.payload.data[0].timestamp == 1710000000000


def test_unknown_wire_topic_raises() -> None:
    with pytest.raises(ValueError, match="unknown RTDS wire topic"):
        parse_rtds_event({"topic": "made_up", "type": "update", "timestamp": "1", "payload": {}})


def test_unknown_event_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown RTDS event"):
        parse_rtds_event({"topic": "comments", "type": "made_up", "timestamp": "1", "payload": {}})


def test_missing_topic_raises() -> None:
    with pytest.raises(ValueError, match="missing topic"):
        parse_rtds_event({"type": "update", "payload": {}})


def test_non_dict_raises() -> None:
    with pytest.raises(ValueError, match="expected dict"):
        parse_rtds_event("not a dict")
