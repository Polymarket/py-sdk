from collections.abc import Callable, Sequence
from typing import Any, Literal, TypeVar, cast, get_args

from polymarket._internal.actions._cursor import next_cursor_or_none
from polymarket._internal.data_params import build_data_params
from polymarket._internal.request import (
    KeysetPagePayload,
    KeysetPaginatedSpec,
    OffsetPaginatedSpec,
    QueryParamValue,
    RequestSpec,
)
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.base import BaseModel
from polymarket.models.data import (
    BuilderVolumeEntry,
    BuilderVolumeTimePeriod,
    ClosedPosition,
    ComboActivity,
    ComboPosition,
    ComboPositionStatus,
    LeaderboardCategory,
    LeaderboardEntry,
    LeaderboardOrderBy,
    LeaderboardTimePeriod,
    LiveVolume,
    MetaHolder,
    MetaMarketPosition,
    OpenInterest,
    PortfolioValue,
    Position,
    Trade,
    TradedMarketCount,
    TraderLeaderboardEntry,
)
from polymarket.models.data.activity import Activity, parse_activities, parse_combo_activities
from polymarket.models.types import to_combo_condition_id

_BUILDER_VOLUME_TIME_PERIODS: tuple[str, ...] = get_args(BuilderVolumeTimePeriod)
_LEADERBOARD_TIME_PERIODS: tuple[str, ...] = get_args(LeaderboardTimePeriod)
_LEADERBOARD_CATEGORIES: tuple[str, ...] = get_args(LeaderboardCategory)
_LEADERBOARD_ORDER_BY: tuple[str, ...] = get_args(LeaderboardOrderBy)

ActivityTypeFilter = Literal[
    "TRADE",
    "SPLIT",
    "MERGE",
    "REDEEM",
    "REWARD",
    "CONVERSION",
    "MAKER_REBATE",
    "REFERRAL_REWARD",
    "YIELD",
]
_ACTIVITY_TYPES: tuple[str, ...] = get_args(ActivityTypeFilter)

ActivitySortBy = Literal["TIMESTAMP", "TOKENS", "CASH"]
_ACTIVITY_SORT_BY: tuple[str, ...] = get_args(ActivitySortBy)

PositionSortBy = Literal[
    "CURRENT",
    "INITIAL",
    "TOKENS",
    "CASHPNL",
    "PERCENTPNL",
    "TITLE",
    "RESOLVING",
    "PRICE",
    "AVGPRICE",
]
_POSITION_SORT_BY: tuple[str, ...] = get_args(PositionSortBy)

ClosedPositionSortBy = Literal["REALIZEDPNL", "TITLE", "PRICE", "AVGPRICE", "TIMESTAMP"]
_CLOSED_POSITION_SORT_BY: tuple[str, ...] = get_args(ClosedPositionSortBy)

_COMBO_POSITION_STATUS: tuple[str, ...] = get_args(ComboPositionStatus)

ComboPositionSort = Literal[
    "current_value_desc",
    "first_entry_desc",
    "entry_cost_desc",
    "resolved_at_desc",
    "updated_asc",
]
_COMBO_POSITION_SORT: tuple[str, ...] = get_args(ComboPositionSort)

MarketPositionStatus = Literal["OPEN", "CLOSED", "ALL"]
_MARKET_POSITION_STATUS: tuple[str, ...] = get_args(MarketPositionStatus)

MarketPositionSortBy = Literal["TOKENS", "CASH_PNL", "REALIZED_PNL", "TOTAL_PNL"]
_MARKET_POSITION_SORT_BY: tuple[str, ...] = get_args(MarketPositionSortBy)

SortDirection = Literal["ASC", "DESC"]
_SORT_DIRECTION: tuple[str, ...] = get_args(SortDirection)

TradeSide = Literal["BUY", "SELL"]
_TRADE_SIDE: tuple[str, ...] = get_args(TradeSide)

