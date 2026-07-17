from typing import Any

import pytest
from pydantic import ValidationError

from polymarket.models.clob.user_events import (
    UserOrderEvent,
    UserTradeEvent,
    parse_user_event,
    parse_user_events,
)

_ORDER_PLACEMENT: dict[str, Any] = {
    "event_type": "order",
    "id": "ord-1",
    "owner": "0xowner",
    "market": "0xMARKET",
    "asset_id": "token-1",
    "side": "buy",
    "original_size": "100.0",
    "size_matched": "0.0",
    "price": "0.50",
    "type": "PLACEMENT",
    "timestamp": "1710000000000",
    "created_at": 1710000000,
    "expiration": 1730000000,
    "status": "LIVE",
    "order_type": "GTC",
    "maker_address": "0xmaker",
    "order_owner": "0xorderowner",
    "associate_trades": ["trade-1", "trade-2"],
}

_TRADE: dict[str, Any] = {
    "event_type": "trade",
    "type": "TRADE",
    "id": "trd-1",
    "taker_order_id": "ord-9",
    "market": "0xMARKET",
    "asset_id": "token-1",
    "side": "SELL",
    "size": "10.0",
    "price": "0.51",
    "status": "MATCHED",
    "owner": "0xowner",
    "timestamp": "1710000000000",
    "fee_rate_bps": "25",
    "match_time": 1710000000,
    "trader_side": "taker",
    "maker_orders": [
        {
            "order_id": "ord-X",
            "owner": "0xother",
            "matched_amount": "10",
            "price": "0.51",
            "asset_id": "token-1",
            "side": "BUY",
        }
    ],
}


def test_order_placement_parses_with_normalized_envelope() -> None:
    event = parse_user_event(_ORDER_PLACEMENT)
    assert isinstance(event, UserOrderEvent)
    assert event.topic == "user"
    assert event.type == "order"
    assert event.payload.id == "ord-1"
    assert event.payload.order_event_type == "PLACEMENT"
    assert event.payload.token_id == "token-1"
    assert event.payload.side == "BUY"
    assert event.payload.original_size == 100  # noqa: PLR2004
    assert event.payload.status == "LIVE"
    assert event.payload.order_type == "GTC"
    assert event.payload.associate_trades == ("trade-1", "trade-2")


def test_order_side_normalized_to_upper() -> None:
    event = parse_user_event({**_ORDER_PLACEMENT, "side": "sell"})
    assert isinstance(event, UserOrderEvent)
    assert event.payload.side == "SELL"


def test_order_timestamp_accepts_epoch_seconds() -> None:
    from datetime import UTC, datetime

    event = parse_user_event({**_ORDER_PLACEMENT, "timestamp": "1672290701"})
    assert isinstance(event, UserOrderEvent)
    assert event.payload.timestamp == datetime.fromtimestamp(1672290701, tz=UTC)


def test_order_timestamp_accepts_epoch_milliseconds() -> None:
    from datetime import UTC, datetime

    event = parse_user_event({**_ORDER_PLACEMENT, "timestamp": "1710000000000"})
    assert isinstance(event, UserOrderEvent)
    assert event.payload.timestamp == datetime.fromtimestamp(1710000000.0, tz=UTC)


def test_order_seconds_fields_parsed_from_wire() -> None:
    from datetime import UTC, datetime

    event = parse_user_event(
        {**_ORDER_PLACEMENT, "created_at": "1710000000", "expiration": "1730000000"}
    )
    assert isinstance(event, UserOrderEvent)
    assert event.payload.created_at == datetime.fromtimestamp(1710000000, tz=UTC)
    assert event.payload.expires_at == datetime.fromtimestamp(1730000000, tz=UTC)


def test_order_expires_at_zero_becomes_none() -> None:
    event = parse_user_event({**_ORDER_PLACEMENT, "expiration": "0"})
    assert isinstance(event, UserOrderEvent)
    assert event.payload.expires_at is None


def test_trade_timestamp_accepts_epoch_seconds() -> None:
    from datetime import UTC, datetime

    event = parse_user_event({**_TRADE, "timestamp": "1672290701"})
    assert isinstance(event, UserTradeEvent)
    assert event.payload.timestamp == datetime.fromtimestamp(1672290701, tz=UTC)


def test_trade_timestamp_accepts_epoch_milliseconds() -> None:
    from datetime import UTC, datetime

    event = parse_user_event({**_TRADE, "timestamp": "1710000000000"})
    assert isinstance(event, UserTradeEvent)
    assert event.payload.timestamp == datetime.fromtimestamp(1710000000.0, tz=UTC)


def test_trade_seconds_fields_parsed_from_wire() -> None:
    from datetime import UTC, datetime

    event = parse_user_event({**_TRADE, "match_time": "1710000000", "last_update": "1710000050"})
    assert isinstance(event, UserTradeEvent)
    assert event.payload.matched_at == datetime.fromtimestamp(1710000000, tz=UTC)
    assert event.payload.updated_at == datetime.fromtimestamp(1710000050, tz=UTC)


