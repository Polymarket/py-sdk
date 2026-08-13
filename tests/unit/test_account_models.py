import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from polymarket.errors import UnexpectedResponseError
from polymarket.models import Notification, NotificationType
from polymarket.models.clob.account import (
    BalanceAllowance,
    ClobTrade,
    MakerOrder,
    OpenOrder,
    TradeStatus,
)
from polymarket.models.clob.notifications import (
    ChildCommentCreatedNotification,
    MarketResolvedNotification,
    OrderCancellationNotification,
    OrderFillNotification,
    RewardPayoutNotification,
)

_NOTIFICATION_ADAPTER: TypeAdapter[Notification] = TypeAdapter(Notification)


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


def test_account_model_annotations_are_canonical() -> None:
    expected = {
        OpenOrder: {
            "price": Decimal,
            "original_size": Decimal,
            "size_matched": Decimal,
            "created_at": datetime,
            "expires_at": datetime | None,
        },
        MakerOrder: {
            "price": Decimal,
            "matched_amount": Decimal,
            "fee_rate_bps": Decimal | None,
        },
        ClobTrade: {
            "price": Decimal,
            "size": Decimal,
            "status": TradeStatus,
            "fee_rate_bps": Decimal,
            "matched_at": datetime,
            "updated_at": datetime,
        },
        OrderFillNotification: {"timestamp": datetime},
    }

    for model, fields in expected.items():
        hints = get_type_hints(model, include_extras=True)
        for field, annotation in fields.items():
            assert hints[field] == annotation
            assert model.model_fields[field].annotation == annotation


def test_account_model_signatures_use_canonical_annotations() -> None:
    expected = {
        OpenOrder: {
            "price": Decimal,
            "original_size": Decimal,
            "size_matched": Decimal,
            "created_at": datetime,
            "expiration": datetime | None,
        },
        MakerOrder: {
            "price": Decimal,
            "matched_amount": Decimal,
            "fee_rate_bps": Decimal | None,
        },
        ClobTrade: {
            "price": Decimal,
            "size": Decimal,
            "status": TradeStatus,
            "fee_rate_bps": Decimal,
            "match_time": datetime,
            "last_update": datetime,
        },
        OrderFillNotification: {"timestamp": datetime},
    }

    for model, fields in expected.items():
        parameters = inspect.signature(model).parameters
        for field, annotation in fields.items():
            assert parameters[field].annotation == annotation


@pytest.mark.parametrize("field", ["price", "original_size", "size_matched"])
def test_open_order_decimal_fields_require_strings_or_decimals(field: str) -> None:
    order = OpenOrder.parse_response(_open_order_payload(**{field: Decimal("1.25")}))
    assert getattr(order, field) == Decimal("1.25")

    with pytest.raises(UnexpectedResponseError):
        OpenOrder.parse_response(_open_order_payload(**{field: 1}))


@pytest.mark.parametrize("field", ["price", "matched_amount", "fee_rate_bps"])
def test_maker_order_decimal_fields_require_strings_or_decimals(field: str) -> None:
    maker = MakerOrder.parse_response(_maker_order_payload(**{field: Decimal("1.25")}))
    assert getattr(maker, field) == Decimal("1.25")

    with pytest.raises(UnexpectedResponseError):
        MakerOrder.parse_response(_maker_order_payload(**{field: 1}))


@pytest.mark.parametrize("field", ["price", "size", "fee_rate_bps"])
def test_clob_trade_decimal_fields_require_strings_or_decimals(field: str) -> None:
    trade = ClobTrade.parse_response(_clob_trade_payload(**{field: Decimal("1.25")}))
    assert getattr(trade, field) == Decimal("1.25")

    with pytest.raises(UnexpectedResponseError):
        ClobTrade.parse_response(_clob_trade_payload(**{field: 1}))


@pytest.mark.parametrize(
    "status",
    ["MATCHED", "MATCHED_NOT_BROADCASTED", "MINED", "CONFIRMED", "RETRYING", "FAILED"],
)
def test_clob_trade_normalizes_prefixed_statuses(status: TradeStatus) -> None:
    trade = ClobTrade.parse_response(_clob_trade_payload(status=f"TRADE_STATUS_{status}"))
    assert trade.status == status


def test_clob_trade_rejects_unknown_status() -> None:
    with pytest.raises(UnexpectedResponseError):
        ClobTrade.parse_response(_clob_trade_payload(status="TRADE_STATUS_UNKNOWN"))


