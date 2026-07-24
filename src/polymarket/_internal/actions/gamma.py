from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any, Literal, TypeAlias, TypeVar, cast

from polymarket._internal.gamma_paths import (
    build_comment_thread_path,
    build_comments_by_user_address_path,
    build_event_path,
    build_event_tags_path,
    build_market_path,
    build_market_tags_path,
    build_related_tag_resources_path,
    build_related_tags_path,
    build_series_path,
    build_tag_path,
)
from polymarket._internal.request import (
    KeysetPagePayload,
    KeysetPaginatedSpec,
    OffsetPaginatedSpec,
    PageBasedSpec,
    QueryParamValue,
    RequestSpec,
)
from polymarket._internal.validation import require_nonempty
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models import (
    Comment,
    Event,
    Market,
    PublicProfile,
    RelatedTag,
    SearchResults,
    Series,
    SportsMarketTypes,
    SportsMetadata,
    Tag,
    TagReference,
    Team,
)
from polymarket.models.gamma.common import parse_string_sequence

CommentParentEntityType = Literal["Event", "Series"]
TagMatch = Literal["any", "all"]
Recurrence = Literal["daily", "weekly", "monthly"]
SearchSort = Literal[
    "volume",
    "volume_24hr",
    "liquidity",
    "competitive",
    "closed_time",
    "start_date",
    "end_date",
]

_T = TypeVar("_T")


def _make_keyset_parser(
    items_key: str,
    parse_item: Callable[[object], _T | None],
) -> Callable[[object], KeysetPagePayload[_T]]:
    def parse(data: object) -> KeysetPagePayload[_T]:
        if not isinstance(data, dict):
            raise UnexpectedResponseError("Expected an object response for keyset pagination.")
        data_dict = cast(dict[str, Any], data)

        if items_key not in data_dict:
            raise UnexpectedResponseError(
                f"Keyset response is missing required '{items_key}' field."
            )
        raw = data_dict[items_key]
        if not isinstance(raw, list):
            raise UnexpectedResponseError(f"Expected '{items_key}' to be an array.")
        items_list = cast(list[Any], raw)
        items: list[_T] = []
        for item in items_list:
            parsed = parse_item(item)
            if parsed is not None:
                items.append(parsed)

        if "next_cursor" not in data_dict:
            server_cursor: str | None = None
        else:
            nc = data_dict["next_cursor"]
            if nc is None:
                server_cursor = None
            elif isinstance(nc, str):
                if not nc:
                    raise UnexpectedResponseError(
                        "'next_cursor' must be a non-empty string when present."
                    )
                server_cursor = nc
            else:
                raise UnexpectedResponseError(
                    f"'next_cursor' must be a string when present, got {type(nc).__name__}."
                )

        return KeysetPagePayload(items=tuple(items), server_next_cursor=server_cursor)

    return parse


def _parse_list_market(item: object) -> Market | None:
    if not isinstance(item, dict):
        return Market.parse_response(item)

    item_dict = cast(dict[str, Any], item)
    try:
        outcomes = parse_string_sequence(item_dict.get("outcomes"))
    except ValueError as error:
        raise UnexpectedResponseError("Market response did not match expected shape") from error

    if len(outcomes) != 2:
        return None

    return Market.parse_response(item_dict)


def _add_optional(
    params: dict[str, QueryParamValue],
    key: str,
    value: QueryParamValue | None,
) -> None:
    if value is not None:
        params[key] = value


DateFilter: TypeAlias = str | date
TimestampFilter: TypeAlias = str | datetime


def _coerce_date_filter(value: DateFilter | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):  # pyright: ignore[reportUnnecessaryIsInstance]
        msg = "expected str or date for a date filter; got datetime (use a *_time_* filter instead)"
        raise UserInputError(msg)
    if not isinstance(value, date):  # pyright: ignore[reportUnnecessaryIsInstance]
        msg = f"expected str or date; got {type(value).__name__}"
        raise UserInputError(msg)
    return value.isoformat()


