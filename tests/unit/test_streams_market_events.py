import inspect
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args, get_origin, get_type_hints

import pytest
from pydantic import ValidationError

from polymarket.models.clob.market_events import (
    MarketBestBidAskEvent,
    MarketBestBidAskPayload,
    MarketBookEvent,
    MarketBookPayload,
    MarketEvent,
    MarketLastTradePriceEvent,
    MarketLastTradePricePayload,
    MarketPriceChangeEvent,
    MarketResolvedEvent,
    MarketTickSizeChangeEvent,
    NewMarketEvent,
    PriceChange,
    parse_market_event,
)

_BOOK: dict[str, Any] = {
    "event_type": "book",
    "market": "0xmarket",
    "asset_id": "token-a",
    "bids": [{"price": "0.49", "size": "100"}],
    "asks": [{"price": "0.51", "size": "100"}],
    "hash": None,
    "timestamp": "1710000000000",
}

_PRICE_CHANGE: dict[str, Any] = {
    "event_type": "price_change",
    "market": "0xmarket",
    "price_changes": [
        {
            "asset_id": "token-a",
            "price": "0.50",
            "size": "10",
            "side": "BUY",
            "best_bid": "0.49",
            "best_ask": "0.51",
        }
    ],
    "timestamp": "1710000000000",
}

_LAST_TRADE: dict[str, Any] = {
    "event_type": "last_trade_price",
    "market": "0xmarket",
    "asset_id": "token-a",
    "price": "0.50",
    "size": "5",
    "side": "SELL",
    "fee_rate_bps": "0.05",
    "timestamp": "1710000000000",
    "transaction_hash": "0xhash",
}

_TICK: dict[str, Any] = {
    "event_type": "tick_size_change",
    "market": "0xmarket",
    "asset_id": "token-a",
    "old_tick_size": "0.01",
    "new_tick_size": "0.001",
    "timestamp": "1710000000000",
}

_BBA: dict[str, Any] = {
    "event_type": "best_bid_ask",
    "market": "0xmarket",
    "asset_id": "token-a",
    "best_bid": "0.49",
    "best_ask": "0.51",
    "spread": "0.02",
    "timestamp": "1710000000000",
}

_NEW_MARKET: dict[str, Any] = {
    "event_type": "new_market",
    "id": "evt-1",
    "market": "0xmarket",
    "condition_id": "0x" + "11" * 32,
    "question": "Will X happen?",
    "assets_ids": ["token-a", "token-b"],
    "active": True,
    "timestamp": "1710000000000",
}

_RESOLVED: dict[str, Any] = {
    "event_type": "market_resolved",
    "id": "evt-1",
    "market": "0xmarket",
    "assets_ids": ["token-a", "token-b"],
    "winning_asset_id": "token-a",
    "winning_outcome": "Yes",
    "timestamp": "1710000000000",
}


def test_event_envelope_has_topic_and_event_type_at_top_level() -> None:
    event = parse_market_event(_BOOK)
    assert event.topic == "market"
    assert event.type == "book"
    assert event.payload is not None


@pytest.mark.parametrize(
    ("wire", "expected_event_type"),
    [
        (_BOOK, "book"),
        (_PRICE_CHANGE, "price_change"),
        (_LAST_TRADE, "last_trade_price"),
        (_TICK, "tick_size_change"),
        (_BBA, "best_bid_ask"),
        (_NEW_MARKET, "new_market"),
        (_RESOLVED, "market_resolved"),
    ],
)
def test_every_variant_has_uniform_envelope_shape(
    wire: dict[str, Any], expected_event_type: str
) -> None:
    event = parse_market_event(wire)
    assert event.topic == "market"
    assert event.type == expected_event_type
    assert event.payload is not None


def test_envelope_roundtrip_through_model_dump_and_validate() -> None:
    original = parse_market_event(_BOOK)
    dumped = original.model_dump()
    restored = parse_market_event(dumped)
    assert restored.topic == original.topic
    assert restored.type == original.type
    assert restored.payload.market == original.payload.market  # type: ignore[union-attr]