TradeFilterType = Literal["CASH", "TOKENS"]
_TRADE_FILTER_TYPE: tuple[str, ...] = get_args(TradeFilterType)


def get_event_live_volumes_spec(*, id: str) -> RequestSpec[tuple[LiveVolume, ...]]:
    if not id:
        raise UserInputError("id is required.")
    return RequestSpec(
        service="data",
        method="GET",
        path="/live-volume",
        params={"id": id},
        parse=LiveVolume.parse_response_list,
    )


def get_open_interests_spec(
    *, market: str | Sequence[str] | None = None
) -> RequestSpec[tuple[OpenInterest, ...]]:
    return RequestSpec(
        service="data",
        method="GET",
        path="/oi",
        params=build_data_params({"market": market}),
        parse=OpenInterest.parse_response_list,
    )


def get_market_holders_spec(
    *,
    market: Sequence[str],
    limit: int | None = None,
    min_balance: int | None = None,
) -> RequestSpec[tuple[MetaHolder, ...]]:
    if not list(market):
        raise UserInputError("market must be a non-empty sequence of condition IDs.")
    if limit is not None and limit < 1:
        raise UserInputError("limit must be a positive integer.")
    if min_balance is not None and min_balance < 0:
        raise UserInputError("min_balance must be non-negative.")
    return RequestSpec(
        service="data",
        method="GET",
        path="/holders",
        params=build_data_params({"market": market, "limit": limit, "minBalance": min_balance}),
        parse=MetaHolder.parse_response_list,
    )


def get_portfolio_values_spec(
    *,
    user: str,
    market: str | Sequence[str] | None = None,
) -> RequestSpec[tuple[PortfolioValue, ...]]:
    if not user:
        raise UserInputError("user is required.")
    return RequestSpec(
        service="data",
        method="GET",
        path="/value",
        params=build_data_params({"user": user, "market": market}),
        parse=PortfolioValue.parse_response_list,
    )


def get_traded_market_count_spec(*, user: str) -> RequestSpec[TradedMarketCount]:
    if not user:
        raise UserInputError("user is required.")
    return RequestSpec(
        service="data",
        method="GET",
        path="/traded",
        params={"user": user},
        parse=TradedMarketCount.parse_response,
    )


def get_builder_volumes_spec(
    *, time_period: BuilderVolumeTimePeriod | None = None
) -> RequestSpec[tuple[BuilderVolumeEntry, ...]]:
    if time_period is not None and time_period not in _BUILDER_VOLUME_TIME_PERIODS:
        raise UserInputError(
            f"time_period must be one of {_BUILDER_VOLUME_TIME_PERIODS}, got {time_period!r}."
        )
    return RequestSpec(
        service="data",
        method="GET",
        path="/v1/builders/volume",
        params=build_data_params({"timePeriod": time_period}),
        parse=BuilderVolumeEntry.parse_response_list,
    )


def list_positions_spec(
    *,
    user: str,
    market: str | Sequence[str] | None = None,
    event_id: int | Sequence[int] | None = None,
    size_threshold: float | None = None,
    redeemable: bool | None = None,
    mergeable: bool | None = None,
    sort_by: PositionSortBy | None = None,
    sort_direction: SortDirection | None = None,
    title: str | None = None,
) -> OffsetPaginatedSpec[Position]:
    if not user:
        raise UserInputError("user is required.")
    if market is not None and event_id is not None:
        raise UserInputError("Provide market or event_id, not both.")
    _check_enum("sort_by", sort_by, _POSITION_SORT_BY)
    _check_enum("sort_direction", sort_direction, _SORT_DIRECTION)
    if title is not None and len(title) > 100:
        raise UserInputError("title must be at most 100 characters.")

    return OffsetPaginatedSpec(
        service="data",
        path="/positions",
        # Matches the upstream per-request limit cap.
        max_page_size=500,
        base_params=build_data_params(
            {
                "user": user,
                "market": market,
                "eventId": event_id,
                "sizeThreshold": size_threshold,
                "redeemable": redeemable,
                "mergeable": mergeable,
                "sortBy": sort_by,
                "sortDirection": sort_direction,
                "title": title,
            }
        ),
        parse_items=_parser_for(Position),
    )