def _coerce_timestamp_filter(value: TimestampFilter | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str | datetime):  # pyright: ignore[reportUnnecessaryIsInstance]
        msg = f"expected str or datetime; got {type(value).__name__}"
        raise UserInputError(msg)
    if isinstance(value, str):
        return value
    return value.isoformat()


def _add_optional_seq(
    params: dict[str, QueryParamValue],
    key: str,
    value: str | int | Sequence[str] | Sequence[int] | None,
) -> None:
    if value is None:
        return
    if isinstance(value, bytes):
        raise UserInputError(f"{key} does not accept bytes")
    if isinstance(value, str):
        params[key] = (value,)
        return
    if isinstance(value, bool):
        raise UserInputError(f"{key} expects a string, int, or sequence; got bool")
    if isinstance(value, int):
        params[key] = (value,)
        return
    coerced = tuple(value)
    if not coerced:
        return
    params[key] = coerced


def _check_recurrence(value: Recurrence | None) -> None:
    if value is not None and value not in {"daily", "weekly", "monthly"}:
        raise UserInputError("recurrence must be one of: daily, weekly, monthly")


def _check_search_sort(value: SearchSort | None) -> None:
    if value is not None and value not in {
        "volume",
        "volume_24hr",
        "liquidity",
        "competitive",
        "closed_time",
        "start_date",
        "end_date",
    }:
        raise UserInputError(
            "sort must be one of: volume, volume_24hr, liquidity, competitive, "
            "closed_time, start_date, end_date"
        )


def _check_tag_match(value: TagMatch | None) -> None:
    if value is not None and value not in {"any", "all"}:
        raise UserInputError("tag_match must be one of: any, all")


def _check_parent_entity_type(value: CommentParentEntityType) -> None:
    if value not in {"Event", "Series"}:
        raise UserInputError("parent_entity_type must be one of: Event, Series")


def get_market_spec(
    *,
    id: str | None,
    slug: str | None,
    url: str | None,
    include_tag: bool | None,
    locale: str | None,
) -> RequestSpec[Market]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path=build_market_path(id=id, slug=slug, url=url),
        params={"include_tag": include_tag, "locale": locale},
        parse=Market.parse_response,
    )


def get_market_tags_spec(id: str) -> RequestSpec[tuple[TagReference, ...]]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path=build_market_tags_path(id),
        parse=TagReference.parse_response_list,
    )


def get_event_spec(
    *,
    id: str | None,
    slug: str | None,
    url: str | None,
    include_best_lines: bool | None,
    include_chat: bool | None,
    include_template: bool | None,
    locale: str | None,
) -> RequestSpec[Event]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path=build_event_path(id=id, slug=slug, url=url),
        params={
            "include_best_lines": include_best_lines,
            "include_chat": include_chat,
            "include_template": include_template,
            "locale": locale,
        },
        parse=Event.parse_response,
    )


def get_event_tags_spec(id: str) -> RequestSpec[tuple[TagReference, ...]]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path=build_event_tags_path(id),
        parse=TagReference.parse_response_list,
    )


def get_series_spec(
    id: str,
    *,
    locale: str | None,
) -> RequestSpec[Series]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path=build_series_path(id),
        params={"locale": locale},
        parse=Series.parse_response,
    )


def get_tag_spec(
    *,
    id: str | None,
    slug: str | None,
    include_template: bool | None,
    locale: str | None,
) -> RequestSpec[Tag]:
    if slug is not None and include_template is not None:
        raise UserInputError("include_template is only supported for tag id lookup.")
    return RequestSpec(
        service="gamma",
        method="GET",
        path=build_tag_path(id=id, slug=slug),
        params={
            "include_template": include_template,
            "locale": locale,
        },
        parse=Tag.parse_response,
    )


