from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.data import (
    BuilderVolumeEntry,
    ClosedPosition,
    ComboPosition,
    ComboRedeemActivity,
    Holder,
    LiveVolume,
    MetaHolder,
    OpenInterest,
    PortfolioValue,
    Position,
    TradedMarketCount,
)
from polymarket.models.data.activity import parse_combo_activity

_COMBO_CONDITION_ID = "0x032def24bfb0c5c57fb236fac08b94236a0000000000000000000000000000"
_CTF_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"


def _combo_position_payload(*, condition_id: str = _COMBO_CONDITION_ID) -> dict[str, Any]:
    return {
        "combo_condition_id": condition_id,
        "combo_position_id": "123",
        "side": "YES",
        "module_id": 3,
        "user_address": "0x0000000000000000000000000000000000000001",
        "shares_balance": "42.5",
        "entry_avg_price_usdc": "0.12",
        "entry_cost_usdc": "5.1",
        "gross_entry_cost_usdc": "5.123456",
        "entry_fees_usdc": "0.023456",
        "realized_payout_usdc": "6.25",
        "total_cost_usdc": "5.1",
        "status": "OPEN",
        "redeemable": False,
        "first_entry_at": "2026-06-01T12:00:00Z",
        "resolved_at": None,
        "updated_at": "2026-06-02T12:00:00Z",
        "legs_total": 2,
        "legs_resolved": 1,
        "legs_pending": 1,
        "legs": [
            {
                "leg_index": 0,
                "leg_position_id": "456",
                "leg_condition_id": _CTF_CONDITION_ID,
                "leg_outcome_index": 1,
                "leg_outcome_label": "Yes",
                "leg_status": "PARTIAL",
                "leg_resolved_at": None,
                "leg_current_price": "0.77",
                "market": {
                    "market_id": "789",
                    "slug": "market-slug",
                    "title": "Market title",
                    "outcome": "Yes",
                    "image_url": "https://example.test/image.png",
                    "icon_url": "https://example.test/icon.png",
                    "category": "Politics",
                    "subcategory": None,
                    "tags": ["a", "b"],
                    "end_date": "2026-07-01T00:00:00Z",
                    "event": {
                        "event_id": "event-1",
                        "event_slug": "event-slug",
                        "event_title": "Event title",
                        "event_image": "https://example.test/event.png",
                    },
                },
            }
        ],
    }


def test_live_volume_parses_total_and_markets() -> None:
    payload = {
        "total": "12345.67",
        "markets": [
            {"market": _CTF_CONDITION_ID, "value": "100.5"},
            {"market": _CTF_CONDITION_ID, "value": 200},
        ],
    }

    volume = LiveVolume.parse_response(payload)

    assert volume.total == Decimal("12345.67")
    assert volume.markets is not None
    assert len(volume.markets) == 2
    assert volume.markets[0].market == _CTF_CONDITION_ID
    assert volume.markets[0].value == Decimal("100.5")
    assert volume.markets[1].value == Decimal("200")


def test_live_volume_handles_missing_fields() -> None:
    volume = LiveVolume.parse_response({})

    assert volume.total is None
    assert volume.markets is None


def test_open_interest_parses_payload() -> None:
    interest = OpenInterest.parse_response({"market": _CTF_CONDITION_ID, "value": "1500"})

    assert interest.market == _CTF_CONDITION_ID
    assert interest.value == Decimal("1500")


def test_open_interest_accepts_global_market() -> None:
    interest = OpenInterest.parse_response({"market": "GLOBAL", "value": "1500"})

    assert interest.market == "GLOBAL"
    assert interest.value == Decimal("1500")


def test_holder_renames_proxy_wallet_and_asset() -> None:
    holder = Holder.parse_response(
        {
            "proxyWallet": "0xWALLET",
            "asset": "TOKEN_123",
            "amount": "42.5",
            "outcomeIndex": 1,
            "name": "Alice",
            "displayUsernamePublic": True,
        }
    )

    assert holder.wallet == "0xWALLET"
    assert holder.token_id == "TOKEN_123"
    assert holder.amount == Decimal("42.5")
    assert holder.outcome_index == 1
    assert holder.name == "Alice"
    assert holder.display_username_public is True


def test_meta_holder_nests_holders() -> None:
    payload = {
        "token": "TOKEN_123",
        "holders": [
            {"proxyWallet": "0xA", "asset": "TOKEN_123", "amount": "1"},
            {"proxyWallet": "0xB", "asset": "TOKEN_123", "amount": "2"},
        ],
    }

    meta = MetaHolder.parse_response(payload)

    assert meta.token == "TOKEN_123"
    assert meta.holders is not None
    assert len(meta.holders) == 2
    assert meta.holders[0].wallet == "0xA"


def test_portfolio_value_parses_user_and_value() -> None:
    value = PortfolioValue.parse_response({"user": "0xWALLET", "value": "9876.54"})

    assert value.user == "0xWALLET"
    assert value.value == Decimal("9876.54")