def list_closed_positions_spec(
    *,
    user: str,
    market: str | Sequence[str] | None = None,
    event_id: int | Sequence[int] | None = None,
    title: str | None = None,
    sort_by: ClosedPositionSortBy | None = None,
    sort_direction: SortDirection | None = None,
) -> OffsetPaginatedSpec[ClosedPosition]:
    if not user:
        raise UserInputError("user is required.")
    if market is not None and event_id is not None:
        raise UserInputError("Provide market or event_id, not both.")
    _check_enum("sort_by", sort_by, _CLOSED_POSITION_SORT_BY)
    _check_enum("sort_direction", sort_direction, _SORT_DIRECTION)
    if title is not None and len(title) > 100:
        raise UserInputError("title must be at most 100 characters.")

    return OffsetPaginatedSpec(
        service="data",
        path="/closed-positions",
        # Matches the upstream per-request limit cap.
        max_page_size=50,
        base_params=build_data_params(
            {
                "user": user,
                "market": market,
                "eventId": event_id,
                "title": title,
                "sortBy": sort_by,
                "sortDirection": sort_direction,
            }
        ),
        parse_items=_parser_for(ClosedPosition),
    )


def list_combo_positions_spec(
    *,
    user: str,
    status: ComboPositionStatus | None = None,
    sort: ComboPositionSort | None = None,
    condition_id: str | Sequence[str] | None = None,
    updated_after: int | None = None,
    updated_before: int | None = None,
) -> KeysetPaginatedSpec[ComboPosition]:
    if not user:
        raise UserInputError("user is required.")
    _check_enum("status", status, _COMBO_POSITION_STATUS)
    _check_enum("sort", sort, _COMBO_POSITION_SORT)
    if condition_id is not None:
        condition_id = _normalize_combo_condition_filter(condition_id)
    _check_nonnegative_int("updated_after", updated_after)
    _check_nonnegative_int("updated_before", updated_before)

    return KeysetPaginatedSpec(
        service="data",
        path="/v1/positions/combos",
        base_params=build_data_params(
            {
                "user": user,
                "status": status,
                "sort": sort,
                "market_id": condition_id,
                "updatedAfter": updated_after,
                "updatedBefore": updated_before,
            }
        ),
        parse_page=_make_keyset_envelope_parser("combos", ComboPosition.parse_response_list),
        cursor_param="cursor",
    )


def list_combo_activity_spec(
    *,
    user: str,
    condition_id: str | Sequence[str] | None = None,
) -> KeysetPaginatedSpec[ComboActivity]:
    if not user:
        raise UserInputError("user is required.")
    if condition_id is not None:
        condition_id = _normalize_combo_condition_filter(condition_id)

    return KeysetPaginatedSpec(
        service="data",
        path="/v1/activity/combos",
        base_params=build_data_params({"user": user, "market_id": condition_id}),
        parse_page=_make_keyset_envelope_parser("activity", parse_combo_activities),
        cursor_param="cursor",
    )


def list_market_positions_spec(
    *,
    market: str,
    user: str | None = None,
    status: MarketPositionStatus | None = None,
    sort_by: MarketPositionSortBy | None = None,
    sort_direction: SortDirection | None = None,
) -> OffsetPaginatedSpec[MetaMarketPosition]:
    if not market:
        raise UserInputError("market is required.")
    _check_enum("status", status, _MARKET_POSITION_STATUS)
    _check_enum("sort_by", sort_by, _MARKET_POSITION_SORT_BY)
    _check_enum("sort_direction", sort_direction, _SORT_DIRECTION)

    return OffsetPaginatedSpec(
        service="data",
        path="/v1/market-positions",
        # Matches the upstream per-request limit cap.
        max_page_size=500,
        base_params=build_data_params(
            {
                "market": market,
                "user": user,
                "status": status,
                "sortBy": sort_by,
                "sortDirection": sort_direction,
            }
        ),
        parse_items=_parser_for(MetaMarketPosition),
    )