def get_related_tags_spec(
    *,
    id: str | None,
    slug: str | None,
    omit_empty: bool | None,
    status: str | None,
) -> RequestSpec[tuple[RelatedTag, ...]]:
    if slug is not None and (omit_empty is not None or status is not None):
        raise UserInputError("omit_empty and status are only supported for related tag id lookup.")
    return RequestSpec(
        service="gamma",
        method="GET",
        path=build_related_tags_path(id=id, slug=slug),
        params={"omit_empty": omit_empty, "status": status},
        parse=RelatedTag.parse_response_list,
    )


def get_related_tag_resources_spec(
    *,
    id: str | None,
    slug: str | None,
    locale: str | None,
    omit_empty: bool | None,
    status: str | None,
) -> RequestSpec[tuple[Tag, ...]]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path=build_related_tag_resources_path(id=id, slug=slug),
        params={"locale": locale, "omit_empty": omit_empty, "status": status},
        parse=Tag.parse_response_list,
    )


def get_sports_spec() -> RequestSpec[tuple[SportsMetadata, ...]]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path="/sports",
        parse=SportsMetadata.parse_response_list,
    )


def get_sports_market_types_spec() -> RequestSpec[SportsMarketTypes]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path="/sports/market-types",
        parse=SportsMarketTypes.parse_response,
    )


def get_public_profile_spec(address: str) -> RequestSpec[PublicProfile]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path="/public-profile",
        params={"address": require_nonempty("address", address)},
        parse=PublicProfile.parse_response,
    )


def get_comment_thread_spec(
    id: str, *, get_positions: bool | None
) -> RequestSpec[tuple[Comment, ...]]:
    return RequestSpec(
        service="gamma",
        method="GET",
        path=build_comment_thread_path(id),
        params={"get_positions": get_positions},
        parse=Comment.parse_response_list,
    )


__all__ = [
    "CommentParentEntityType",
    "DateFilter",
    "Recurrence",
    "TagMatch",
    "TimestampFilter",
    "get_comment_thread_spec",
    "get_event_spec",
    "get_event_tags_spec",
    "get_market_spec",
    "get_market_tags_spec",
    "get_public_profile_spec",
    "get_related_tag_resources_spec",
    "get_related_tags_spec",
    "get_series_spec",
    "get_sports_market_types_spec",
    "get_sports_spec",
    "get_tag_spec",
    "list_comments_by_user_address_spec",
    "list_comments_spec",
    "list_events_spec",
    "list_markets_spec",
    "list_series_spec",
    "list_tags_spec",
    "list_teams_spec",
    "search_spec",
]


