from typing import Any

import pytest

from polymarket._internal.actions.rewards import (
    END_CURSOR,
    build_get_order_scoring_request,
    build_get_orders_scoring_request,
    build_get_reward_percentages_request,
    build_list_current_rewards_request,
    build_list_market_rewards_request,
    build_list_user_earnings_and_markets_config_request,
    build_list_user_earnings_for_day_request,
    build_total_user_earnings_for_day_request,
    parse_current_rewards_page,
    parse_market_rewards_page,
    parse_order_scoring,
    parse_orders_scoring,
    parse_reward_percentages,
    parse_total_user_earnings,
    parse_user_earnings_page,
    parse_user_rewards_earnings_page,
)
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.types import CtfConditionId

_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"

_CURRENT_REWARD_PAYLOAD: dict[str, Any] = {
    "condition_id": _CONDITION_ID,
    "rewards_max_spread": 3.0,
    "rewards_min_size": "100",
    "rewards_config": [
        {
            "id": 1,
            "asset_address": "0xASSET",
            "start_date": 1700000000000,
            "end_date": 1800000000000,
            "rate_per_day": "100.5",
            "total_rewards": "10000",
        }
    ],
    "sponsored_daily_rate": "50",
    "sponsors_count": 2,
    "native_daily_rate": "10",
    "total_daily_rate": "60",
}

_MARKET_REWARD_PAYLOAD: dict[str, Any] = {
    "condition_id": _CONDITION_ID,
    "question": "Will it rain?",
    "market_slug": "rain",
    "event_slug": "weather",
    "image": "https://example.com/img.png",
    "rewards_max_spread": 3.0,
    "rewards_min_size": "100",
    "market_competitiveness": 0.5,
    "tokens": [
        {"token_id": "8501497", "outcome": "Yes", "price": "0.5"},
        {"token_id": "8501498", "outcome": "No", "price": "0.5"},
    ],
    "rewards_config": [
        {
            "asset_address": "0xASSET",
            "start_date": 1700000000000,
            "rate_per_day": "100.5",
        }
    ],
}

_USER_EARNING_PAYLOAD: dict[str, Any] = {
    "asset_address": "0xUSDC",
    "asset_rate": 0.0001,
    "condition_id": _CONDITION_ID,
    "date": 1700000000000,
    "earnings": "5.5",
    "maker_address": "0xMAKER",
}

_TOTAL_USER_EARNING_PAYLOAD: dict[str, Any] = {
    "asset_address": "0xUSDC",
    "asset_rate": 0.0001,
    "date": 1700000000000,
    "earnings": "5.5",
    "maker_address": "0xMAKER",
}

_USER_REWARDS_EARNING_PAYLOAD: dict[str, Any] = {
    "condition_id": _CONDITION_ID,
    "earning_percentage": 0.25,
    "earnings": [
        {"asset_address": "0xUSDC", "asset_rate": 0.0001, "earnings": "5.5"},
    ],
    "event_slug": "weather",
    "image": "https://example.com/img.png",
    "maker_address": "0xMAKER",
    "market_competitiveness": 0.5,
    "market_slug": "rain",
    "question": "Will it rain?",
    "rewards_config": [
        {
            "asset_address": "0xUSDC",
            "end_date": 1800000000000,
            "rate_per_day": "100.5",
            "start_date": 1700000000000,
            "total_rewards": "10000",
        }
    ],
    "rewards_max_spread": 3.0,
    "rewards_min_size": "100",
    "tokens": [
        {"token_id": "8501497", "outcome": "Yes", "price": "0.5"},
    ],
}


def test_build_list_current_rewards_request_with_no_filters() -> None:
    path, params = build_list_current_rewards_request()
    assert path == "/rewards/markets/current"
    assert params == {}


def test_build_list_current_rewards_request_with_sponsored_and_cursor() -> None:
    path, params = build_list_current_rewards_request(sponsored=True, cursor="abc")
    assert path == "/rewards/markets/current"
    assert params == {"sponsored": True, "next_cursor": "abc"}


def test_build_list_current_rewards_request_rejects_non_bool_sponsored() -> None:
    with pytest.raises(UserInputError, match="sponsored"):
        build_list_current_rewards_request(sponsored="true")  # type: ignore[arg-type]