def list_trades_spec(
    *,
    taker_only: bool | None = None,
    filter_type: TradeFilterType | None = None,
    filter_amount: float | None = None,
    market: str | Sequence[str] | None = None,
    event_id: int | Sequence[int] | None = None,
    user: str | None = None,
    side: TradeSide | None = None,
    start: int | None = None,
    end: int | None = None,
) -> OffsetPaginatedSpec[Trade]:
    if market is not None and event_id is not None:
        raise UserInputError("Provide market or event_id, not both.")
    if (filter_type is None) != (filter_amount is None):
        raise UserInputError("filter_type and filter_amount must be provided together.")
    _check_enum("filter_type", filter_type, _TRADE_FILTER_TYPE)
    _check_enum("side", side, _TRADE_SIDE)
    _check_nonnegative_int("start", start)
    _check_nonnegative_int("end", end)

    return OffsetPaginatedSpec(
        service="data",
        path="/trades",
        # Matches the upstream per-request limit cap.
        max_page_size=10_000,
        base_params=build_data_params(
            {
                "takerOnly": taker_only,
                "filterType": filter_type,
                "filterAmount": filter_amount,
                "market": market,
                "eventId": event_id,
                "user": user,
                "side": side,
                "start": start,
                "end": end,
            }
        ),
        parse_items=_parser_for(Trade),
    )


def list_activity_spec(
    *,
    user: str,
    market: str | Sequence[str] | None = None,
    event_id: int | Sequence[int] | None = None,
    activity_types: Sequence[ActivityTypeFilter] | None = None,
    start: int | None = None,
    end: int | None = None,
    sort_by: ActivitySortBy | None = None,
    sort_direction: SortDirection | None = None,
    side: TradeSide | None = None,
) -> OffsetPaginatedSpec[Activity]:
    if not user:
        raise UserInputError("user is required.")
    if market is not None and event_id is not None:
        raise UserInputError("Provide market or event_id, not both.")
    _check_enum("sort_by", sort_by, _ACTIVITY_SORT_BY)
    _check_enum("sort_direction", sort_direction, _SORT_DIRECTION)
    _check_enum("side", side, _TRADE_SIDE)
    _check_nonnegative_int("start", start)
    _check_nonnegative_int("end", end)
    if activity_types is not None:
        for value in activity_types:
            if value not in _ACTIVITY_TYPES:
                raise UserInputError(
                    f"activity_types entries must be one of {_ACTIVITY_TYPES}, got {value!r}."
                )

    return OffsetPaginatedSpec(
        service="data",
        path="/activity",
        # Matches the upstream per-request limit cap.
        max_page_size=500,
        base_params=build_data_params(
            {
                "user": user,
                "market": market,
                "eventId": event_id,
                "type": activity_types,
                "start": start,
                "end": end,
                "sortBy": sort_by,
                "sortDirection": sort_direction,
                "side": side,
            }
        ),
        parse_items=parse_activities,
    )


def list_builder_leaderboard_spec(
    *,
    time_period: LeaderboardTimePeriod | None = None,
) -> OffsetPaginatedSpec[LeaderboardEntry]:
    _check_enum("time_period", time_period, _LEADERBOARD_TIME_PERIODS)
    return OffsetPaginatedSpec(
        service="data",
        path="/v1/builders/leaderboard",
        # Matches the upstream per-request limit cap.
        max_page_size=50,
        base_params=build_data_params({"timePeriod": time_period}),
        parse_items=_parser_for(LeaderboardEntry),
    )