def list_events_spec(
    *,
    ascending: bool | None = None,
    closed: bool = False,
    cyom: bool | None = None,
    end_date_max: TimestampFilter | None = None,
    end_date_min: TimestampFilter | None = None,
    ended: bool | None = None,
    event_date: DateFilter | None = None,
    event_week: int | None = None,
    exclude_tag_ids: int | Sequence[int] | None = None,
    featured: bool | None = None,
    featured_order: bool | None = None,
    game_ids: int | Sequence[int] | None = None,
    ids: int | Sequence[int] | None = None,
    include_best_lines: bool | None = None,
    include_chat: bool | None = None,
    include_children: bool | None = None,
    include_template: bool | None = None,
    liquidity_max: float | None = None,
    liquidity_min: float | None = None,
    live: bool | None = None,
    locale: str | None = None,
    order: str | None = None,
    parent_event_id: int | None = None,
    partner_slug: str | None = None,
    recurrence: Recurrence | None = None,
    related_tags: bool | None = None,
    series_ids: int | Sequence[int] | None = None,
    slug: str | Sequence[str] | None = None,
    start_date_max: TimestampFilter | None = None,
    start_date_min: TimestampFilter | None = None,
    start_time_max: TimestampFilter | None = None,
    start_time_min: TimestampFilter | None = None,
    tag_ids: int | Sequence[int] | None = None,
    tag_match: TagMatch | None = None,
    tag_slug: str | None = None,
    title_search: str | None = None,
    volume_max: float | None = None,
    volume_min: float | None = None,
) -> KeysetPaginatedSpec[Event]:
    _check_recurrence(recurrence)
    _check_tag_match(tag_match)

    params: dict[str, QueryParamValue] = {}
    _add_optional(params, "ascending", ascending)
    _add_optional(params, "closed", closed)
    _add_optional(params, "cyom", cyom)
    _add_optional(params, "end_date_max", _coerce_timestamp_filter(end_date_max))
    _add_optional(params, "end_date_min", _coerce_timestamp_filter(end_date_min))
    _add_optional(params, "ended", ended)
    _add_optional(params, "event_date", _coerce_date_filter(event_date))
    _add_optional(params, "event_week", event_week)
    _add_optional_seq(params, "exclude_tag_id", exclude_tag_ids)
    _add_optional(params, "featured", featured)
    _add_optional(params, "featured_order", featured_order)
    _add_optional_seq(params, "game_id", game_ids)
    _add_optional_seq(params, "id", ids)
    _add_optional(params, "include_best_lines", include_best_lines)
    _add_optional(params, "include_chat", include_chat)
    _add_optional(params, "include_children", include_children)
    _add_optional(params, "include_template", include_template)
    _add_optional(params, "liquidity_max", liquidity_max)
    _add_optional(params, "liquidity_min", liquidity_min)
    _add_optional(params, "live", live)
    _add_optional(params, "locale", locale)
    _add_optional(params, "order", order)
    _add_optional(params, "parent_event_id", parent_event_id)
    _add_optional(params, "partner_slug", partner_slug)
    _add_optional(params, "recurrence", recurrence)
    _add_optional(params, "related_tags", related_tags)
    _add_optional_seq(params, "series_id", series_ids)
    _add_optional_seq(params, "slug", slug)
    _add_optional(params, "start_date_max", _coerce_timestamp_filter(start_date_max))
    _add_optional(params, "start_date_min", _coerce_timestamp_filter(start_date_min))
    _add_optional(params, "start_time_max", _coerce_timestamp_filter(start_time_max))
    _add_optional(params, "start_time_min", _coerce_timestamp_filter(start_time_min))
    _add_optional_seq(params, "tag_id", tag_ids)
    _add_optional(params, "tag_match", tag_match)
    _add_optional(params, "tag_slug", tag_slug)
    _add_optional(params, "title_search", title_search)
    _add_optional(params, "volume_max", volume_max)
    _add_optional(params, "volume_min", volume_min)

    return KeysetPaginatedSpec(
        service="gamma",
        path="/events/keyset",
        parse_page=_make_keyset_parser("events", Event.parse_response),
        base_params=params or None,
    )


