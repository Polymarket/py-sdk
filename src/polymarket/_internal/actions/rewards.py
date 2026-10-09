import math
import re
from collections.abc import Sequence
from datetime import date as _date
from typing import cast

from pydantic import TypeAdapter, ValidationError

from polymarket._internal.actions._cursor import (
    END_CURSOR,
    next_cursor_or_none,
    optional_int,
    validate_cursor,
)
from polymarket._internal.request import QueryParamValue
from polymarket._internal.validation import require_nonempty
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.clob.rewards import (
    CurrentReward,
    MarketReward,
    RewardMarket,
    RewardMarketSort,
    RewardsPercentages,
    TotalUserEarning,
    UserEarning,
    UserRewardsEarning,
)
from polymarket.models.data.common import SortDirection
from polymarket.models.types import CtfConditionId, validate_ctf_condition_id
from polymarket.pagination import Page

_MAX_PAGE_SIZE = 500
_DEFAULT_PAGE_SIZE = 100

_CurrentRewardsAdapter = TypeAdapter(tuple[CurrentReward, ...])
_MarketRewardsAdapter = TypeAdapter(tuple[MarketReward, ...])
_UserEarningsAdapter = TypeAdapter(tuple[UserEarning, ...])
_TotalUserEarningsAdapter = TypeAdapter(tuple[TotalUserEarning, ...])
_UserRewardsEarningsAdapter = TypeAdapter(tuple[UserRewardsEarning, ...])


def _validate_date(value: str) -> str:
    if type(value) is not str:
        raise UserInputError(
            f"date must be a string in YYYY-MM-DD form, got {type(value).__name__}."
        )
    try:
        _date.fromisoformat(value)
    except ValueError as error:
        raise UserInputError(
            f"date must be a valid YYYY-MM-DD calendar date, got {value!r}."
        ) from error
    return value


def build_list_current_rewards_request(
    *, sponsored: bool | None = None, cursor: str | None = None
) -> tuple[str, dict[str, QueryParamValue]]:
    params: dict[str, QueryParamValue] = {}
    if sponsored is not None:
        if type(sponsored) is not bool:
            raise UserInputError("sponsored must be a bool.")
        params["sponsored"] = sponsored
    validated_cursor = validate_cursor(cursor)
    if validated_cursor is not None:
        params["next_cursor"] = validated_cursor
    return "/rewards/markets/current", params