def list_trader_leaderboard_spec(
    *,
    category: LeaderboardCategory | None = None,
    time_period: LeaderboardTimePeriod | None = None,
    order_by: LeaderboardOrderBy | None = None,
    user: str | None = None,
    user_name: str | None = None,
) -> OffsetPaginatedSpec[TraderLeaderboardEntry]:
    _check_enum("category", category, _LEADERBOARD_CATEGORIES)
    _check_enum("time_period", time_period, _LEADERBOARD_TIME_PERIODS)
    _check_enum("order_by", order_by, _LEADERBOARD_ORDER_BY)
    return OffsetPaginatedSpec(
        service="data",
        path="/v1/leaderboard",
        # Matches the upstream per-request limit cap.
        max_page_size=50,
        base_params=build_data_params(
            {
                "category": category,
                "timePeriod": time_period,
                "orderBy": order_by,
                "user": user,
                "userName": user_name,
            }
        ),
        parse_items=_parser_for(TraderLeaderboardEntry),
    )


def build_accounting_snapshot_request(*, user: str) -> tuple[str, dict[str, QueryParamValue]]:
    if not user:
        raise UserInputError("user is required.")
    return "/v1/accounting/snapshot", {"user": user}


def _check_enum(name: str, value: object, allowed: tuple[str, ...]) -> None:
    if value is None:
        return
    if value not in allowed:
        raise UserInputError(f"{name} must be one of {allowed}, got {value!r}.")


def _check_nonnegative_int(name: str, value: int | None) -> None:
    if value is not None and value < 0:
        raise UserInputError(f"{name} must be non-negative.")


def _normalize_combo_condition_filter(value: str | Sequence[str]) -> str | tuple[str, ...]:
    values = (value,) if isinstance(value, str) else tuple(value)
    if not values:
        raise UserInputError("condition_id must be a non-empty sequence.")
    out: list[str] = []
    for item in values:
        try:
            out.append(to_combo_condition_id(item))
        except TypeError as error:
            raise UserInputError(str(error)) from error
    return tuple(out) if not isinstance(value, str) else out[0]


_M = TypeVar("_M", bound=BaseModel)


def _parser_for(model: type[_M]) -> Callable[[object], tuple[_M, ...]]:
    def parse(payload: object) -> tuple[_M, ...]:
        return model.parse_response_list(payload)

    return parse


def _make_keyset_envelope_parser(
    items_key: str,
    parse_items: Callable[[object], tuple[_M, ...]],
) -> Callable[[object], KeysetPagePayload[_M]]:
    def parse(payload: object) -> KeysetPagePayload[_M]:
        if not isinstance(payload, dict):
            raise UnexpectedResponseError("Paginated response did not match expected shape")
        response = cast(dict[str, Any], payload)
        if items_key not in response:
            raise UnexpectedResponseError(f"Paginated response is missing '{items_key}'.")
        pagination = response.get("pagination")
        if not isinstance(pagination, dict):
            raise UnexpectedResponseError("Paginated response is missing pagination.")
        next_cursor = next_cursor_or_none(cast(dict[str, Any], pagination).get("next_cursor"))
        return KeysetPagePayload(
            items=parse_items(response[items_key]),
            server_next_cursor=next_cursor,
        )

    return parse


__all__ = [
    "ActivitySortBy",
    "ActivityTypeFilter",
    "ClosedPositionSortBy",
    "ComboPositionSort",
    "ComboPositionStatus",
    "MarketPositionSortBy",
    "MarketPositionStatus",
    "PositionSortBy",
    "SortDirection",
    "TradeFilterType",
    "TradeSide",
    "build_accounting_snapshot_request",
    "get_builder_volumes_spec",
    "get_event_live_volumes_spec",
    "get_market_holders_spec",
    "get_open_interests_spec",
    "get_portfolio_values_spec",
    "get_traded_market_count_spec",
    "list_activity_spec",
    "list_builder_leaderboard_spec",
    "list_closed_positions_spec",
    "list_combo_activity_spec",
    "list_combo_positions_spec",
    "list_market_positions_spec",
    "list_positions_spec",
    "list_trader_leaderboard_spec",
    "list_trades_spec",
]