def list_markets_spec(
    *,
    ascending: bool | None = None,
    closed: bool | None = None,
    clob_token_ids: str | Sequence[str] | None = None,
    condition_ids: str | Sequence[str] | None = None,
    cyom: bool | None = None,
    decimalized: bool | None = None,
    end_date_max: TimestampFilter | None = None,
    end_date_min: TimestampFilter | None = None,
    game_id: str | None = None,
    ids: int | Sequence[int] | None = None,
    include_tag: bool | None = None,
    liquidity_num_max: float | None = None,
    liquidity_num_min: float | None = None,
    locale: str | None = None,
    market_maker_addresses: str | Sequence[str] | None = None,
    order: str | None = None,
    position_ids: str | Sequence[str] | None = None,
    question_ids: str | Sequence[str] | None = None,
    related_tags: bool | None = None,
    rfq_enabled: bool | None = None,
    rewards_min_size: float | None = None,
    slug: str | Sequence[str] | None = None,
    sports_market_types: str | Sequence[str] | None = None,
    start_date_max: TimestampFilter | None = None,
    start_date_min: TimestampFilter | None = None,
    tag_id: int | None = None,
    tag_match: TagMatch | None = None,
    uma_resolution_status: str | None = None,
    volume_num_max: float | None = None,
    volume_num_min: float | None = None,
) -> KeysetPaginatedSpec[Market]:
    _check_tag_match(tag_match)

    params: dict[str, QueryParamValue] = {}
    _add_optional(params, "ascending", ascending)
    _add_optional(params, "closed", closed)
    _add_optional_seq(params, "clob_token_ids", clob_token_ids)
    _add_optional_seq(params, "condition_ids", condition_ids)
    _add_optional(params, "cyom", cyom)
    _add_optional(params, "decimalized", decimalized)
    _add_optional(params, "end_date_max", _coerce_timestamp_filter(end_date_max))
    _add_optional(params, "end_date_min", _coerce_timestamp_filter(end_date_min))
    _add_optional(params, "game_id", game_id)
    _add_optional_seq(params, "id", ids)
    _add_optional(params, "include_tag", include_tag)
    _add_optional(params, "liquidity_num_max", liquidity_num_max)
    _add_optional(params, "liquidity_num_min", liquidity_num_min)
    _add_optional(params, "locale", locale)
    _add_optional_seq(params, "market_maker_address", market_maker_addresses)
    _add_optional(params, "order", order)
    _add_optional_seq(params, "position_ids", position_ids)
    _add_optional_seq(params, "question_ids", question_ids)
    _add_optional(params, "related_tags", related_tags)
    _add_optional(params, "rfq_enabled", rfq_enabled)
    _add_optional(params, "rewards_min_size", rewards_min_size)
    _add_optional_seq(params, "slug", slug)
    _add_optional_seq(params, "sports_market_types", sports_market_types)
    _add_optional(params, "start_date_max", _coerce_timestamp_filter(start_date_max))
    _add_optional(params, "start_date_min", _coerce_timestamp_filter(start_date_min))
    _add_optional(params, "tag_id", tag_id)
    _add_optional(params, "tag_match", tag_match)
    _add_optional(params, "uma_resolution_status", uma_resolution_status)
    _add_optional(params, "volume_num_max", volume_num_max)
    _add_optional(params, "volume_num_min", volume_num_min)

    return KeysetPaginatedSpec(
        service="gamma",
        path="/markets/keyset",
        parse_page=_make_keyset_parser("markets", _parse_list_market),
        base_params=params or None,
    )


def list_series_spec(
    *,
    ascending: bool | None = None,
    closed: bool | None = None,
    exclude_events: bool | None = None,
    locale: str | None = None,
    order: str | None = None,
    recurrence: Recurrence | None = None,
    slug: str | Sequence[str] | None = None,
) -> OffsetPaginatedSpec[Series]:
    _check_recurrence(recurrence)

    params: dict[str, QueryParamValue] = {}
    _add_optional(params, "ascending", ascending)
    _add_optional(params, "closed", closed)
    _add_optional(params, "exclude_events", exclude_events)
    _add_optional(params, "locale", locale)
    _add_optional(params, "order", order)
    _add_optional(params, "recurrence", recurrence)
    _add_optional_seq(params, "slug", slug)

    return OffsetPaginatedSpec(
        service="gamma",
        path="/series",
        # Matches the upstream per-request limit cap.
        max_page_size=50,
        parse_items=Series.parse_response_list,
        base_params=params or None,
    )


def list_tags_spec(
    *,
    ascending: bool | None = None,
    include_template: bool | None = None,
    is_carousel: bool | None = None,
    locale: str | None = None,
    order: str | None = None,
) -> OffsetPaginatedSpec[Tag]:
    params: dict[str, QueryParamValue] = {}
    _add_optional(params, "ascending", ascending)
    _add_optional(params, "include_template", include_template)
    _add_optional(params, "is_carousel", is_carousel)
    _add_optional(params, "locale", locale)
    _add_optional(params, "order", order)

    return OffsetPaginatedSpec(
        service="gamma",
        path="/tags",
        # Matches the upstream per-request limit cap.
        max_page_size=100,
        parse_items=Tag.parse_response_list,
        base_params=params or None,
    )