def test_traded_market_count_parses_payload() -> None:
    count = TradedMarketCount.parse_response({"user": "0xWALLET", "traded": 42})

    assert count.user == "0xWALLET"
    assert count.traded == 42


def test_position_empty_icon_normalizes_to_none() -> None:
    position = Position.parse_response({"conditionId": _CTF_CONDITION_ID, "icon": ""})

    assert position.icon is None


def test_position_keeps_populated_icon() -> None:
    position = Position.parse_response(
        {"conditionId": _CTF_CONDITION_ID, "icon": "https://example.test/icon.png"}
    )

    assert position.icon == "https://example.test/icon.png"


def test_closed_position_empty_icon_normalizes_to_none() -> None:
    position = ClosedPosition.parse_response({"conditionId": _CTF_CONDITION_ID, "icon": ""})

    assert position.icon is None


def test_builder_volume_entry_renames_dt_to_bucket_at() -> None:
    entry = BuilderVolumeEntry.parse_response(
        {
            "dt": "2026-05-08T00:00:00Z",
            "builder": "polymarket",
            "builderLogo": "https://example.test/logo.png",
            "verified": True,
            "volume": "1000.5",
            "activeUsers": 25,
            "rank": "1",
        }
    )

    assert entry.bucket_at == datetime(2026, 5, 8, tzinfo=UTC)
    assert entry.builder == "polymarket"
    assert entry.builder_logo == "https://example.test/logo.png"
    assert entry.verified is True
    assert entry.volume == Decimal("1000.5")
    assert entry.active_users == 25
    assert entry.rank == "1"


def test_builder_volume_entry_handles_missing_fields() -> None:
    entry = BuilderVolumeEntry.parse_response({})

    assert entry.bucket_at is None
    assert entry.builder is None
    assert entry.volume is None


def test_combo_position_parses_payload() -> None:
    payload = _combo_position_payload()

    combo = ComboPosition.parse_response(payload)

    assert combo.condition_id == payload["combo_condition_id"]
    assert combo.position_id == "123"
    assert combo.outcome == "YES"
    assert combo.wallet == "0x0000000000000000000000000000000000000001"
    assert combo.shares == Decimal("42.5")
    assert combo.gross_entry_cost_usdc == Decimal("5.123456")
    assert combo.entry_fees_usdc == Decimal("0.023456")
    assert combo.realized_payout_usdc == Decimal("6.25")
    assert combo.total_cost_usdc == Decimal("5.1")
    assert combo.status == "OPEN"
    assert combo.redeemable is False
    assert combo.updated_at == datetime(2026, 6, 2, 12, tzinfo=UTC)
    assert combo.legs[0].leg_position_id == "456"
    assert combo.legs[0].leg_current_price == Decimal("0.77")
    assert combo.legs[0].market is not None
    assert combo.legs[0].market.market_id == "789"
    assert combo.legs[0].market.event is not None
    assert combo.legs[0].market.event.event_slug == "event-slug"


def test_combo_position_normalizes_binary_wire_condition_id() -> None:
    combo = ComboPosition.parse_response(
        _combo_position_payload(condition_id=f"{_COMBO_CONDITION_ID}01")
    )

    assert combo.condition_id == _COMBO_CONDITION_ID


def test_combo_position_rejects_invalid_condition_id() -> None:
    with pytest.raises(UnexpectedResponseError, match="ComboPosition response"):
        ComboPosition.parse_response(_combo_position_payload(condition_id=_CTF_CONDITION_ID))


def test_combo_activity_parses_api_type_and_redeem_fields() -> None:
    payload = {
        "id": "tx:1",
        "type": "REDEEM",
        "user_address": "0x0000000000000000000000000000000000000001",
        "combo_condition_id": _COMBO_CONDITION_ID,
        "combo_position_id": "123",
        "module_id": 3,
        "amount_usdc": "4.5",
        "payout_usdc": "6.25",
        "timestamp": 1_797_360_000,
        "tx_dttm": "2026-06-01T12:00:00Z",
        "tx_hash": "0xabc",
        "log_index": 1,
        "block_number": 123456,
        "legs": _combo_position_payload()["legs"],
    }

    activity = parse_combo_activity(payload)

    assert isinstance(activity, ComboRedeemActivity)
    assert activity.type == "REDEEM"
    assert activity.condition_id == _COMBO_CONDITION_ID
    assert activity.position_id == "123"
    assert activity.wallet == "0x0000000000000000000000000000000000000001"
    assert activity.amount == Decimal("4.5")
    assert activity.payout == Decimal("6.25")


def test_open_interest_rejects_malformed_condition_id() -> None:
    with pytest.raises(UnexpectedResponseError, match="OpenInterest response"):
        OpenInterest.parse_response({"market": "0x1234", "value": "1500"})