def parse_current_rewards_page(data: object) -> Page[CurrentReward]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("current rewards response did not match expected shape")
    payload = cast(dict[str, object], data)
    try:
        items = _CurrentRewardsAdapter.validate_python(payload.get("data"))
    except ValidationError as error:
        raise UnexpectedResponseError("current rewards items malformed") from error
    next_cursor = next_cursor_or_none(payload.get("next_cursor"))
    return Page(
        items=items,
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


def build_list_market_rewards_request(
    *,
    condition_id: CtfConditionId,
    sponsored: bool | None = None,
    cursor: str | None = None,
) -> tuple[str, dict[str, QueryParamValue]]:
    validated = require_nonempty("condition_id", condition_id)
    try:
        validated = validate_ctf_condition_id(validated)
    except ValueError as error:
        raise UserInputError(str(error)) from error
    params: dict[str, QueryParamValue] = {}
    if sponsored is not None:
        if type(sponsored) is not bool:
            raise UserInputError("sponsored must be a bool.")
        params["sponsored"] = sponsored
    validated_cursor = validate_cursor(cursor)
    if validated_cursor is not None:
        params["next_cursor"] = validated_cursor
    return f"/rewards/markets/{validated}", params


def parse_market_rewards_page(data: object) -> Page[MarketReward]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("market rewards response did not match expected shape")
    payload = cast(dict[str, object], data)
    try:
        items = _MarketRewardsAdapter.validate_python(payload.get("data"))
    except ValidationError as error:
        raise UnexpectedResponseError("market rewards items malformed") from error
    next_cursor = next_cursor_or_none(payload.get("next_cursor"))
    return Page(
        items=items,
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


def build_get_order_scoring_request(*, order_id: str) -> tuple[str, dict[str, str]]:
    validated = require_nonempty("order_id", order_id)
    return "/order-scoring", {"order_id": validated}


def parse_order_scoring(data: object) -> bool:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("order-scoring response did not match expected shape")
    raw = cast(dict[str, object], data).get("scoring")
    if not isinstance(raw, bool):
        raise UnexpectedResponseError(
            f"order-scoring 'scoring' must be a bool, got {type(raw).__name__}"
        )
    return raw


def build_get_orders_scoring_request(*, order_ids: Sequence[str]) -> tuple[str, list[str]]:
    if isinstance(order_ids, str | bytes):
        raise UserInputError("order_ids must be a sequence of strings, not a single string.")
    items = list(order_ids)
    if not items:
        raise UserInputError("order_ids must be a non-empty sequence.")
    validated = [require_nonempty("order id", item) for item in items]
    return "/orders-scoring", validated


def parse_orders_scoring(data: object) -> dict[str, bool]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("orders-scoring response did not match expected shape")
    result: dict[str, bool] = {}
    for key, value in cast(dict[object, object], data).items():
        if not isinstance(key, str):
            raise UnexpectedResponseError(
                f"orders-scoring key must be a string, got {type(key).__name__}"
            )
        if not isinstance(value, bool):
            raise UnexpectedResponseError(
                f"orders-scoring value for {key!r} must be a bool, got {type(value).__name__}"
            )
        result[key] = value
    return result


def build_list_user_earnings_for_day_request(
    *, date: str, signature_type: int, cursor: str | None = None
) -> tuple[str, dict[str, QueryParamValue]]:
    validated_date = _validate_date(date)
    params: dict[str, QueryParamValue] = {
        "date": validated_date,
        "signature_type": signature_type,
    }
    validated_cursor = validate_cursor(cursor)
    if validated_cursor is not None:
        params["next_cursor"] = validated_cursor
    return "/rewards/user", params


def parse_user_earnings_page(data: object) -> Page[UserEarning]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("user earnings response did not match expected shape")
    payload = cast(dict[str, object], data)
    try:
        items = _UserEarningsAdapter.validate_python(payload.get("data"))
    except ValidationError as error:
        raise UnexpectedResponseError("user earnings items malformed") from error
    next_cursor = next_cursor_or_none(payload.get("next_cursor"))
    return Page(
        items=items,
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


def build_total_user_earnings_for_day_request(
    *, date: str, signature_type: int
) -> tuple[str, dict[str, QueryParamValue]]:
    validated_date = _validate_date(date)
    return "/rewards/user/total", {
        "date": validated_date,
        "signature_type": signature_type,
    }


def parse_total_user_earnings(data: object) -> tuple[TotalUserEarning, ...]:
    try:
        return _TotalUserEarningsAdapter.validate_python(data)
    except ValidationError as error:
        raise UnexpectedResponseError(
            "total user earnings response did not match expected shape"
        ) from error


def build_list_user_earnings_and_markets_config_request(
    *,
    date: str,
    signature_type: int,
    no_competition: bool | None = None,
    order_by: str | None = None,
    position: str | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
) -> tuple[str, dict[str, QueryParamValue]]:
    validated_date = _validate_date(date)
    params: dict[str, QueryParamValue] = {
        "date": validated_date,
        "signature_type": signature_type,
    }
    if no_competition is not None:
        if type(no_competition) is not bool:
            raise UserInputError("no_competition must be a bool.")
        params["no_competition"] = no_competition
    if order_by is not None:
        params["order_by"] = require_nonempty("order_by", order_by)
    if position is not None:
        params["position"] = require_nonempty("position", position)
    if page_size is None:
        params["page_size"] = _DEFAULT_PAGE_SIZE
    else:
        if type(page_size) is not int:
            raise UserInputError("page_size must be an int.")
        if page_size < 1 or page_size > _MAX_PAGE_SIZE:
            raise UserInputError(f"page_size must be between 1 and {_MAX_PAGE_SIZE}.")
        params["page_size"] = page_size
    validated_cursor = validate_cursor(cursor)
    if validated_cursor is not None:
        params["next_cursor"] = validated_cursor
    return "/rewards/user/markets", params


def parse_user_rewards_earnings_page(data: object) -> Page[UserRewardsEarning]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("user rewards earnings response did not match expected shape")
    payload = cast(dict[str, object], data)
    try:
        items = _UserRewardsEarningsAdapter.validate_python(payload.get("data"))
    except ValidationError as error:
        raise UnexpectedResponseError("user rewards earnings items malformed") from error
    next_cursor = next_cursor_or_none(payload.get("next_cursor"))
    return Page(
        items=items,
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
        total_count=optional_int(payload, "total_count"),
    )


def build_get_reward_percentages_request(
    *, signature_type: int
) -> tuple[str, dict[str, QueryParamValue]]:
    return "/rewards/user/percentages", {"signature_type": signature_type}


def parse_reward_percentages(data: object) -> RewardsPercentages:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("reward percentages response did not match expected shape")
    result: RewardsPercentages = {}
    for key, value in cast(dict[object, object], data).items():
        if not isinstance(key, str):
            raise UnexpectedResponseError(
                f"reward percentages key must be a string, got {type(key).__name__}"
            )
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise UnexpectedResponseError(
                f"reward percentages value for {key!r} must be numeric, got {type(value).__name__}"
            )
        result[CtfConditionId(key)] = float(value)
    return result


__all__ = [
    "END_CURSOR",
    "build_get_order_scoring_request",
    "build_get_orders_scoring_request",
    "build_get_reward_percentages_request",
    "build_list_current_rewards_request",
    "build_list_market_rewards_request",
    "build_list_user_earnings_and_markets_config_request",
    "build_list_user_earnings_for_day_request",
    "build_total_user_earnings_for_day_request",
    "parse_current_rewards_page",
    "parse_market_rewards_page",
    "parse_order_scoring",
    "parse_orders_scoring",
    "parse_reward_percentages",
    "parse_total_user_earnings",
    "parse_user_earnings_page",
    "parse_user_rewards_earnings_page",
]


def build_list_reward_markets_request(
    *,
    query: str | None = None,
    tag_slugs: Sequence[str] | None = None,
    exclude_tag_slugs: Sequence[str] | None = None,
    market_id: int | None = None,
    event_ids: Sequence[int] | None = None,
    event_title: str | None = None,
    order_by: RewardMarketSort | str | None = None,
    sort_direction: SortDirection | None = None,
    min_volume_24hr: float | None = None,
    max_volume_24hr: float | None = None,
    min_spread: float | None = None,
    max_spread: float | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    page_size: int = 100,
    cursor: str | None = None,
) -> tuple[str, dict[str, QueryParamValue]]:
    params: dict[str, QueryParamValue] = {}
    if type(page_size) is not int or not 1 <= page_size <= 500:
        raise UserInputError("page_size must be an integer between 1 and 500.")
    params["page_size"] = page_size
    for name, value in (("q", query), ("event_title", event_title)):
        if value is not None:
            if type(value) is not str:
                raise UserInputError(f"{name} must be a string.")
            params[name] = value
    if tag_slugs is not None:
        if isinstance(tag_slugs, str | bytes):
            raise UserInputError("tag_slugs must be a sequence of strings.")
        params["tag_slug"] = tuple(require_nonempty("tag_slug", item) for item in tag_slugs)
    if exclude_tag_slugs is not None:
        if isinstance(exclude_tag_slugs, str | bytes):
            raise UserInputError("exclude_tag_slugs must be a sequence of strings.")
        excluded: list[str] = []
        for item in exclude_tag_slugs:
            slug = require_nonempty("exclude_tag_slug", item).strip().lower()
            if len(slug) > 64 or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is None:
                raise UserInputError("Invalid excluded tag slug.")
            if slug not in excluded:
                excluded.append(slug)
        if len(excluded) > 20:
            raise UserInputError("At most 20 unique excluded tags are supported.")
        params["exclude_tag_slug"] = tuple(excluded)
    if market_id is not None:
        if type(market_id) is not int or market_id <= 0:
            raise UserInputError("market_id must be a positive integer.")
        params["market_id"] = market_id
    if event_ids is not None:
        if isinstance(event_ids, str | bytes):
            raise UserInputError("event_ids must be a sequence of positive integers.")
        if any(type(item) is not int or item <= 0 for item in event_ids):
            raise UserInputError("event_ids must be positive integers.")
        params["event_id"] = tuple(event_ids)
    if order_by is not None:
        try:
            params["order_by"] = RewardMarketSort(order_by).value
        except ValueError as error:
            raise UserInputError("Invalid reward market sort field.") from error
    if sort_direction is not None:
        if sort_direction not in ("ASC", "DESC"):
            raise UserInputError("sort_direction must be ASC or DESC.")
        params["position"] = sort_direction
    for name, bound in (
        ("min_volume_24hr", min_volume_24hr),
        ("max_volume_24hr", max_volume_24hr),
        ("min_spread", min_spread),
        ("max_spread", max_spread),
        ("min_price", min_price),
        ("max_price", max_price),
    ):
        if bound is not None:
            if type(bound) not in (int, float) or not math.isfinite(bound) or bound < 0:
                raise UserInputError(f"{name} must be a finite nonnegative number.")
            params[name] = bound
    validated_cursor = validate_cursor(cursor)
    if validated_cursor is not None:
        params["next_cursor"] = validated_cursor
    return "/rewards/markets/multi", params


def parse_reward_markets_page(data: object) -> Page[RewardMarket]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("reward markets response did not match expected shape")
    payload = cast(dict[str, object], data)
    items = RewardMarket.parse_response_list(payload.get("data"))
    next_cursor = next_cursor_or_none(payload.get("next_cursor"))
    return Page(items=items, has_more=next_cursor is not None, next_cursor=next_cursor)
