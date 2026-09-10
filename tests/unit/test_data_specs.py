from datetime import UTC, datetime
from typing import Any

import pytest

from polymarket import PublicClient
from polymarket._internal.actions import data
from polymarket._internal.data_params import build_distinct_condition_ids, to_epoch_seconds
from polymarket.errors import UserInputError
from polymarket.models.data import (
    ActivityType,
    ComboPositionStatus,
    PositionStatus,
    UserPnlInterval,
)
from polymarket.models.types import to_market_condition_id

CONDITION = "0x" + "ab" * 32
COMBO = "0x03" + "ab" * 30
WALLET = "0x" + "12" * 20


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("list_trades", {"condition_id": CONDITION, "event_id": 1}),
        ("list_trades", {"condition_id": ["0x" + f"{n:064x}" for n in range(21)]}),
        ("list_trades", {"page_size": 1001}),
        ("list_trades", {"page_size": True}),
        ("list_trades", {"page_size": 1.5}),
        ("list_trades", {"condition_id": "0x" + "a" * 62 + "_1"}),
        ("list_trades", {"filter_amount": -1}),
        ("list_activity", {"user": WALLET, "start": datetime(2026, 1, 1)}),
        ("list_activity", {"user": WALLET, "full_history": True, "end": 100}),
        ("list_positions", {}),
        ("list_positions", {"condition_id": [CONDITION, "0x" + "cd" * 32]}),
        ("list_positions", {"user": WALLET, "status": "CLOSED", "include_archived": True}),
        ("list_combo_positions", {"user": WALLET, "status": ["REDEEMABLE", "OPEN"]}),
        ("list_combo_positions", {"user": WALLET, "status": "OPEN,PARTIAL"}),
        ("list_combo_positions", {"user": WALLET, "updated_after": 100, "updated_before": 50}),
        ("list_combo_positions", {"user": WALLET, "condition_id": CONDITION}),
        (
            "list_market_holders",
            {"condition_ids": [CONDITION, "0x" + "cd" * 32], "include_pnl": True},
        ),
        (
            "list_market_holders",
            {"condition_ids": CONDITION, "include_pnl": True, "page_size": 101},
        ),
        ("list_price_history", {"asset_id": "1", "interval": "1w", "bucket_seconds": 60}),
        ("list_price_history", {"asset_id": "1", "start": 1, "end": 16 * 86400}),
        ("list_price_history", {"asset_id": "1", "start": 100, "end": 99}),
        ("list_price_history", {"asset_id": "1", "as_of": 253402300800}),
        ("list_price_history", {"asset_id": "1", "as_of": 100, "page_size": 10}),
        ("list_price_history", {"asset_id": "1", "as_of": 100, "interval": "1d"}),
        ("get_resolutions", {"condition_ids": []}),
        ("get_resolutions", {"condition_ids": COMBO}),
        ("get_resolutions", {"condition_ids": CONDITION, "event_ids": [1]}),
        ("get_event_live_volume", {"event_ids": [1, "2"]}),
        ("get_event_live_volume", {"event_ids": 1.5}),
        ("list_trades", {"condition_id": 123}),
        ("list_trades", {"user": ""}),
        ("list_positions", {"user": WALLET, "status": "open"}),
        ("list_activity", {"user": WALLET, "activity_types": "TRADE"}),
        ("list_activity", {"user": WALLET, "activity_types": ActivityType.TRADE}),
        ("list_trader_leaderboard", {"category": ""}),
        ("list_biggest_winners", {"category": ""}),
        ("get_trader_leaderboard_standing", {"user": WALLET, "category": ""}),
        ("get_builder_volumes", {"bucket_limit": 91}),
    ],
)
def test_validation_before_transport(method: str, kwargs: dict[str, Any]) -> None:
    with PublicClient() as client, pytest.raises(UserInputError):
        getattr(client, method)(**kwargs)


def test_query_contracts() -> None:
    assert data.build_get_user_stats_spec(user=WALLET).params == {"user": WALLET}
    assert data.build_get_portfolio_value_spec(user=WALLET, condition_ids=CONDITION).params == {
        "user": WALLET,
        "condition_id": CONDITION,
    }
    assert data.list_positions_spec(
        user=WALLET, status="CLOSED", include_archived=False
    ).base_params == {"user": WALLET, "status": "CLOSED", "include_archived": False}
    assert data.build_list_market_holders_spec(condition_ids=CONDITION).base_params == {
        "condition_id": CONDITION
    }
    assert data.build_get_resolutions_spec(condition_ids=CONDITION).params == {
        "condition_id": CONDITION
    }
    assert data.list_trader_leaderboard_spec(category="Sports").base_params == {
        "category": "Sports"
    }
    assert data.build_list_price_history_spec(asset_id="1", start=100, end=100).base_params == {
        "token_id": "1",
        "start": 100,
        "end": 100,
    }
    assert data.build_get_trader_leaderboard_standing_spec(
        user=WALLET, category="sports", window="week"
    ).params == {"user": WALLET, "category": "sports", "time_period": "week"}
    assert data.get_builder_volumes_spec(interval="day", bucket_limit=2).params == {
        "interval": "day",
        "limit": 2,
    }
    at = datetime(2026, 1, 1, microsecond=900000, tzinfo=UTC)
    assert data.build_get_user_volume_spec(user=WALLET, start=at).params == {
        "user": WALLET,
        "start": 1767225600,
    }
    assert data.build_list_price_history_spec(asset_id="1", interval="1d").base_params == {
        "token_id": "1",
        "interval": "1d",
    }
    assert data.list_trades_spec(filter_type="TOKENS").base_params == {"filter_type": "TOKENS"}
    assert data.list_trades_spec(filter_amount=0).base_params == {"filter_amount": 0}
    assert data.build_accounting_snapshot_request(user=WALLET) == (
        "/v1/accounting/snapshot",
        {"user": WALLET},
    )


