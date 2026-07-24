from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.clob.account import (
    BalanceAllowance,
    ClobTrade,
    MakerOrder,
    Notification,
    OpenOrder,
)


def _open_order_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "asset_id": "8501497",
        "associate_trades": ["trade-1"],
        "created_at": 1700000000000,
        "expiration": 1800000000,
        "id": "order-1",
        "maker_address": "0xMAKER",
        "market": "0xMARKET",
        "order_type": "GTC",
        "original_size": "100",
        "outcome": "Yes",
        "owner": "0xOWNER",
        "price": "0.5",
        "side": "BUY",
        "size_matched": "50",
        "status": "LIVE",
    }
    base.update(overrides)
    return base


def _maker_order_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "asset_id": "8501497",
        "fee_rate_bps": "10",
        "maker_address": "0xMAKER",
        "matched_amount": "5",
        "order_id": "order-1",
        "outcome": "Yes",
        "owner": "0xOWNER",
        "price": "0.5",
        "side": "BUY",
    }
    base.update(overrides)
    return base


def _clob_trade_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "asset_id": "8501497",
        "bucket_index": 7,
        "fee_rate_bps": "10",
        "id": "trade-1",
        "last_update": 1700000010000,
        "maker_address": "0xMAKER",
        "maker_orders": [_maker_order_payload()],
        "market": "0xMARKET",
        "match_time": 1700000000000,
        "outcome": "Yes",
        "owner": "0xOWNER",
        "price": "0.5",
        "side": "BUY",
        "size": "5",
        "status": "MINED",
        "taker_order_id": "order-2",
        "trader_side": "TAKER",
        "transaction_hash": "0xTX",
    }
    base.update(overrides)
    return base


def test_open_order_parses_epoch_ms_timestamps() -> None:
    order = OpenOrder.parse_response(_open_order_payload())
    assert order.created_at == datetime.fromtimestamp(1700000000, tz=UTC)
    assert order.expires_at == datetime.fromtimestamp(1800000000, tz=UTC)


def test_open_order_accepts_string_epoch_ms() -> None:
    order = OpenOrder.parse_response(_open_order_payload(created_at="1700000000000"))
    assert order.created_at == datetime.fromtimestamp(1700000000, tz=UTC)


def test_open_order_accepts_iso_string_with_z_suffix() -> None:
    order = OpenOrder.parse_response(_open_order_payload(created_at="2023-11-14T00:00:00Z"))
    assert order.created_at.tzinfo is not None


def test_open_order_treats_empty_expiration_as_none() -> None:
    order = OpenOrder.parse_response(_open_order_payload(expiration=""))
    assert order.expires_at is None


@pytest.mark.parametrize("expiration", [0, "0"])
def test_open_order_treats_zero_expiration_as_none(expiration: object) -> None:
    order = OpenOrder.parse_response(_open_order_payload(expiration=expiration))
    assert order.expires_at is None


def test_open_order_rejects_invalid_timestamp() -> None:
    with pytest.raises(UnexpectedResponseError):
        OpenOrder.parse_response(_open_order_payload(created_at="not-a-date"))


def test_open_order_rejects_unknown_side() -> None:
    with pytest.raises(UnexpectedResponseError):
        OpenOrder.parse_response(_open_order_payload(side="HOLD"))


def test_open_order_defaults_associate_trades_to_empty_tuple() -> None:
    payload = _open_order_payload()
    payload.pop("associate_trades")
    order = OpenOrder.parse_response(payload)
    assert order.associate_trades == ()


def test_maker_order_validates_required_fields() -> None:
    maker = MakerOrder.parse_response(_maker_order_payload())
    assert maker.order_id == "order-1"
    assert maker.token_id == "8501497"
    assert maker.matched_amount == Decimal("5")


def test_clob_trade_rejects_out_of_range_epoch_for_match_time() -> None:
    with pytest.raises(UnexpectedResponseError):
        ClobTrade.parse_response(_clob_trade_payload(match_time=10**18))


def test_clob_trade_rejects_negative_epoch_string_for_match_time() -> None:
    # The shared epoch parser accepts only unsigned digit strings; a negative-string
    # epoch is rejected (trade timestamps are never negative).
    with pytest.raises(UnexpectedResponseError):
        ClobTrade.parse_response(_clob_trade_payload(match_time="-1"))


