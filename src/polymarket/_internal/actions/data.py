from collections.abc import Sequence
from datetime import UTC, datetime
from math import isfinite
from typing import get_args

from polymarket._internal.data_envelope import (
    parse_data_envelope,
    parse_data_page,
    parse_optional_data_envelope,
)
from polymarket._internal.data_params import (
    build_data_params,
    build_distinct_condition_ids,
    build_event_ids,
    to_epoch_seconds,
)
from polymarket._internal.request import KeysetPaginatedSpec, QueryParamValue, RequestSpec
from polymarket._internal.retry import DATA_READ_RETRY
from polymarket.errors import UserInputError
from polymarket.models.data import (
    Activity,
    ActivityTypeFilter,
    BuilderStanding,
    BuilderVolumeInterval,
    BuilderVolumePoint,
    ComboActivity,
    ComboBiggestWinner,
    ComboPosition,
    ComboPositionSortBy,
    ComboPositionStatus,
    LeaderboardWindow,
    LiveVolume,
    MarketBiggestWinner,
    MetaHolder,
    OpenInterest,
    PortfolioValue,
    Position,
    PositionFilterType,
    PositionSortBy,
    PositionStatus,
    PriceHistoryInterval,
    PriceHistoryPoint,
    Resolution,
    SortDirection,
    Trade,
    TradeFilterType,
    TraderLeaderboardEntry,
    TraderLeaderboardSort,
    TraderLeaderboardStanding,
    UserPnlFidelity,
    UserPnlInterval,
    UserPnlSeries,
    UserStats,
    UserVolume,
)
from polymarket.models.data.activity import parse_activities, parse_combo_activities
from polymarket.models.data.leaderboard import parse_biggest_winners
from polymarket.models.types import OrderSide


def list_trades_spec(
    *,
    user: str | None = None,
    condition_id: str | Sequence[str] | None = None,
    event_id: int | Sequence[int] | None = None,
    side: OrderSide | None = None,
    taker_only: bool | None = None,
    filter_type: TradeFilterType | None = None,
    filter_amount: float | None = None,
    start: int | datetime | None = None,
    end: int | datetime | None = None,
    full_history: bool = False,
) -> KeysetPaginatedSpec[Trade]:
    _check_enum("side", side, get_args(OrderSide))
    _check_enum("filter_type", filter_type, get_args(TradeFilterType))
    _check_selectors(condition_id, event_id)
    event_id = build_event_ids(event_id)
    condition_id = build_distinct_condition_ids(condition_id, grammar="feed")
    start, end = build_time_window(start=start, end=end, full_history=full_history)
    _check_nonnegative_amount("filter_amount", filter_amount)
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/trades",
        base_params=build_data_params(
            {
                "user": user,
                "condition_id": condition_id,
                "event_id": event_id,
                "side": side,
                "taker_only": taker_only,
                "filter_type": filter_type,
                "filter_amount": filter_amount,
                "start": start,
                "end": end,
            }
        ),
        parse_page=lambda payload: parse_data_page(payload, Trade.parse_response_list),
        cursor_param="cursor",
        max_page_size=1000,
        retry=DATA_READ_RETRY,
    )


def list_activity_spec(
    *,
    user: str,
    condition_id: str | Sequence[str] | None = None,
    event_id: int | Sequence[int] | None = None,
    activity_types: Sequence[ActivityTypeFilter] | None = None,
    side: OrderSide | None = None,
    sort_direction: SortDirection | None = None,
    start: int | datetime | None = None,
    end: int | datetime | None = None,
    full_history: bool = False,
) -> KeysetPaginatedSpec[Activity]:
    _check_enum("side", side, get_args(OrderSide))
    _check_enum("sort_direction", sort_direction, get_args(SortDirection))
    _require_user(user)
    _check_selectors(condition_id, event_id)
    event_id = build_event_ids(event_id)
    condition_id = build_distinct_condition_ids(condition_id, grammar="feed")
    start, end = build_time_window(start=start, end=end, full_history=full_history)
    if activity_types is not None:
        for value in activity_types:
            _check_enum("activity_types", value, get_args(ActivityTypeFilter))
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/activity",
        base_params=build_data_params(
            {
                "user": user,
                "condition_id": condition_id,
                "event_id": event_id,
                "type": activity_types,
                "side": side,
                "sort_direction": sort_direction,
                "start": start,
                "end": end,
                "exclude_deposits_withdrawals": False,
            }
        ),
        parse_page=lambda payload: parse_data_page(payload, parse_activities),
        cursor_param="cursor",
        max_page_size=1000,
        retry=DATA_READ_RETRY,
    )


