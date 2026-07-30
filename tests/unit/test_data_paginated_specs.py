import pytest

from polymarket._internal.actions import data as data_actions
from polymarket.errors import UnexpectedResponseError, UserInputError

_COMBO_CONDITION_ID = "0x032def24bfb0c5c57fb236fac08b94236a0000000000000000000000000000"
_CTF_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"


def test_list_positions_spec_builds_request() -> None:
    spec = data_actions.list_positions_spec(user="0xWALLET", market=["0xabc", "0xdef"])
    assert spec.service == "data"
    assert spec.path == "/positions"
    assert spec.base_params == {"user": "0xWALLET", "market": "0xabc,0xdef"}


def test_list_positions_spec_rejects_empty_user() -> None:
    with pytest.raises(UserInputError, match="user is required"):
        data_actions.list_positions_spec(user="")


def test_list_positions_spec_rejects_market_and_event_id() -> None:
    with pytest.raises(UserInputError, match="not both"):
        data_actions.list_positions_spec(user="0xWALLET", market=["0xabc"], event_id=[1])


def test_list_positions_spec_rejects_long_title() -> None:
    with pytest.raises(UserInputError, match="100 characters"):
        data_actions.list_positions_spec(user="0xWALLET", title="x" * 101)


def test_list_positions_spec_validates_sort_by() -> None:
    with pytest.raises(UserInputError, match="sort_by"):
        data_actions.list_positions_spec(user="0xWALLET", sort_by="BOGUS")  # type: ignore[arg-type]


def test_list_closed_positions_spec_builds_request() -> None:
    spec = data_actions.list_closed_positions_spec(
        user="0xWALLET", sort_by="REALIZEDPNL", sort_direction="DESC"
    )
    assert spec.path == "/closed-positions"
    assert spec.base_params == {
        "user": "0xWALLET",
        "sortBy": "REALIZEDPNL",
        "sortDirection": "DESC",
    }


def test_list_combo_positions_spec_builds_request() -> None:
    spec = data_actions.list_combo_positions_spec(
        user="0xWALLET",
        status="OPEN",
        sort="updated_asc",
        condition_id=f"{_COMBO_CONDITION_ID}01",
        updated_after=1_797_360_000,
    )
    assert spec.path == "/v1/positions/combos"
    assert spec.cursor_param == "cursor"
    assert spec.base_params == {
        "user": "0xWALLET",
        "status": "OPEN",
        "sort": "updated_asc",
        "market_id": _COMBO_CONDITION_ID,
        "updatedAfter": 1_797_360_000,
    }


def test_list_combo_positions_spec_validates_status() -> None:
    with pytest.raises(UserInputError, match="status"):
        data_actions.list_combo_positions_spec(user="0xWALLET", status="CLOSED")  # type: ignore[arg-type]


def test_list_combo_positions_spec_rejects_non_combo_condition_id() -> None:
    with pytest.raises(UserInputError, match="combo condition ID"):
        data_actions.list_combo_positions_spec(user="0xWALLET", condition_id=_CTF_CONDITION_ID)


def test_list_combo_positions_spec_rejects_empty_condition_id_sequence() -> None:
    with pytest.raises(UserInputError, match="condition_id"):
        data_actions.list_combo_positions_spec(user="0xWALLET", condition_id=[])


def test_list_combo_activity_spec_builds_request() -> None:
    spec = data_actions.list_combo_activity_spec(
        user="0xWALLET",
        condition_id=[f"{_COMBO_CONDITION_ID}00", f"{_COMBO_CONDITION_ID}01"],
    )

    assert spec.path == "/v1/activity/combos"
    assert spec.cursor_param == "cursor"
    assert spec.base_params == {
        "user": "0xWALLET",
        "market_id": f"{_COMBO_CONDITION_ID},{_COMBO_CONDITION_ID}",
    }


def test_list_combo_activity_spec_rejects_empty_condition_id_sequence() -> None:
    with pytest.raises(UserInputError, match="condition_id"):
        data_actions.list_combo_activity_spec(user="0xWALLET", condition_id=[])


def test_list_combo_positions_parser_treats_end_cursor_as_terminal() -> None:
    spec = data_actions.list_combo_positions_spec(user="0xWALLET")
    page = spec.parse_page(
        {
            "combos": [],
            "pagination": {
                "limit": 50,
                "offset": 0,
                "has_more": False,
                "next_cursor": "LTE=",
            },
        }
    )

    assert page.items == ()
    assert page.server_next_cursor is None


def test_list_combo_activity_parser_rejects_empty_next_cursor() -> None:
    spec = data_actions.list_combo_activity_spec(user="0xWALLET")
    with pytest.raises(UnexpectedResponseError, match="next_cursor"):
        spec.parse_page(
            {
                "activity": [],
                "pagination": {
                    "limit": 50,
                    "offset": 0,
                    "has_more": True,
                    "next_cursor": "",
                },
            }
        )


def test_list_market_positions_spec_requires_market() -> None:
    with pytest.raises(UserInputError, match="market is required"):
        data_actions.list_market_positions_spec(market="")


def test_list_market_positions_spec_validates_status() -> None:
    with pytest.raises(UserInputError, match="status"):
        data_actions.list_market_positions_spec(market="0xabc", status="ACTIVE")  # type: ignore[arg-type]


def test_list_trades_spec_rejects_market_and_event_id() -> None:
    with pytest.raises(UserInputError, match="not both"):
        data_actions.list_trades_spec(market=["0xabc"], event_id=[1])


def test_list_trades_spec_requires_filter_pair() -> None:
    with pytest.raises(UserInputError, match="filter_type and filter_amount"):
        data_actions.list_trades_spec(filter_type="CASH")
    with pytest.raises(UserInputError, match="filter_type and filter_amount"):
        data_actions.list_trades_spec(filter_amount=10.0)