def test_book_event_parses_with_asset_id_aliased_to_token_id() -> None:
    event = parse_market_event(_BOOK)
    assert isinstance(event, MarketBookEvent)
    assert event.payload.token_id == "token-a"
    assert event.payload.market == "0xmarket"
    assert len(event.payload.bids) == 1


def test_price_change_event_parses_nested_changes() -> None:
    event = parse_market_event(_PRICE_CHANGE)
    assert isinstance(event, MarketPriceChangeEvent)
    assert len(event.payload.price_changes) == 1
    assert event.payload.price_changes[0].token_id == "token-a"
    assert event.payload.price_changes[0].side == "BUY"


def test_last_trade_price_event_parses() -> None:
    event = parse_market_event(_LAST_TRADE)
    assert isinstance(event, MarketLastTradePriceEvent)
    assert event.payload.token_id == "token-a"
    assert event.payload.transaction_hash == "0xhash"


def test_tick_size_change_event_parses() -> None:
    event = parse_market_event(_TICK)
    assert isinstance(event, MarketTickSizeChangeEvent)
    assert event.payload.token_id == "token-a"


def test_best_bid_ask_event_parses() -> None:
    event = parse_market_event(_BBA)
    assert isinstance(event, MarketBestBidAskEvent)
    assert event.payload.token_id == "token-a"
    assert event.payload.spread is not None


def test_new_market_event_parses_with_assets_ids_aliased() -> None:
    event = parse_market_event(_NEW_MARKET)
    assert isinstance(event, NewMarketEvent)
    assert event.payload.market == "0xmarket"
    assert event.payload.condition_id == "0x" + "11" * 32
    assert event.payload.token_ids == ("token-a", "token-b")
    assert event.payload.active is True


def test_market_resolved_event_parses_winning_asset_id_alias() -> None:
    event = parse_market_event(_RESOLVED)
    assert isinstance(event, MarketResolvedEvent)
    assert event.payload.winning_token_id == "token-a"
    assert event.payload.token_ids == ("token-a", "token-b")


def test_discriminator_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError):
        parse_market_event({"event_type": "unknown_event", "market": "x"})


def test_missing_required_field_raises() -> None:
    payload = dict(_BOOK)
    del payload["asset_id"]
    with pytest.raises(ValidationError):
        parse_market_event(payload)


def test_order_side_normalized_to_uppercase() -> None:
    payload = dict(_LAST_TRADE) | {"side": "sell"}
    event = parse_market_event(payload)
    assert isinstance(event, MarketLastTradePriceEvent)
    assert event.payload.side == "SELL"


def test_order_side_normalized_in_nested_price_change() -> None:
    payload: dict[str, Any] = {
        **_PRICE_CHANGE,
        "price_changes": [
            {
                "asset_id": "token-a",
                "price": "0.5",
                "size": "10",
                "side": "buy",
            }
        ],
    }
    event = parse_market_event(payload)
    assert isinstance(event, MarketPriceChangeEvent)
    assert event.payload.price_changes[0].side == "BUY"


def test_timestamp_parsed_to_utc_datetime() -> None:
    from datetime import UTC, datetime

    event = parse_market_event(_BOOK)
    assert isinstance(event, MarketBookEvent)
    assert event.payload.timestamp == datetime.fromtimestamp(1710000000, tz=UTC)
    assert event.payload.timestamp is not None
    assert event.payload.timestamp.tzinfo is UTC


def test_empty_string_timestamp_normalized_to_none() -> None:
    payload = dict(_BOOK) | {"timestamp": ""}
    event = parse_market_event(payload)
    assert isinstance(event, MarketBookEvent)
    assert event.payload.timestamp is None


def test_invalid_timestamp_raises_validation_error() -> None:
    payload = dict(_BOOK) | {"timestamp": "not-a-number"}
    with pytest.raises(ValidationError):
        parse_market_event(payload)


@pytest.mark.parametrize(
    "bad_value",
    [
        "-1710000000000",  # negative
        "+1710000000000",  # signed
        " 1710000000000",  # leading whitespace
        "1710000000000 ",  # trailing whitespace
        "1.7e12",  # scientific
        "1710000000000.0",  # decimal
        "0x123",  # hex
    ],
)
def test_loose_numeric_strings_rejected_as_epoch_ms(bad_value: str) -> None:
    payload = dict(_BOOK) | {"timestamp": bad_value}
    with pytest.raises(ValidationError):
        parse_market_event(payload)