@pytest.mark.parametrize("created_at", [None, ""])
def test_open_order_requires_created_at(created_at: object) -> None:
    with pytest.raises(UnexpectedResponseError):
        OpenOrder.parse_response(_open_order_payload(created_at=created_at))


@pytest.mark.parametrize("field", ["match_time", "last_update"])
@pytest.mark.parametrize("value", [None, ""])
def test_clob_trade_requires_timestamps(field: str, value: object) -> None:
    with pytest.raises(UnexpectedResponseError):
        ClobTrade.parse_response(_clob_trade_payload(**{field: value}))


@pytest.mark.parametrize("timestamp", [None, ""])
def test_notification_requires_timestamp(timestamp: object) -> None:
    with pytest.raises(ValidationError):
        _NOTIFICATION_ADAPTER.validate_python(
            _notification(
                NotificationType.ORDER_FILL,
                _order_notification_payload(),
                timestamp=timestamp,
            )
        )


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


_CONDITION_ID = "0x" + "cc" * 32
_TRANSACTION_HASH = "0x" + "dd" * 32
_PROXY_WALLET = "0x" + "ee" * 20


def _order_notification_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "asset_id": "8501497",
        "eventSlug": "event-slug",
        "icon": "https://example.com/icon.png",
        "image": "https://example.com/image.png",
        "market": _CONDITION_ID,
        "market_slug": "market-slug",
        "matched_size": "10",
        "order_id": "0x" + "ab" * 32,
        "original_size": "100",
        "outcome": "YES",
        "outcome_index": 0,
        "owner": "f4f247b7-4ac7-ff29-a152-04fda0a8755a",
        "price": "0.6",
        "question": "Will it happen?",
        "remaining_size": "90",
        "seriesSlug": "",
        "side": "SELL",
        "trade_id": "trade-1",
        "transaction_hash": _TRANSACTION_HASH,
        "type": "GTC",
    }
    base.update(overrides)
    return base


def _notification(type_: int, payload: object, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": type_,
        "owner": "f4f247b7-4ac7-ff29-a152-04fda0a8755a",
        "payload": payload,
        "timestamp": 1700000000000,
        "type": type_,
    }
    base.update(overrides)
    return base


def test_order_fill_notification_normalizes_payload() -> None:
    notification = _NOTIFICATION_ADAPTER.validate_python(
        _notification(NotificationType.ORDER_FILL, _order_notification_payload())
    )
    assert isinstance(notification, OrderFillNotification)
    assert notification.type == NotificationType.ORDER_FILL
    assert notification.timestamp == datetime.fromtimestamp(1700000000, tz=UTC)
    assert notification.payload.token_id == "8501497"
    assert notification.payload.condition_id == _CONDITION_ID
    assert notification.payload.order_type == "GTC"
    assert notification.payload.matched_size == Decimal("10")
    assert notification.payload.transaction_hash == _TRANSACTION_HASH


def test_order_cancellation_notification_maps_empty_transaction_fields_to_none() -> None:
    notification = _NOTIFICATION_ADAPTER.validate_python(
        _notification(
            NotificationType.ORDER_CANCELLATION,
            _order_notification_payload(trade_id="", transaction_hash="", type=""),
            id="42",
        )
    )
    assert isinstance(notification, OrderCancellationNotification)
    assert notification.id == 42
    assert notification.payload.transaction_hash is None
    assert notification.payload.trade_id is None
    assert notification.payload.order_type is None


def _market_notification_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "accepting_order_timestamp": None,
        "accepting_orders": True,
        "active": True,
        "archived": False,
        "closed": False,
        "condition_id": _CONDITION_ID,
        "description": "Resolves YES if it happens.",
        "enable_order_book": True,
        "end_date_iso": "2026-08-24",
        "eventSlug": "event-slug",
        "fpmm": "",
        "game_start_time": None,
        "icon": "https://example.com/icon.png",
        "image": "https://example.com/image.png",
        "is_50_50_outcome": False,
        "maker_base_fee": 0,
        "market_slug": "market-slug",
        "minimum_order_size": "15",
        "minimum_tick_size": "0.01",
        "neg_risk": False,
        "neg_risk_market_id": "",
        "neg_risk_request_id": "",
        "notifications_enabled": True,
        "question": "Will it happen?",
        "question_id": "0x" + "ab" * 32,
        "rewards": {
            "max_spread": 3.5,
            "min_size": 50,
            "rates": [
                {"asset_address": _PROXY_WALLET, "rewards_daily_rate": 5},
            ],
        },
        "seconds_delay": 0,
        "tags": ["Sports"],
        "taker_base_fee": 0,
        "tokens": [
            {"outcome": "Yes", "price": 0.6, "token_id": "1", "winner": False},
            {"outcome": "No", "price": 0.4, "token_id": "2", "winner": True},
        ],
    }
    base.update(overrides)
    return base