def list_combo_activity_spec(
    *,
    user: str,
    condition_id: str | Sequence[str] | None = None,
) -> KeysetPaginatedSpec[ComboActivity]:
    _require_user(user)
    condition_id = build_distinct_condition_ids(condition_id, grammar="combo")
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/activity/combos",
        base_params=build_data_params({"user": user, "condition_id": condition_id}),
        parse_page=lambda payload: parse_data_page(payload, parse_combo_activities),
        cursor_param="cursor",
        max_page_size=1000,
        retry=DATA_READ_RETRY,
    )


def list_positions_spec(
    *,
    user: str | None = None,
    condition_id: str | Sequence[str] | None = None,
    status: PositionStatus | None = None,
    event_id: int | Sequence[int] | None = None,
    filter_type: PositionFilterType | None = None,
    filter_amount: float | None = None,
    include_archived: bool | None = None,
    sort_by: PositionSortBy | None = None,
    sort_direction: SortDirection | None = None,
    start: int | datetime | None = None,
    end: int | datetime | None = None,
    full_history: bool = False,
) -> KeysetPaginatedSpec[Position]:
    if user is not None:
        _require_user(user)
    _check_enum("status", status, get_args(PositionStatus))
    _check_enum("filter_type", filter_type, get_args(PositionFilterType))
    _check_enum("sort_by", sort_by, get_args(PositionSortBy))
    _check_enum("sort_direction", sort_direction, get_args(SortDirection))
    _check_selectors(condition_id, event_id)
    event_id = build_event_ids(event_id)
    condition_id = build_distinct_condition_ids(condition_id, grammar="market")
    start, end = build_time_window(start=start, end=end, full_history=full_history)
    if not user and (condition_id is None or len(condition_id) != 1):
        raise UserInputError("Provide user or exactly one condition_id")
    if event_id is not None and not user:
        raise UserInputError("event_id requires user")
    if status == "CLOSED" and include_archived is not None:
        raise UserInputError("include_archived is invalid with CLOSED")
    _check_nonnegative_amount("filter_amount", filter_amount)
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/positions",
        base_params=build_data_params(
            {
                "user": user,
                "condition": condition_id,
                "status": status,
                "event_id": event_id,
                "filter_type": filter_type,
                "filter_amount": filter_amount,
                "include_archived": include_archived,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "start": start,
                "end": end,
            }
        ),
        parse_page=lambda payload: parse_data_page(payload, Position.parse_response_list),
        cursor_param="cursor",
        max_page_size=1000,
        retry=DATA_READ_RETRY,
    )


def list_combo_positions_spec(
    *,
    user: str,
    condition_id: str | Sequence[str] | None = None,
    status: ComboPositionStatus | Sequence[ComboPositionStatus] | None = None,
    sort_by: ComboPositionSortBy | None = None,
    sort_direction: SortDirection | None = None,
    updated_after: int | datetime | None = None,
    updated_before: int | datetime | None = None,
) -> KeysetPaginatedSpec[ComboPosition]:
    _check_enum("sort_by", sort_by, get_args(ComboPositionSortBy))
    _check_enum("sort_direction", sort_direction, get_args(SortDirection))
    _require_user(user)
    condition_id = build_distinct_condition_ids(condition_id, grammar="combo")
    if status is not None:
        statuses = (status,) if isinstance(status, str) else tuple(status)
        if not statuses:
            raise UserInputError("status must be non-empty")
        for value in statuses:
            _check_enum("status", value, get_args(ComboPositionStatus))
        status = tuple(dict.fromkeys(statuses))
        if "REDEEMABLE" in status and len(status) != 1:
            raise UserInputError("REDEEMABLE must be the only status")
    updated_after = _check_timestamp(updated_after)
    updated_before = _check_timestamp(updated_before)
    if updated_after is not None and updated_before is not None and updated_before < updated_after:
        raise UserInputError("updated_before must be at least updated_after")
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/positions/combos",
        base_params=build_data_params(
            {
                "user": user,
                "condition_id": condition_id,
                "status": status,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "updated_after": updated_after,
                "updated_before": updated_before,
            }
        ),
        parse_page=lambda payload: parse_data_page(payload, ComboPosition.parse_response_list),
        cursor_param="cursor",
        max_page_size=1000,
        retry=DATA_READ_RETRY,
    )