def test_new_market_game_start_time_parsed_to_datetime() -> None:
    from datetime import UTC, datetime

    payload = dict(_NEW_MARKET) | {"game_start_time": "1710000000000"}
    event = parse_market_event(payload)
    assert isinstance(event, NewMarketEvent)
    assert event.payload.game_start_time == datetime.fromtimestamp(1710000000, tz=UTC)


def test_last_trade_empty_string_fee_rate_bps_parsed_as_none() -> None:
    payload = dict(_LAST_TRADE) | {"fee_rate_bps": ""}
    event = parse_market_event(payload)
    assert isinstance(event, MarketLastTradePriceEvent)
    assert event.payload.fee_rate_bps is None


def test_price_change_empty_string_best_bid_ask_parsed_as_none() -> None:
    # The wire sends "" for best_bid/best_ask when they are absent.
    price_change = dict(_PRICE_CHANGE["price_changes"][0]) | {"best_bid": "", "best_ask": ""}
    payload = dict(_PRICE_CHANGE) | {"price_changes": [price_change]}
    event = parse_market_event(payload)
    assert isinstance(event, MarketPriceChangeEvent)
    assert event.payload.price_changes[0].best_bid is None
    assert event.payload.price_changes[0].best_ask is None


def test_best_bid_ask_empty_strings_parsed_as_none() -> None:
    payload = dict(_BBA) | {"best_bid": "", "best_ask": "", "spread": ""}
    event = parse_market_event(payload)
    assert isinstance(event, MarketBestBidAskEvent)
    assert event.payload.best_bid is None
    assert event.payload.best_ask is None
    assert event.payload.spread is None


def test_empty_string_required_decimal_rejected() -> None:
    # "" only means absent for optional decimals; required ones stay strict.
    payload = dict(_LAST_TRADE) | {"price": ""}
    with pytest.raises(ValidationError):
        parse_market_event(payload)


def test_market_payload_annotations_expose_canonical_types() -> None:
    price_change_hints = get_type_hints(PriceChange, include_extras=True)
    assert price_change_hints["price"] is Decimal
    assert price_change_hints["best_bid"] == (Decimal | None)
    assert price_change_hints["side"] == Literal["BUY", "SELL"]

    book_hints = get_type_hints(MarketBookPayload, include_extras=True)
    assert book_hints["timestamp"] == (datetime | None)
    assert book_hints["tick_size"] == (Decimal | None)


def test_market_payload_constructor_signatures_expose_canonical_types() -> None:
    price_change_parameters = inspect.signature(PriceChange).parameters
    assert price_change_parameters["price"].annotation is Decimal
    assert price_change_parameters["best_bid"].annotation == (Decimal | None)
    assert price_change_parameters["side"].annotation == Literal["BUY", "SELL"]

    last_trade_parameters = inspect.signature(MarketLastTradePricePayload).parameters
    assert last_trade_parameters["timestamp"].annotation == (datetime | None)
    assert last_trade_parameters["fee_rate_bps"].annotation == (Decimal | None)


def test_market_event_keeps_discriminated_union_metadata() -> None:
    assert get_origin(MarketEvent) is Annotated
    event_union, metadata = get_args(MarketEvent)
    assert get_args(event_union) == (
        MarketBookEvent,
        MarketPriceChangeEvent,
        MarketLastTradePriceEvent,
        MarketTickSizeChangeEvent,
        MarketBestBidAskEvent,
        NewMarketEvent,
        MarketResolvedEvent,
    )
    assert metadata.discriminator == "type"


def test_optional_market_decimal_annotations_are_consistent() -> None:
    hints = get_type_hints(MarketBestBidAskPayload, include_extras=True)
    assert hints["best_bid"] == (Decimal | None)
    assert hints["best_ask"] == (Decimal | None)
    assert hints["spread"] == (Decimal | None)