def test_market_resolved_notification_parses_market_payload() -> None:
    notification = _NOTIFICATION_ADAPTER.validate_python(
        _notification(NotificationType.MARKET_RESOLVED, _market_notification_payload())
    )
    assert isinstance(notification, MarketResolvedNotification)
    assert notification.payload.condition_id == _CONDITION_ID
    assert notification.payload.end_date == datetime(2026, 8, 24, tzinfo=UTC)
    assert notification.payload.tokens[1].winner is True
    assert notification.payload.rewards is not None
    assert notification.payload.rewards.rates is not None
    assert notification.payload.rewards.rates[0].daily_rate == Decimal("5")
    assert notification.payload.minimum_tick_size == Decimal("0.01")


@pytest.mark.parametrize("fee_field", ["maker_base_fee", "taker_base_fee"])
def test_market_notification_requires_base_fees(fee_field: str) -> None:
    payload = _market_notification_payload()
    del payload[fee_field]

    with pytest.raises(ValidationError):
        _NOTIFICATION_ADAPTER.validate_python(
            _notification(NotificationType.MARKET_RESOLVED, payload)
        )


def test_market_notification_allows_null_base_fees() -> None:
    notification = _NOTIFICATION_ADAPTER.validate_python(
        _notification(
            NotificationType.MARKET_RESOLVED,
            _market_notification_payload(maker_base_fee=None, taker_base_fee=None),
        )
    )
    assert isinstance(notification, MarketResolvedNotification)
    assert notification.payload.maker_base_fee is None
    assert notification.payload.taker_base_fee is None


def test_reward_payout_notification_parses_payload() -> None:
    notification = _NOTIFICATION_ADAPTER.validate_python(
        _notification(
            NotificationType.REWARD_PAYOUT,
            {
                "owner": "f4f247b7-4ac7-ff29-a152-04fda0a8755a",
                "proxyWallet": _PROXY_WALLET,
                "reward": 12.5,
                "txnHash": _TRANSACTION_HASH,
            },
        )
    )
    assert isinstance(notification, RewardPayoutNotification)
    assert notification.payload.proxy_wallet == _PROXY_WALLET
    assert notification.payload.reward == Decimal("12.5")
    assert notification.payload.transaction_hash == _TRANSACTION_HASH


def test_child_comment_notification_normalizes_profile_wallet() -> None:
    notification = _NOTIFICATION_ADAPTER.validate_python(
        _notification(
            NotificationType.CHILD_COMMENT_CREATED,
            {
                "body": "Nice call!",
                "createdAt": "2026-07-01T10:00:00Z",
                "eventSlug": "event-slug",
                "eventTitle": "Event title",
                "id": "123",
                "image": "https://example.com/profile.png",
                "parentCommentID": "99",
                "parentEntityID": 42,
                "parentEntityType": "Event",
                "profile": {
                    "baseAddress": _PROXY_WALLET,
                    "isCreator": False,
                    "isMod": False,
                    "name": "trader",
                    "proxyWallet": _PROXY_WALLET,
                },
                "userAddress": _PROXY_WALLET,
            },
        )
    )
    assert isinstance(notification, ChildCommentCreatedNotification)
    assert notification.payload.parent_comment_id == "99"
    assert notification.payload.parent_entity_type == "Event"
    assert notification.payload.profile is not None
    assert notification.payload.profile.wallet == _PROXY_WALLET


def test_notification_rejects_non_numeric_id() -> None:
    with pytest.raises(ValidationError):
        _NOTIFICATION_ADAPTER.validate_python(
            _notification(
                NotificationType.ORDER_FILL,
                _order_notification_payload(),
                id="not-a-number",
            )
        )


def test_notification_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        _NOTIFICATION_ADAPTER.validate_python(_notification(99, {}))


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
