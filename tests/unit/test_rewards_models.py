import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import get_type_hints

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.base import BaseModel
from polymarket.models.clob.rewards import (
    CurrentReward,
    CurrentRewardConfig,
    EarningBreakdown,
    MarketReward,
    MarketRewardConfig,
    MarketRewardToken,
    TotalUserEarning,
    UserEarning,
    UserRewardsConfig,
    UserRewardsEarning,
)

_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"


def test_current_reward_parses_with_all_optional_fields() -> None:
    reward = CurrentReward.parse_response(
        {
            "condition_id": _CONDITION_ID,
            "rewards_max_spread": 3.0,
            "rewards_min_size": "100",
            "sponsors_count": 2,
            "sponsored_daily_rate": "50",
            "native_daily_rate": "10",
            "total_daily_rate": "60",
        }
    )
    assert reward.condition_id == _CONDITION_ID
    assert reward.rewards_max_spread == 3.0
    assert reward.rewards_min_size == Decimal("100")
    assert reward.sponsors_count == 2
    assert reward.rewards_config == ()


def test_current_reward_handles_minimal_payload() -> None:
    reward = CurrentReward.parse_response({"condition_id": _CONDITION_ID})
    assert reward.condition_id == _CONDITION_ID
    assert reward.rewards_max_spread is None
    assert reward.sponsors_count is None


def test_market_reward_config_parses_epoch_ms_dates() -> None:
    config = MarketRewardConfig.parse_response(
        {
            "asset_address": "0xUSDC",
            "start_date": 1700000000000,
            "end_date": 1800000000000,
            "rate_per_day": "100",
            "total_rewards": "10000",
        }
    )
    assert config.start_date == datetime.fromtimestamp(1700000000, tz=UTC)
    assert config.end_date == datetime.fromtimestamp(1800000000, tz=UTC)


def test_market_reward_config_allows_omitting_end_date_and_total() -> None:
    config = MarketRewardConfig.parse_response(
        {
            "asset_address": "0xUSDC",
            "start_date": 1700000000000,
            "rate_per_day": "100",
        }
    )
    assert config.end_date is None
    assert config.total_rewards is None


def test_market_reward_parses_full_payload() -> None:
    market = MarketReward.parse_response(
        {
            "condition_id": _CONDITION_ID,
            "question": "Q?",
            "tokens": [{"token_id": "8501497", "outcome": "Yes", "price": "0.5"}],
        }
    )
    assert market.question == "Q?"
    assert len(market.tokens) == 1
    assert market.rewards_config == ()


def test_user_earning_parses_decimal_rate_from_number() -> None:
    earning = UserEarning.parse_response(
        {
            "asset_address": "0xUSDC",
            "asset_rate": 0.0001,
            "condition_id": _CONDITION_ID,
            "date": 1700000000000,
            "earnings": "5.5",
            "maker_address": "0xMAKER",
        }
    )
    assert earning.asset_rate == Decimal("0.0001")
    assert earning.earnings == Decimal("5.5")


def test_total_user_earning_does_not_carry_condition_id() -> None:
    total = TotalUserEarning.parse_response(
        {
            "asset_address": "0xUSDC",
            "asset_rate": "0.01",
            "date": 1700000000000,
            "earnings": "1000",
            "maker_address": "0xMAKER",
        }
    )
    assert total.asset_address == "0xUSDC"
    assert not hasattr(total, "condition_id")


def test_user_rewards_config_requires_all_fields() -> None:
    with pytest.raises(UnexpectedResponseError):
        UserRewardsConfig.parse_response(
            {
                "asset_address": "0xUSDC",
                "start_date": 1700000000000,
                "rate_per_day": "100",
            }
        )


def test_earning_breakdown_parses_decimal_fields() -> None:
    e = EarningBreakdown.parse_response(
        {"asset_address": "0xUSDC", "asset_rate": "0.001", "earnings": "10"}
    )
    assert e.asset_rate == Decimal("0.001")
    assert e.earnings == Decimal("10")