def test_parse_current_rewards_page_decodes_end_cursor_as_none() -> None:
    page = parse_current_rewards_page(
        {"data": [_CURRENT_REWARD_PAYLOAD], "next_cursor": END_CURSOR, "count": 1, "limit": 100}
    )
    assert page.next_cursor is None
    assert page.has_more is False
    assert page.total_count is None
    assert len(page.items) == 1
    assert page.items[0].condition_id == _CONDITION_ID
    assert page.items[0].sponsors_count == 2


def test_parse_current_rewards_page_keeps_non_terminal_cursor() -> None:
    page = parse_current_rewards_page(
        {"data": [], "next_cursor": "next-token", "count": 0, "limit": 100}
    )
    assert page.next_cursor == "next-token"
    assert page.has_more is True


def test_parse_current_rewards_page_returns_none_total_count_when_missing() -> None:
    page = parse_current_rewards_page({"data": [], "next_cursor": END_CURSOR})
    assert page.total_count is None


def test_parse_current_rewards_page_raises_on_empty_string_next_cursor() -> None:
    with pytest.raises(UnexpectedResponseError, match="next_cursor"):
        parse_current_rewards_page({"data": [], "next_cursor": "", "count": 0})


def test_build_list_market_rewards_request_includes_path_and_query() -> None:
    path, params = build_list_market_rewards_request(
        condition_id=CtfConditionId(_CONDITION_ID), sponsored=False, cursor="next"
    )
    assert path == f"/rewards/markets/{_CONDITION_ID}"
    assert params == {"sponsored": False, "next_cursor": "next"}


def test_build_list_market_rewards_request_rejects_empty_condition_id() -> None:
    with pytest.raises(UserInputError):
        build_list_market_rewards_request(condition_id=CtfConditionId(""))


def test_build_list_market_rewards_request_rejects_malformed_condition_id() -> None:
    with pytest.raises(UserInputError, match="31-byte or 32-byte hex string"):
        build_list_market_rewards_request(condition_id=CtfConditionId("0x1234"))


def test_parse_market_rewards_page_parses_tokens_and_config() -> None:
    page = parse_market_rewards_page(
        {"data": [_MARKET_REWARD_PAYLOAD], "next_cursor": END_CURSOR, "count": 1, "limit": 100}
    )
    assert len(page.items) == 1
    market = page.items[0]
    assert len(market.tokens) == 2
    assert market.tokens[0].outcome == "Yes"
    assert len(market.rewards_config) == 1


def test_build_get_order_scoring_request_targets_correct_path() -> None:
    path, params = build_get_order_scoring_request(order_id="0xORDER")
    assert path == "/order-scoring"
    assert params == {"order_id": "0xORDER"}


def test_build_get_order_scoring_request_rejects_empty_id() -> None:
    with pytest.raises(UserInputError):
        build_get_order_scoring_request(order_id="")


def test_parse_order_scoring_returns_bool() -> None:
    assert parse_order_scoring({"scoring": True}) is True
    assert parse_order_scoring({"scoring": False}) is False


def test_parse_order_scoring_rejects_non_bool() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_order_scoring({"scoring": "yes"})


def test_build_get_orders_scoring_request_posts_id_list() -> None:
    path, body = build_get_orders_scoring_request(order_ids=["a", "b", "c"])
    assert path == "/orders-scoring"
    assert body == ["a", "b", "c"]


def test_build_get_orders_scoring_request_rejects_empty_list() -> None:
    with pytest.raises(UserInputError, match="non-empty"):
        build_get_orders_scoring_request(order_ids=[])


def test_build_get_orders_scoring_request_rejects_bare_string() -> None:
    with pytest.raises(UserInputError, match="sequence"):
        build_get_orders_scoring_request(order_ids="abc")  # type: ignore[arg-type]


def test_parse_orders_scoring_returns_dict() -> None:
    result = parse_orders_scoring({"order-1": True, "order-2": False})
    assert result == {"order-1": True, "order-2": False}


def test_parse_orders_scoring_rejects_non_bool_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_orders_scoring({"order-1": "true"})


def test_build_list_user_earnings_for_day_request_validates_date() -> None:
    path, params = build_list_user_earnings_for_day_request(date="2026-04-16", signature_type=1)
    assert path == "/rewards/user"
    assert params == {"date": "2026-04-16", "signature_type": 1}


def test_build_list_user_earnings_for_day_request_includes_cursor() -> None:
    _, params = build_list_user_earnings_for_day_request(
        date="2026-04-16", signature_type=0, cursor="next"
    )
    assert params["next_cursor"] == "next"