def build_get_portfolio_value_spec(
    *,
    user: str,
    condition_ids: str | Sequence[str] | None = None,
) -> RequestSpec[PortfolioValue]:
    _require_user(user)
    condition_ids = build_distinct_condition_ids(condition_ids, grammar="market")
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/value",
        params=build_data_params({"user": user, "condition": condition_ids}),
        parse=lambda payload: parse_data_envelope(payload, PortfolioValue.parse_response),
        retry=DATA_READ_RETRY,
    )


def build_get_user_stats_spec(
    *,
    user: str,
) -> RequestSpec[UserStats | None]:
    _require_user(user)
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/user-stats",
        params=build_data_params({"user": user}),
        parse=lambda payload: parse_optional_data_envelope(payload, UserStats.parse_response),
        retry=DATA_READ_RETRY,
    )


def build_get_user_pnl_spec(
    *,
    user: str,
    interval: UserPnlInterval | None = None,
    fidelity: UserPnlFidelity | None = None,
) -> RequestSpec[UserPnlSeries]:
    _check_enum("interval", interval, get_args(UserPnlInterval))
    _check_enum("fidelity", fidelity, get_args(UserPnlFidelity))
    _require_user(user)
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/user-pnl",
        params=build_data_params({"user": user, "interval": interval, "fidelity": fidelity}),
        parse=lambda payload: parse_data_envelope(payload, UserPnlSeries.parse_response),
        retry=DATA_READ_RETRY,
    )


def build_get_user_volume_spec(
    *,
    user: str,
    start: int | datetime | None = None,
    end: int | datetime | None = None,
    full_history: bool = False,
) -> RequestSpec[UserVolume]:
    _require_user(user)
    start, end = build_time_window(start=start, end=end, full_history=full_history)
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/user-volume",
        params=build_data_params({"user": user, "start": start, "end": end}),
        parse=lambda payload: parse_data_envelope(payload, UserVolume.parse_response),
        retry=DATA_READ_RETRY,
    )


def build_list_market_holders_spec(
    *,
    condition_ids: str | Sequence[str],
    min_balance: float | None = None,
    include_pnl: bool | None = None,
) -> KeysetPaginatedSpec[MetaHolder]:
    conditions = build_distinct_condition_ids(condition_ids, grammar="market")
    if not conditions:
        raise UserInputError("condition_ids is required")
    _check_nonnegative_amount("min_balance", min_balance)
    if include_pnl and len(conditions) != 1:
        raise UserInputError("include_pnl requires exactly one condition")
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/holders",
        base_params=build_data_params(
            {"condition": conditions, "min_balance": min_balance, "include_pnl": include_pnl}
        ),
        parse_page=lambda payload: parse_data_page(payload, MetaHolder.parse_response_list),
        cursor_param="cursor",
        max_page_size=100 if include_pnl else 1000,
        retry=DATA_READ_RETRY,
    )


def get_open_interests_spec(
    *,
    condition_ids: str | Sequence[str] | None = None,
) -> RequestSpec[tuple[OpenInterest, ...]]:
    condition_ids = build_distinct_condition_ids(condition_ids, grammar="market")
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/oi",
        params=build_data_params({"condition": condition_ids}),
        parse=lambda payload: parse_data_envelope(payload, OpenInterest.parse_response_list),
        retry=DATA_READ_RETRY,
    )