def test_user_rewards_earning_aggregates_nested_structures() -> None:
    earning = UserRewardsEarning.parse_response(
        {
            "condition_id": _CONDITION_ID,
            "earning_percentage": 0.5,
            "earnings": [
                {"asset_address": "0xUSDC", "asset_rate": "0.001", "earnings": "5"},
                {"asset_address": "0xUSDC", "asset_rate": "0.002", "earnings": "10"},
            ],
            "event_slug": "evt",
            "image": "img",
            "maker_address": "0xMAKER",
            "market_competitiveness": 0.75,
            "market_slug": "mkt",
            "question": "Q?",
            "rewards_config": [
                {
                    "asset_address": "0xUSDC",
                    "end_date": 1800000000000,
                    "rate_per_day": "100",
                    "start_date": 1700000000000,
                    "total_rewards": "10000",
                }
            ],
            "rewards_max_spread": 3.0,
            "rewards_min_size": "100",
            "tokens": [{"token_id": "8501497", "outcome": "Yes", "price": "0.5"}],
        }
    )
    assert len(earning.earnings) == 2
    assert len(earning.rewards_config) == 1
    assert earning.rewards_config[0].total_rewards == Decimal("10000")


def test_user_earning_rejects_out_of_range_epoch() -> None:
    with pytest.raises(UnexpectedResponseError):
        UserEarning.parse_response(
            {
                "asset_address": "0xUSDC",
                "asset_rate": "0.01",
                "condition_id": _CONDITION_ID,
                "date": 10**18,
                "earnings": "1",
                "maker_address": "0xMAKER",
            }
        )


def test_reward_decimal_fields_expose_canonical_annotations_and_signatures() -> None:
    fields_by_model: tuple[tuple[type[BaseModel], dict[str, object]], ...] = (
        (
            CurrentRewardConfig,
            {"rate_per_day": Decimal, "total_rewards": Decimal | None},
        ),
        (
            CurrentReward,
            {
                "rewards_min_size": Decimal | None,
                "sponsored_daily_rate": Decimal | None,
                "native_daily_rate": Decimal | None,
                "total_daily_rate": Decimal | None,
            },
        ),
        (
            MarketRewardConfig,
            {"rate_per_day": Decimal, "total_rewards": Decimal | None},
        ),
        (MarketRewardToken, {"price": Decimal}),
        (MarketReward, {"rewards_min_size": Decimal | None}),
        (UserEarning, {"asset_rate": Decimal, "earnings": Decimal}),
        (TotalUserEarning, {"asset_rate": Decimal, "earnings": Decimal}),
        (UserRewardsConfig, {"rate_per_day": Decimal, "total_rewards": Decimal}),
        (EarningBreakdown, {"asset_rate": Decimal, "earnings": Decimal}),
        (UserRewardsEarning, {"rewards_min_size": Decimal}),
    )

    for model, expected_fields in fields_by_model:
        hints = get_type_hints(model)
        parameters = inspect.signature(model).parameters
        for field, annotation in expected_fields.items():
            assert hints[field] == annotation
            assert parameters[field].annotation == annotation


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10, Decimal("10")),
        (0.1, Decimal("0.1")),
        ("0.001", Decimal("0.001")),
        (Decimal("1.25"), Decimal("1.25")),
    ],
)
def test_reward_decimal_fields_accept_number_string_and_decimal(
    value: int | float | str | Decimal, expected: Decimal
) -> None:
    token = MarketRewardToken.parse_response(
        {"token_id": "8501497", "outcome": "Yes", "price": value}
    )
    assert token.price == expected


def test_reward_decimal_fields_reject_bool() -> None:
    with pytest.raises(UnexpectedResponseError):
        MarketRewardToken.parse_response({"token_id": "8501497", "outcome": "Yes", "price": True})


@pytest.mark.parametrize(
    ("model", "payload", "field"),
    [
        (
            CurrentRewardConfig,
            {"asset_address": "0xUSDC", "start_date": 1700000000000, "rate_per_day": "1"},
            "total_rewards",
        ),
        (CurrentReward, {"condition_id": _CONDITION_ID}, "rewards_min_size"),
        (CurrentReward, {"condition_id": _CONDITION_ID}, "sponsored_daily_rate"),
        (CurrentReward, {"condition_id": _CONDITION_ID}, "native_daily_rate"),
        (CurrentReward, {"condition_id": _CONDITION_ID}, "total_daily_rate"),
        (
            MarketRewardConfig,
            {"asset_address": "0xUSDC", "start_date": 1700000000000, "rate_per_day": "1"},
            "total_rewards",
        ),
        (
            MarketReward,
            {"condition_id": _CONDITION_ID, "question": "Q?", "tokens": []},
            "rewards_min_size",
        ),
    ],
)
def test_optional_reward_decimals_accept_none_but_reject_empty_string(
    model: type[BaseModel], payload: dict[str, object], field: str
) -> None:
    assert getattr(model.parse_response(payload | {field: None}), field) is None

    with pytest.raises(UnexpectedResponseError):
        model.parse_response(payload | {field: ""})