def test_clob_trade_parses_match_and_last_update() -> None:
    trade = ClobTrade.parse_response(_clob_trade_payload())
    assert trade.matched_at == datetime.fromtimestamp(1700000000, tz=UTC)
    assert trade.updated_at == datetime.fromtimestamp(1700000010, tz=UTC)


def test_clob_trade_parses_epoch_seconds_strings_from_live_api() -> None:
    payload = _clob_trade_payload(match_time="1778445523", last_update="1778445531")
    trade = ClobTrade.parse_response(payload)
    assert trade.matched_at == datetime.fromtimestamp(1778445523, tz=UTC)
    assert trade.updated_at == datetime.fromtimestamp(1778445531, tz=UTC)


def test_maker_order_accepts_empty_fee_rate_bps_as_none() -> None:
    payload = _clob_trade_payload()
    payload["maker_orders"] = [_maker_order_payload(fee_rate_bps="")]
    trade = ClobTrade.parse_response(payload)
    assert trade.maker_orders[0].fee_rate_bps is None


def test_clob_trade_rejects_invalid_trader_side() -> None:
    with pytest.raises(UnexpectedResponseError):
        ClobTrade.parse_response(_clob_trade_payload(trader_side="HYBRID"))


def test_clob_trade_parses_nested_maker_orders() -> None:
    trade = ClobTrade.parse_response(_clob_trade_payload())
    assert len(trade.maker_orders) == 1
    assert trade.maker_orders[0].order_id == "order-1"


def test_notification_parses_epoch_ms_timestamp() -> None:
    notification = Notification.parse_response(
        {
            "id": 1,
            "owner": "0xOWNER",
            "type": 0,
            "payload": {"key": "value"},
            "timestamp": 1700000000000,
        }
    )
    assert notification.id == 1
    assert notification.timestamp == datetime.fromtimestamp(1700000000, tz=UTC)
    assert notification.payload == {"key": "value"}


def test_notification_accepts_numeric_string_id() -> None:
    notification = Notification.parse_response(
        {
            "id": "42",
            "owner": "0xOWNER",
            "type": 1,
            "payload": None,
            "timestamp": 1700000000000,
        }
    )
    assert notification.id == 42


def test_notification_rejects_non_numeric_id() -> None:
    with pytest.raises(UnexpectedResponseError):
        Notification.parse_response(
            {
                "id": "not-a-number",
                "owner": "0xOWNER",
                "type": 1,
                "payload": None,
                "timestamp": 1700000000000,
            }
        )


def test_notification_allows_null_payload() -> None:
    notification = Notification.parse_response(
        {
            "id": 99,
            "owner": "0xOWNER",
            "type": 1,
            "payload": None,
            "timestamp": 1700000000000,
        }
    )
    assert notification.payload is None


def test_open_order_assumes_utc_for_naive_iso_string() -> None:
    order = OpenOrder.parse_response(_open_order_payload(created_at="2023-11-14T00:00:00"))
    assert order.created_at.tzinfo is not None
    assert order.created_at == datetime(2023, 11, 14, 0, 0, 0, tzinfo=UTC)


def test_balance_allowance_parses_string_base_units() -> None:
    ba = BalanceAllowance.parse_response(
        {
            "balance": "1000000",
            "allowances": {"0xCTF": "500000", "0xEXCHANGE": "750000"},
        }
    )
    assert ba.balance == 1000000
    assert ba.allowances == {"0xCTF": 500000, "0xEXCHANGE": 750000}


def test_balance_allowance_accepts_int_values() -> None:
    ba = BalanceAllowance.parse_response({"balance": 1234, "allowances": {"0xCTF": 99}})
    assert ba.balance == 1234
    assert ba.allowances == {"0xCTF": 99}


def test_balance_allowance_rejects_non_numeric_balance() -> None:
    with pytest.raises(UnexpectedResponseError):
        BalanceAllowance.parse_response({"balance": "not-a-number", "allowances": {}})


def test_balance_allowance_rejects_non_mapping_allowances() -> None:
    with pytest.raises(UnexpectedResponseError):
        BalanceAllowance.parse_response({"balance": "0", "allowances": [("0xCTF", "1")]})


def test_balance_allowance_rejects_bool_balance() -> None:
    with pytest.raises(UnexpectedResponseError):
        BalanceAllowance.parse_response({"balance": True, "allowances": {}})