def test_build_list_user_earnings_for_day_request_rejects_bad_date() -> None:
    with pytest.raises(UserInputError, match="YYYY-MM-DD"):
        build_list_user_earnings_for_day_request(date="2026/04/16", signature_type=0)


def test_build_list_user_earnings_for_day_request_rejects_invalid_calendar_date() -> None:
    with pytest.raises(UserInputError, match="YYYY-MM-DD"):
        build_list_user_earnings_for_day_request(date="2026-13-45", signature_type=0)


def test_parse_user_earnings_page_extracts_models() -> None:
    page = parse_user_earnings_page(
        {"data": [_USER_EARNING_PAYLOAD], "next_cursor": END_CURSOR, "count": 1, "limit": 100}
    )
    assert len(page.items) == 1
    assert page.items[0].condition_id == _CONDITION_ID


def test_build_total_user_earnings_for_day_request_path_and_params() -> None:
    path, params = build_total_user_earnings_for_day_request(date="2026-04-16", signature_type=3)
    assert path == "/rewards/user/total"
    assert params == {"date": "2026-04-16", "signature_type": 3}


def test_parse_total_user_earnings_returns_tuple() -> None:
    result = parse_total_user_earnings([_TOTAL_USER_EARNING_PAYLOAD])
    assert len(result) == 1
    assert result[0].asset_address == "0xUSDC"


def test_parse_total_user_earnings_rejects_non_list() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_total_user_earnings({"items": []})


def test_build_list_user_earnings_and_markets_config_request_with_all_filters() -> None:
    path, params = build_list_user_earnings_and_markets_config_request(
        date="2026-04-16",
        signature_type=1,
        no_competition=True,
        order_by="earnings",
        position="maker",
        page_size=50,
        cursor="next",
    )
    assert path == "/rewards/user/markets"
    assert params == {
        "date": "2026-04-16",
        "signature_type": 1,
        "no_competition": True,
        "order_by": "earnings",
        "position": "maker",
        "page_size": 50,
        "next_cursor": "next",
    }


def test_build_list_user_earnings_and_markets_config_request_uses_default_page_size() -> None:
    _, params = build_list_user_earnings_and_markets_config_request(
        date="2026-04-16", signature_type=0
    )
    assert params == {"date": "2026-04-16", "signature_type": 0, "page_size": 100}


def test_build_list_user_earnings_and_markets_config_request_rejects_oversize_page() -> None:
    with pytest.raises(UserInputError, match="between"):
        build_list_user_earnings_and_markets_config_request(
            date="2026-04-16", signature_type=0, page_size=501
        )


def test_build_list_user_earnings_and_markets_config_request_rejects_non_bool_no_competition() -> (
    None
):
    with pytest.raises(UserInputError, match="no_competition"):
        build_list_user_earnings_and_markets_config_request(
            date="2026-04-16",
            signature_type=0,
            no_competition="false",  # type: ignore[arg-type]
        )


def test_parse_user_rewards_earnings_page_decodes_full_payload() -> None:
    page = parse_user_rewards_earnings_page(
        {
            "data": [_USER_REWARDS_EARNING_PAYLOAD],
            "next_cursor": END_CURSOR,
            "count": 1,
            "total_count": 42,
            "limit": 100,
        }
    )
    assert page.total_count == 42
    assert len(page.items) == 1
    item = page.items[0]
    assert item.earning_percentage == 0.25
    assert len(item.earnings) == 1
    assert len(item.rewards_config) == 1
    assert len(item.tokens) == 1


def test_build_get_reward_percentages_request_includes_signature_type() -> None:
    path, params = build_get_reward_percentages_request(signature_type=2)
    assert path == "/rewards/user/percentages"
    assert params == {"signature_type": 2}


def test_parse_reward_percentages_returns_dict_of_floats() -> None:
    result = parse_reward_percentages({"0xCOND1": 0.5, "0xCOND2": 0.25})
    assert result == {"0xCOND1": 0.5, "0xCOND2": 0.25}


def test_parse_reward_percentages_coerces_int_to_float() -> None:
    result = parse_reward_percentages({"0xCOND1": 1})
    assert result == {"0xCOND1": 1.0}


def test_parse_reward_percentages_rejects_non_numeric_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_reward_percentages({"0xCOND1": "0.5"})


def test_parse_reward_percentages_rejects_bool_value() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_reward_percentages({"0xCOND1": True})