def list_teams_spec(
    *,
    abbreviation: str | Sequence[str] | None = None,
    ascending: bool | None = None,
    league: str | Sequence[str] | None = None,
    name: str | Sequence[str] | None = None,
    order: str | None = None,
    provider_ids: int | Sequence[int] | None = None,
) -> OffsetPaginatedSpec[Team]:
    params: dict[str, QueryParamValue] = {}
    _add_optional_seq(params, "abbreviation", abbreviation)
    _add_optional(params, "ascending", ascending)
    _add_optional_seq(params, "league", league)
    _add_optional_seq(params, "name", name)
    _add_optional(params, "order", order)
    _add_optional_seq(params, "provider_id", provider_ids)

    return OffsetPaginatedSpec(
        service="gamma",
        path="/teams",
        # Matches the upstream per-request limit cap.
        max_page_size=100,
        parse_items=Team.parse_response_list,
        base_params=params or None,
    )


def list_comments_spec(
    *,
    parent_entity_id: str,
    parent_entity_type: CommentParentEntityType,
    ascending: bool | None = None,
    get_positions: bool | None = None,
    holders_only: bool | None = None,
    order: str | None = None,
) -> OffsetPaginatedSpec[Comment]:
    require_nonempty("parent_entity_id", parent_entity_id)
    _check_parent_entity_type(parent_entity_type)

    params: dict[str, QueryParamValue] = {
        "parent_entity_id": parent_entity_id,
        "parent_entity_type": parent_entity_type,
    }
    _add_optional(params, "ascending", ascending)
    _add_optional(params, "get_positions", get_positions)
    _add_optional(params, "holders_only", holders_only)
    _add_optional(params, "order", order)

    return OffsetPaginatedSpec(
        service="gamma",
        path="/comments",
        # Matches the upstream per-request limit cap.
        max_page_size=100,
        parse_items=Comment.parse_response_list,
        base_params=params,
    )


def list_comments_by_user_address_spec(
    *,
    address: str,
    ascending: bool | None = None,
    order: str | None = None,
) -> OffsetPaginatedSpec[Comment]:
    path = build_comments_by_user_address_path(address)

    params: dict[str, QueryParamValue] = {}
    _add_optional(params, "ascending", ascending)
    _add_optional(params, "order", order)

    return OffsetPaginatedSpec(
        service="gamma",
        path=path,
        # Matches the upstream per-request limit cap.
        max_page_size=100,
        parse_items=Comment.parse_response_list,
        base_params=params or None,
    )


def search_spec(
    *,
    q: str,
    ascending: bool | None = None,
    cache: bool | None = None,
    events_status: str | None = None,
    events_tag: str | Sequence[str] | None = None,
    exclude_tag_ids: int | Sequence[int] | None = None,
    keep_closed_markets: int | None = None,
    optimized: bool | None = None,
    presets: str | Sequence[str] | None = None,
    recurrence: Recurrence | None = None,
    search_profiles: bool | None = None,
    search_tags: bool | None = None,
    sort: SearchSort | None = None,
) -> PageBasedSpec[SearchResults]:
    require_nonempty("q", q)
    _check_recurrence(recurrence)
    _check_search_sort(sort)

    params: dict[str, QueryParamValue] = {"q": q}
    _add_optional(params, "ascending", ascending)
    _add_optional(params, "cache", cache)
    _add_optional(params, "events_status", events_status)
    _add_optional_seq(params, "events_tag", events_tag)
    _add_optional_seq(params, "exclude_tag_id", exclude_tag_ids)
    _add_optional(params, "keep_closed_markets", keep_closed_markets)
    _add_optional(params, "optimized", optimized)
    _add_optional_seq(params, "presets", presets)
    _add_optional(params, "recurrence", recurrence)
    _add_optional(params, "search_profiles", search_profiles)
    _add_optional(params, "search_tags", search_tags)
    _add_optional(params, "sort", sort)

    return PageBasedSpec(
        service="gamma",
        path="/public-search",
        parse_page=SearchResults.parse_page_response,
        base_params=params,
    )