def build_get_event_live_volume_spec(
    *,
    event_ids: int | Sequence[int],
) -> RequestSpec[LiveVolume]:
    events = build_event_ids(event_ids)
    if not events:
        raise UserInputError("event_ids is required")
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/live-volume",
        params=build_data_params({"event_id": events}),
        parse=lambda payload: parse_data_envelope(payload, LiveVolume.parse_response),
        retry=DATA_READ_RETRY,
    )


def build_list_price_history_spec(
    *,
    asset_id: str,
    interval: PriceHistoryInterval | None = None,
    start: int | datetime | None = None,
    end: int | datetime | None = None,
    as_of: int | datetime | None = None,
    bucket_seconds: int | None = None,
    page_size: int | None = None,
) -> KeysetPaginatedSpec[PriceHistoryPoint]:
    _check_enum("interval", interval, get_args(PriceHistoryInterval))
    if type(asset_id) is not str or not asset_id:
        raise UserInputError("asset_id must be a non-empty string")
    if sum(value is not None for value in (interval, start, as_of)) != 1:
        raise UserInputError("Provide exactly one of interval, start, or as_of")
    if end is not None and start is None:
        raise UserInputError("end requires start")
    start, end, as_of = (_check_timestamp(value) for value in (start, end, as_of))
    if start is not None:
        until = end if end is not None else int(datetime.now(UTC).timestamp())
        if until <= start or until - start > 15 * 86400:
            raise UserInputError("Price history windows must be positive and at most 15 days")
    if as_of is not None and (bucket_seconds is not None or page_size is not None):
        raise UserInputError("as_of forbids bucket_seconds and page_size")
    if bucket_seconds is not None:
        minimum = 600 if interval in ("max", "all", "1m") else 300 if interval == "1w" else 60
        if type(bucket_seconds) is not int or not minimum <= bucket_seconds <= 86400:
            raise UserInputError(f"bucket_seconds must be between {minimum} and 86400")
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/prices-history",
        base_params=build_data_params(
            {
                "token_id": asset_id,
                "interval": interval,
                "start": start,
                "end": end,
                "as_of": as_of,
                "bucket_seconds": bucket_seconds,
            }
        ),
        parse_page=lambda payload: parse_data_page(payload, PriceHistoryPoint.parse_response_list),
        cursor_param="cursor",
        max_page_size=10000,
        retry=DATA_READ_RETRY,
    )


def build_get_resolutions_spec(
    *,
    question_id: str | None = None,
    condition_ids: str | Sequence[str] | None = None,
    event_ids: int | Sequence[int] | None = None,
) -> RequestSpec[tuple[Resolution, ...]]:
    if sum(value is not None for value in (question_id, condition_ids, event_ids)) != 1:
        raise UserInputError("Provide exactly one of question_id, condition_ids, or event_ids")
    if question_id is not None and (type(question_id) is not str or not question_id):
        raise UserInputError("question_id must be non-empty")
    condition_ids = build_distinct_condition_ids(condition_ids, grammar="market")
    event_ids = build_event_ids(event_ids)
    if event_ids is not None and len(event_ids) > 20:
        raise UserInputError("event_ids accepts at most 20 distinct values")
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/resolutions",
        params=build_data_params(
            {"question_id": question_id, "condition": condition_ids, "event_id": event_ids}
        ),
        parse=lambda payload: parse_data_envelope(payload, Resolution.parse_response_list),
        retry=DATA_READ_RETRY,
    )


def list_trader_leaderboard_spec(
    *,
    category: str | None = None,
    window: LeaderboardWindow | None = None,
    sort_by: TraderLeaderboardSort | None = None,
) -> KeysetPaginatedSpec[TraderLeaderboardEntry]:
    _check_enum("window", window, get_args(LeaderboardWindow))
    _check_enum("sort_by", sort_by, get_args(TraderLeaderboardSort))
    if category is not None:
        category = category.lower()
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/leaderboard",
        base_params=build_data_params(
            {"category": category, "time_period": window, "sort_by": sort_by}
        ),
        parse_page=lambda payload: parse_data_page(
            payload, TraderLeaderboardEntry.parse_response_list
        ),
        cursor_param="cursor",
        max_page_size=1000,
        retry=DATA_READ_RETRY,
    )