def test_trade_matched_at_accepts_matchtime_alias() -> None:
    from datetime import UTC, datetime

    wire = {k: v for k, v in _TRADE.items() if k != "match_time"}
    wire["matchtime"] = "1710000000"
    event = parse_user_event(wire)
    assert isinstance(event, UserTradeEvent)
    assert event.payload.matched_at == datetime.fromtimestamp(1710000000, tz=UTC)


def test_trade_matched_at_prefers_match_time_when_both_aliases_present() -> None:
    from datetime import UTC, datetime

    event = parse_user_event({**_TRADE, "match_time": "1710000000", "matchtime": "9999999999"})
    assert isinstance(event, UserTradeEvent)
    assert event.payload.matched_at == datetime.fromtimestamp(1710000000, tz=UTC)


def test_trade_parses_with_maker_orders() -> None:
    event = parse_user_event(_TRADE)
    assert isinstance(event, UserTradeEvent)
    assert event.type == "trade"
    assert event.payload.status == "MATCHED"
    assert event.payload.trader_side == "TAKER"
    assert event.payload.maker_orders is not None
    assert len(event.payload.maker_orders) == 1
    assert event.payload.maker_orders[0].order_id == "ord-X"
    assert event.payload.maker_orders[0].token_id == "token-1"
    assert event.payload.maker_orders[0].side == "BUY"


def test_trade_status_long_form_normalized_to_short() -> None:
    event = parse_user_event({**_TRADE, "status": "TRADE_STATUS_CONFIRMED"})
    assert isinstance(event, UserTradeEvent)
    assert event.payload.status == "CONFIRMED"


def test_trade_status_short_form_passes_through() -> None:
    event = parse_user_event({**_TRADE, "status": "MINED"})
    assert isinstance(event, UserTradeEvent)
    assert event.payload.status == "MINED"


def test_unknown_event_type_raises() -> None:
    with pytest.raises(ValidationError):
        parse_user_event({**_ORDER_PLACEMENT, "event_type": "made_up"})


def test_missing_event_type_raises() -> None:
    payload = {k: v for k, v in _ORDER_PLACEMENT.items() if k != "event_type"}
    with pytest.raises(ValueError, match="missing event_type"):
        parse_user_event(payload)


def test_missing_required_field_raises() -> None:
    payload = {k: v for k, v in _ORDER_PLACEMENT.items() if k != "id"}
    with pytest.raises(ValidationError):
        parse_user_event(payload)


def test_pre_enveloped_input_passes_through() -> None:
    pre_enveloped = {
        "topic": "user",
        "type": "order",
        "payload": {k: v for k, v in _ORDER_PLACEMENT.items() if k != "event_type"},
    }
    event = parse_user_event(pre_enveloped)
    assert isinstance(event, UserOrderEvent)
    assert event.payload.id == "ord-1"


def test_parse_user_events_batches_arrays() -> None:
    events, unknown = parse_user_events([_ORDER_PLACEMENT, _TRADE])
    assert unknown == []
    assert len(events) == 2
    assert isinstance(events[0], UserOrderEvent)
    assert isinstance(events[1], UserTradeEvent)


def test_parse_user_events_drops_malformed() -> None:
    events, unknown = parse_user_events([_ORDER_PLACEMENT, {"bogus": True}, _TRADE])
    assert unknown == [{"bogus": True}]
    assert len(events) == 2


def test_trade_empty_string_fee_rate_bps_parsed_as_none() -> None:
    # The user channel sends "" when a trade carries no fee.
    event = parse_user_event({**_TRADE, "fee_rate_bps": ""})
    assert isinstance(event, UserTradeEvent)
    assert event.payload.fee_rate_bps is None


def test_trade_maker_order_empty_string_fee_rate_bps_parsed_as_none() -> None:
    maker_order = {**_TRADE["maker_orders"][0], "fee_rate_bps": ""}
    event = parse_user_event({**_TRADE, "maker_orders": [maker_order]})
    assert isinstance(event, UserTradeEvent)
    assert event.payload.maker_orders is not None
    assert event.payload.maker_orders[0].fee_rate_bps is None


def test_trade_fee_rate_bps_still_parsed_when_present() -> None:
    from decimal import Decimal

    event = parse_user_event(_TRADE)
    assert isinstance(event, UserTradeEvent)
    assert event.payload.fee_rate_bps == Decimal("25")


def test_trade_empty_string_required_decimal_rejected() -> None:
    # "" only means absent for optional decimals; required ones stay strict.
    with pytest.raises(ValidationError):
        parse_user_event({**_TRADE, "price": ""})


def test_trade_with_status_the_sdk_does_not_model_is_dropped() -> None:
    # A trade whose status the SDK does not model fails validation and is
    # returned as unrecognized, so streams drop the frame instead of failing.
    frame = {**_TRADE, "status": "TRADE_STATUS_FUTURE_STATUS"}
    events, unknown = parse_user_events([frame, _TRADE])
    assert len(events) == 1
    assert unknown == [frame]


def test_order_with_status_or_event_type_the_sdk_does_not_model_is_dropped() -> None:
    frame = {**_ORDER_PLACEMENT, "status": "FUTURE_STATUS", "type": "FUTURE_EVENT_TYPE"}
    events, unknown = parse_user_events([frame, _ORDER_PLACEMENT])
    assert len(events) == 1
    assert unknown == [frame]