def test_list_trades_spec_accepts_paired_filter() -> None:
    spec = data_actions.list_trades_spec(filter_type="CASH", filter_amount=10.0)
    assert spec.base_params == {"filterType": "CASH", "filterAmount": 10.0}


def test_list_trades_spec_serializes_start_and_end() -> None:
    spec = data_actions.list_trades_spec(start=1_797_360_000, end=1_797_446_400)

    assert spec.base_params == {"start": 1_797_360_000, "end": 1_797_446_400}


@pytest.mark.parametrize("field", ["start", "end"])
def test_list_trades_spec_rejects_negative_time_bounds(field: str) -> None:
    with pytest.raises(UserInputError, match=field):
        if field == "start":
            data_actions.list_trades_spec(start=-1)
        else:
            data_actions.list_trades_spec(end=-1)


def test_list_activity_spec_validates_type_entries() -> None:
    with pytest.raises(UserInputError, match="activity_types entries"):
        data_actions.list_activity_spec(user="0xWALLET", activity_types=["BOGUS"])  # type: ignore[list-item]


def test_list_activity_spec_accepts_cash_activity_types() -> None:
    spec = data_actions.list_activity_spec(
        user="0xWALLET",
        activity_types=["DEPOSIT", "WITHDRAWAL", "TAKER_REBATE"],
    )
    assert spec.base_params == {
        "user": "0xWALLET",
        "type": "DEPOSIT,WITHDRAWAL,TAKER_REBATE",
        "excludeDepositsWithdrawals": False,
    }


@pytest.mark.parametrize(
    "activity_types",
    [["DEPOSIT"], ["WITHDRAWAL"], ["TRADE", "DEPOSIT"]],
)
def test_list_activity_spec_disables_deposit_withdrawal_exclusion(
    activity_types: list[str],
) -> None:
    spec = data_actions.list_activity_spec(
        user="0xWALLET",
        activity_types=activity_types,  # type: ignore[arg-type]
    )
    assert spec.base_params == {
        "user": "0xWALLET",
        "type": ",".join(activity_types),
        "excludeDepositsWithdrawals": False,
    }


def test_list_activity_spec_keeps_exclusion_default_for_other_types() -> None:
    spec = data_actions.list_activity_spec(
        user="0xWALLET",
        activity_types=["TAKER_REBATE", "MAKER_REBATE"],
    )
    assert spec.base_params == {
        "user": "0xWALLET",
        "type": "TAKER_REBATE,MAKER_REBATE",
    }


@pytest.mark.parametrize("field", ["start", "end"])
def test_list_activity_spec_rejects_negative_time_bounds(field: str) -> None:
    with pytest.raises(UserInputError, match=field):
        if field == "start":
            data_actions.list_activity_spec(user="0xWALLET", start=-1)
        else:
            data_actions.list_activity_spec(user="0xWALLET", end=-1)


def test_list_activity_spec_serializes_filters() -> None:
    spec = data_actions.list_activity_spec(
        user="0xWALLET",
        activity_types=["TRADE", "REWARD"],
        sort_by="TIMESTAMP",
        sort_direction="DESC",
    )
    assert spec.path == "/activity"
    assert spec.base_params == {
        "user": "0xWALLET",
        "type": "TRADE,REWARD",
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC",
    }


def test_list_builder_leaderboard_spec() -> None:
    spec = data_actions.list_builder_leaderboard_spec(time_period="WEEK")
    assert spec.path == "/v1/builders/leaderboard"
    assert spec.base_params == {"timePeriod": "WEEK"}


def test_list_builder_leaderboard_spec_rejects_unknown_time_period() -> None:
    with pytest.raises(UserInputError, match="time_period"):
        data_actions.list_builder_leaderboard_spec(time_period="YEAR")  # type: ignore[arg-type]


def test_list_trader_leaderboard_spec_serializes_all_filters() -> None:
    spec = data_actions.list_trader_leaderboard_spec(
        category="POLITICS",
        time_period="MONTH",
        order_by="PNL",
        user="0xWALLET",
        user_name="alice",
    )
    assert spec.path == "/v1/leaderboard"
    assert spec.base_params == {
        "category": "POLITICS",
        "timePeriod": "MONTH",
        "orderBy": "PNL",
        "user": "0xWALLET",
        "userName": "alice",
    }


def test_list_trader_leaderboard_spec_validates_category() -> None:
    with pytest.raises(UserInputError, match="category"):
        data_actions.list_trader_leaderboard_spec(category="OTHER")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("spec", "expected_max"),
    [
        (data_actions.list_positions_spec(user="0xWALLET"), 500),
        (data_actions.list_closed_positions_spec(user="0xWALLET"), 50),
        (data_actions.list_market_positions_spec(market="0xabc"), 500),
        (data_actions.list_trades_spec(), 10_000),
        (data_actions.list_activity_spec(user="0xWALLET"), 500),
        (data_actions.list_builder_leaderboard_spec(), 50),
        (data_actions.list_trader_leaderboard_spec(), 50),
    ],
    ids=[
        "positions",
        "closed-positions",
        "market-positions",
        "trades",
        "activity",
        "builder-leaderboard",
        "trader-leaderboard",
    ],
)
def test_offset_specs_cap_page_size_at_server_limit(spec: object, expected_max: int) -> None:
    # Each cap matches the server-side limit cap. Page sizes past the cap fail
    # fast instead of the server clamping or rejecting the request and
    # pagination silently misbehaving.
    assert isinstance(spec, data_actions.OffsetPaginatedSpec)
    assert spec.max_page_size == expected_max