def build_get_trader_leaderboard_standing_spec(
    *,
    user: str,
    category: str | None = None,
    window: LeaderboardWindow | None = None,
) -> RequestSpec[TraderLeaderboardStanding | None]:
    _check_enum("window", window, get_args(LeaderboardWindow))
    _require_user(user)
    if category is not None:
        category = category.lower()
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/leaderboard",
        params=build_data_params({"user": user, "category": category, "time_period": window}),
        parse=lambda payload: parse_optional_data_envelope(
            payload, TraderLeaderboardStanding.parse_response
        ),
        retry=DATA_READ_RETRY,
    )


def build_list_biggest_winners_spec(
    *,
    category: str | None = None,
    window: LeaderboardWindow | None = None,
) -> KeysetPaginatedSpec[MarketBiggestWinner | ComboBiggestWinner]:
    _check_enum("window", window, get_args(LeaderboardWindow))
    if category is not None:
        category = category.lower()
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/biggest-winners",
        base_params=build_data_params({"category": category, "time_period": window}),
        parse_page=lambda payload: parse_data_page(payload, parse_biggest_winners),
        cursor_param="cursor",
        max_page_size=1000,
        retry=DATA_READ_RETRY,
    )


def list_builder_leaderboard_spec(
    *,
    window: LeaderboardWindow | None = None,
) -> KeysetPaginatedSpec[BuilderStanding]:
    _check_enum("window", window, get_args(LeaderboardWindow))
    return KeysetPaginatedSpec(
        service="data",
        path="/v2/builders/leaderboard",
        base_params=build_data_params({"time_period": window}),
        parse_page=lambda payload: parse_data_page(payload, BuilderStanding.parse_response_list),
        cursor_param="cursor",
        max_page_size=1000,
        retry=DATA_READ_RETRY,
    )


def get_builder_volumes_spec(
    *,
    interval: BuilderVolumeInterval | None = None,
    bucket_limit: int | None = None,
) -> RequestSpec[tuple[BuilderVolumePoint, ...]]:
    _check_enum("interval", interval, get_args(BuilderVolumeInterval))
    if bucket_limit is not None and (type(bucket_limit) is not int or not 1 <= bucket_limit <= 90):
        raise UserInputError("bucket_limit must be between 1 and 90")
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/builders/volume",
        params=build_data_params({"interval": interval, "limit": bucket_limit}),
        parse=lambda payload: parse_data_envelope(payload, BuilderVolumePoint.parse_response_list),
        retry=DATA_READ_RETRY,
    )


def build_accounting_snapshot_request(*, user: str) -> tuple[str, dict[str, QueryParamValue]]:
    _require_user(user)
    return "/v1/accounting/snapshot", {"user": user}


def _require_user(user: object) -> None:
    if not isinstance(user, str) or not user:
        raise UserInputError("user is required")


def _check_enum(name: str, value: object, allowed: tuple[str, ...]) -> None:
    if value is not None and value not in allowed:
        raise UserInputError(f"{name} must be one of {allowed}, got {value!r}")


def _check_selectors(condition_id: object, event_id: object) -> None:
    if condition_id is not None and event_id is not None:
        raise UserInputError("Provide condition_id or event_id, not both")


def _check_nonnegative_amount(name: str, value: float | None) -> None:
    if value is not None and (isinstance(value, bool) or not isfinite(value) or value < 0):
        raise UserInputError(f"{name} must be a finite non-negative amount")


def _check_timestamp(value: int | datetime | None) -> int | None:
    if value is None:
        return None
    seconds = to_epoch_seconds(value)
    if not 0 < seconds <= 253402300799:
        raise UserInputError("Timestamp must be positive and no later than 9999-12-31T23:59:59Z")
    return seconds


def build_time_window(
    *, start: int | datetime | None, end: int | datetime | None, full_history: bool
) -> tuple[int | None, int | None]:
    if full_history:
        if start is not None or end is not None:
            raise UserInputError("full_history cannot be combined with start or end")
        return 1, None
    return _check_timestamp(start), _check_timestamp(end)