@pytest.mark.parametrize("bound", ["start", "end"])
@pytest.mark.parametrize("value", [0, 1, datetime(2026, 1, 1, tzinfo=UTC)])
def test_positions_full_history_rejects_explicit_bounds(bound: str, value: object) -> None:
    kwargs: dict[str, Any] = {bound: value}
    with pytest.raises(UserInputError, match="full_history cannot be combined"):
        data.list_positions_spec(user=WALLET, full_history=True, **kwargs)


def test_positions_time_bounds_and_other_full_history_feeds() -> None:
    at = datetime(2026, 1, 1, microsecond=999999, tzinfo=UTC)
    assert data.list_positions_spec(user=WALLET, start=at, end=1767225601).base_params == {
        "user": WALLET,
        "start": 1767225600,
        "end": 1767225601,
    }
    assert data.list_trades_spec(full_history=True).base_params == {"start": 1}
    assert data.list_activity_spec(user=WALLET, full_history=True).base_params == {
        "user": WALLET,
        "exclude_deposits_withdrawals": False,
        "start": 1,
    }
    assert data.build_get_user_volume_spec(user=WALLET, full_history=True).params == {
        "user": WALLET,
        "start": 1,
    }


@pytest.mark.parametrize("bound", ["updated_after", "updated_before"])
@pytest.mark.parametrize(
    "value,expected",
    [
        (0, 0),
        (datetime(1970, 1, 1, tzinfo=UTC), 0),
        (datetime(2026, 1, 1, microsecond=999999, tzinfo=UTC), 1767225600),
        (253402300799, 253402300799),
        (None, None),
    ],
)
def test_combo_watermarks_preserve_epoch_seconds(
    bound: str, value: object, expected: int | None
) -> None:
    kwargs: dict[str, Any] = {bound: value}
    assert data.list_combo_positions_spec(user=WALLET, **kwargs).base_params == {
        "user": WALLET,
        **({bound: expected} if expected is not None else {}),
    }


@pytest.mark.parametrize("bound", ["updated_after", "updated_before"])
@pytest.mark.parametrize("value", [-1, True, 0.0, "0", datetime(1970, 1, 1), 253402300800])
def test_combo_watermarks_reject_invalid_values(bound: str, value: object) -> None:
    kwargs: dict[str, Any] = {bound: value}
    with pytest.raises(UserInputError):
        data.list_combo_positions_spec(user=WALLET, **kwargs)


@pytest.mark.parametrize("after,before", [(0, 0), (0, 1), (1, 1)])
def test_combo_watermarks_accept_ordered_bounds(after: int, before: int) -> None:
    assert data.list_combo_positions_spec(
        user=WALLET, updated_after=after, updated_before=before
    ).base_params == {"user": WALLET, "updated_after": after, "updated_before": before}


def test_combo_watermarks_reject_inverted_epoch_window() -> None:
    with pytest.raises(UserInputError, match="updated_before must be at least updated_after"):
        data.list_combo_positions_spec(user=WALLET, updated_after=1, updated_before=0)


def test_enum_members_serialize_like_plain_strings() -> None:
    plain = data.list_positions_spec(user=WALLET, status="CLOSED").base_params
    member = data.list_positions_spec(user=WALLET, status=PositionStatus.CLOSED).base_params
    assert plain == member and member is not None and type(member["status"]) is str
    combo = data.list_combo_positions_spec(
        user=WALLET, status=[ComboPositionStatus.OPEN, "OPEN", "PARTIAL"]
    ).base_params
    assert combo == {"user": WALLET, "status": "OPEN,PARTIAL"}
    single = data.list_combo_positions_spec(user=WALLET, status=ComboPositionStatus.OPEN)
    assert single.base_params == {"user": WALLET, "status": "OPEN"}
    activity = data.list_activity_spec(user=WALLET, activity_types=[ActivityType.TRADE, "SPLIT"])
    assert activity.base_params is not None and activity.base_params["type"] == "TRADE,SPLIT"
    assert data.build_list_biggest_winners_spec(category="Politics").base_params == {
        "category": "Politics"
    }
    assert data.build_get_user_pnl_spec(
        user=WALLET, interval=UserPnlInterval.ONE_WEEK, fidelity="1h"
    ).params == {"user": WALLET, "interval": "1w", "fidelity": "1h"}


def test_condition_canonicalization_and_time_flooring() -> None:
    for prefix in ("01", "02"):
        value = "0x" + prefix + "AB" * 30
        assert to_market_condition_id(value) == value.lower() + "00"
    assert build_distinct_condition_ids(
        [CONDITION, CONDITION.upper().replace("0X", "0x")], grammar="feed"
    ) == (CONDITION,)
    assert to_market_condition_id(CONDITION) == CONDITION
    for value in (COMBO, "0xnothex", "0x01" + " " * 60):
        with pytest.raises(TypeError):
            to_market_condition_id(value)
    assert to_epoch_seconds(datetime(2026, 1, 1, microsecond=999999, tzinfo=UTC)) == 1767225600
