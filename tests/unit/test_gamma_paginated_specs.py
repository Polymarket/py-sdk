import asyncio

import httpx
import pytest
import respx
from eth_account import Account

from polymarket import ApiKeyCreds, AsyncPublicClient, AsyncSecureClient, PublicClient, SecureClient
from polymarket._internal.actions import gamma as gamma_actions
from polymarket._internal.pagination import fingerprint_query
from polymarket._internal.request import (
    KeysetPaginatedSpec,
    OffsetPaginatedSpec,
    PageBasedSpec,
)
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models import Comment, MarketResolutionStatus, ProtocolVersion


def _minimal_market_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "MARKET-1",
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.6", "0.4"],
        "clobTokenIds": ["TOKEN-YES", "TOKEN-NO"],
        "positionIds": ["POSITION-YES", "POSITION-NO"],
        "marketMakerAddress": "0xMM",
    }
    payload.update(overrides)
    return payload


def test_list_events_spec_defaults_to_open_events() -> None:
    spec = gamma_actions.list_events_spec()

    assert isinstance(spec, KeysetPaginatedSpec)
    assert spec.service == "gamma"
    assert spec.path == "/events/keyset"
    assert spec.base_params == {"closed": False}


def test_list_events_spec_collects_filter_params() -> None:
    spec = gamma_actions.list_events_spec(
        closed=False, exclude_tag_ids=[1, 2], ids=[10], tag_match="any"
    )

    assert spec.base_params == {
        "closed": False,
        "exclude_tag_id": (1, 2),
        "id": (10,),
        "tag_match": "any",
    }


def test_list_events_spec_rejects_invalid_recurrence() -> None:
    with pytest.raises(UserInputError, match="recurrence must be one of"):
        gamma_actions.list_events_spec(recurrence="yearly")  # type: ignore[arg-type]


def test_list_events_spec_rejects_invalid_tag_match() -> None:
    with pytest.raises(UserInputError, match="tag_match must be one of"):
        gamma_actions.list_events_spec(tag_match="some")  # type: ignore[arg-type]


def test_list_events_spec_omits_empty_sequences() -> None:
    spec = gamma_actions.list_events_spec(ids=[])

    assert spec.base_params == {"closed": False}


def test_list_markets_spec_default_has_no_params() -> None:
    spec = gamma_actions.list_markets_spec()

    assert isinstance(spec, KeysetPaginatedSpec)
    assert spec.service == "gamma"
    assert spec.path == "/markets/keyset"
    assert spec.base_params is None


def test_list_markets_spec_preserves_v2_filters_and_pagination_fingerprint() -> None:
    spec = gamma_actions.list_markets_spec(
        request_ids=["request-A", "request-B"],
        onchain_event_ids="event-A",
        resolution_status=MarketResolutionStatus.ACTIVE,
        version=ProtocolVersion.V2,
    )

    assert spec.base_params == {
        "request_ids": ("request-A", "request-B"),
        "onchain_event_ids": ("event-A",),
        "resolution_status": "active",
        "version": "v2",
    }
    assert fingerprint_query(spec.base_params) != fingerprint_query(None)


@pytest.mark.parametrize("name", ["request_ids", "onchain_event_ids"])
def test_list_markets_spec_bounds_v2_filter_count(name: str) -> None:
    accepted = (
        gamma_actions.list_markets_spec(request_ids=["ID"] * 100)
        if name == "request_ids"
        else gamma_actions.list_markets_spec(onchain_event_ids=["ID"] * 100)
    )
    assert accepted.base_params is not None
    assert accepted.base_params[name] == ("ID",) * 100
    with pytest.raises(UserInputError, match="100"):
        if name == "request_ids":
            gamma_actions.list_markets_spec(request_ids=["ID"] * 101)
        else:
            gamma_actions.list_markets_spec(onchain_event_ids=["ID"] * 101)


@pytest.mark.parametrize("client_mode", ["sync", "async"])
@pytest.mark.parametrize("secure", [False, True], ids=["public", "secure"])
def test_market_lists_preserve_v2_filters_and_bounds_across_pages(
    client_mode: str,
    secure: bool,
) -> None:
    # Controlled responses isolate filter serialization and continuation while
    # the live metadata API is unavailable in this environment.
    request_ids = [f"request-{index}" for index in range(100)]
    event_ids = [f"event-{index}" for index in range(100)]
    # Synthetic signing material is used only with controlled transports.
    test_key = "0x" + "01" * 32
    wallet = Account.from_key(test_key).address
    credentials = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
    requests: list[httpx.Request] = []
    responses = iter(
        [
            httpx.Response(200, json={"markets": [], "next_cursor": "page-2"}),
            httpx.Response(200, json={"markets": []}),
        ]
    )

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return next(responses)

    with respx.mock as router:
        if secure:
            router.get("https://clob.polymarket.com/auth/api-keys").respond(
                json={"apiKeys": [credentials.key]},
            )
        route = router.get("https://gamma-api.polymarket.com/markets/keyset")
        route.side_effect = respond

        if client_mode == "sync":
            client = (
                SecureClient.create(private_key=test_key, wallet=wallet, credentials=credentials)
                if secure
                else PublicClient()
            )
            with client:
                pages = list(
                    client.list_markets(
                        request_ids=request_ids,
                        onchain_event_ids=event_ids,
                        resolution_status="active",
                        version="v2",
                        page_size=10,
                    )
                )
                with pytest.raises(UserInputError, match="100"):
                    client.list_markets(request_ids=request_ids + ["extra"])
                with pytest.raises(UserInputError, match="100"):
                    client.list_markets(onchain_event_ids=event_ids + ["extra"])
        else:

            async def collect() -> int:
                client = (
                    await AsyncSecureClient.create(
                        private_key=test_key,
                        wallet=wallet,
                        credentials=credentials,
                    )
                    if secure
                    else AsyncPublicClient()
                )
                async with client:
                    pages = [
                        page
                        async for page in client.list_markets(
                            request_ids=request_ids,
                            onchain_event_ids=event_ids,
                            resolution_status="active",
                            version="v2",
                            page_size=10,
                        )
                    ]
                    with pytest.raises(UserInputError, match="100"):
                        client.list_markets(request_ids=request_ids + ["extra"])
                    with pytest.raises(UserInputError, match="100"):
                        client.list_markets(onchain_event_ids=event_ids + ["extra"])
                    return len(pages)

            assert asyncio.run(collect()) == 2
            pages = []

        if client_mode == "sync":
            assert len(pages) == 2
        assert len(requests) == 2
        for request in requests:
            query = request.url.params
            assert query.get_list("request_ids") == request_ids
            assert query.get_list("onchain_event_ids") == event_ids
            assert query["resolution_status"] == "active"
            assert query["version"] == "v2"
        assert requests[1].url.params["after_cursor"] == "page-2"


@pytest.mark.parametrize("filters", [{"resolution_status": "pending"}, {"version": "v3"}])
def test_list_markets_spec_rejects_unsupported_v2_filter_enums(filters: dict[str, str]) -> None:
    with pytest.raises(UserInputError):
        gamma_actions.list_markets_spec(**filters)  # type: ignore[arg-type]


def test_list_markets_spec_collects_array_params() -> None:
    spec = gamma_actions.list_markets_spec(
        clob_token_ids=["A", "B"],
        market_maker_addresses=["0xMM"],
        ids=[1, 2],
        position_ids=["P1", "P2"],
    )

    assert spec.base_params == {
        "clob_token_ids": ("A", "B"),
        "market_maker_address": ("0xMM",),
        "id": (1, 2),
        "position_ids": ("P1", "P2"),
    }


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        ("volume", "volumeNum"),
        ("liquidity", "liquidityNum"),
        ("volume,id", "volumeNum,id"),
        ("createdAt, volume", "createdAt,volumeNum"),
    ],
)
def test_list_markets_spec_sends_numeric_twins_for_text_sorted_fields(
    order: str, expected: str
) -> None:
    spec = gamma_actions.list_markets_spec(order=order)

    assert spec.base_params == {"order": expected}


@pytest.mark.parametrize("order", ["volumeNum", "liquidityNum", "volume24hr", "startDate", "id"])
def test_list_markets_spec_forwards_other_order_fields_unchanged(order: str) -> None:
    spec = gamma_actions.list_markets_spec(order=order, ascending=False)

    assert spec.base_params == {"ascending": False, "order": order}


def test_list_markets_spec_order_alias_keeps_cursors_interchangeable() -> None:
    # Pagination cursors carry a fingerprint of the query; a cursor issued while
    # ordering by "volume" must resume when the caller spells it "volumeNum".
    aliased = gamma_actions.list_markets_spec(order="volume", closed=False)
    explicit = gamma_actions.list_markets_spec(order="volumeNum", closed=False)

    assert fingerprint_query(aliased.base_params) == fingerprint_query(explicit.base_params)


def test_list_markets_spec_order_alias_leaves_empty_tokens_alone() -> None:
    spec = gamma_actions.list_markets_spec(order="volume,")

    assert spec.base_params == {"order": "volumeNum,"}


def test_list_events_spec_does_not_alias_order() -> None:
    # Events store volume as a number upstream, so the alias is markets-only.
    spec = gamma_actions.list_events_spec(order="volume")

    assert spec.base_params == {"closed": False, "order": "volume"}


def test_list_markets_parser_skips_non_binary_markets_and_keeps_cursor() -> None:
    spec = gamma_actions.list_markets_spec()

    payload = spec.parse_page(
        {
            "markets": [
                _minimal_market_payload(id="MARKET-1"),
                _minimal_market_payload(
                    id="MARKET-2",
                    outcomes=["Jeff Bezos", "Elon Musk", "Other"],
                ),
            ],
            "next_cursor": "cursor-1",
        }
    )

    assert [market.id for market in payload.items] == ["MARKET-1"]
    assert payload.server_next_cursor == "cursor-1"


def test_list_markets_parser_rejects_malformed_outcomes() -> None:
    spec = gamma_actions.list_markets_spec()

    with pytest.raises(UnexpectedResponseError, match="Market response"):
        spec.parse_page(
            {
                "markets": [
                    _minimal_market_payload(outcomes=["Yes", 1]),
                ]
            }
        )


def test_list_series_spec_default_has_no_params() -> None:
    spec = gamma_actions.list_series_spec()

    assert isinstance(spec, OffsetPaginatedSpec)
    assert spec.service == "gamma"
    assert spec.path == "/series"
    assert spec.base_params is None


def test_list_series_spec_collects_filter_params() -> None:
    spec = gamma_actions.list_series_spec(closed=False, exclude_events=True, slug=["nba"])

    assert spec.base_params == {"closed": False, "exclude_events": True, "slug": ("nba",)}


def test_list_series_spec_rejects_invalid_recurrence() -> None:
    with pytest.raises(UserInputError, match="recurrence must be one of"):
        gamma_actions.list_series_spec(recurrence="yearly")  # type: ignore[arg-type]


def test_list_tags_spec_default_has_no_params() -> None:
    spec = gamma_actions.list_tags_spec()

    assert isinstance(spec, OffsetPaginatedSpec)
    assert spec.path == "/tags"
    assert spec.base_params is None


def test_list_tags_spec_with_options() -> None:
    spec = gamma_actions.list_tags_spec(include_template=True, locale="en")

    assert spec.base_params == {"include_template": True, "locale": "en"}


def test_list_teams_spec_default_has_no_params() -> None:
    spec = gamma_actions.list_teams_spec()

    assert isinstance(spec, OffsetPaginatedSpec)
    assert spec.path == "/teams"
    assert spec.base_params is None


def test_list_teams_spec_maps_provider_ids_to_singular() -> None:
    spec = gamma_actions.list_teams_spec(league=["NBA"], provider_ids=[7, 8])

    assert spec.base_params == {"league": ("NBA",), "provider_id": (7, 8)}


def test_list_comments_spec_requires_parent_entity_id() -> None:
    with pytest.raises(UserInputError, match="parent_entity_id is required"):
        gamma_actions.list_comments_spec(parent_entity_id="", parent_entity_type="Event")


def test_list_comments_spec_rejects_invalid_entity_type() -> None:
    with pytest.raises(UserInputError, match="parent_entity_type must be one of"):
        gamma_actions.list_comments_spec(
            parent_entity_id="123",
            parent_entity_type="Other",  # type: ignore[arg-type]
        )


def test_list_comments_spec_builds_base_params() -> None:
    spec = gamma_actions.list_comments_spec(
        parent_entity_id="123",
        parent_entity_type="Event",
        get_positions=True,
        holders_only=False,
    )

    assert isinstance(spec, OffsetPaginatedSpec)
    assert spec.path == "/comments"
    assert spec.base_params == {
        "parent_entity_id": "123",
        "parent_entity_type": "Event",
        "get_positions": True,
        "holders_only": False,
    }


def test_list_comments_by_user_address_spec_builds_path_from_address() -> None:
    spec = gamma_actions.list_comments_by_user_address_spec(address="0xUSER", order="createdAt")

    assert isinstance(spec, OffsetPaginatedSpec)
    assert spec.path == "/comments/user_address/0xUSER"
    assert spec.base_params == {"order": "createdAt"}


def test_list_comments_by_user_address_spec_rejects_empty_address() -> None:
    with pytest.raises(UserInputError, match="address is required"):
        gamma_actions.list_comments_by_user_address_spec(address="")


def test_search_spec_requires_q() -> None:
    with pytest.raises(UserInputError, match="q is required"):
        gamma_actions.search_spec(q="")


def test_search_spec_builds_request_with_filters() -> None:
    spec = gamma_actions.search_spec(
        q="trump",
        ascending=True,
        events_tag=["politics"],
        exclude_tag_ids=[5, 6],
        sort="volume",
    )

    assert isinstance(spec, PageBasedSpec)
    assert spec.service == "gamma"
    assert spec.path == "/public-search"
    assert spec.base_params == {
        "q": "trump",
        "ascending": True,
        "events_tag": ("politics",),
        "exclude_tag_id": (5, 6),
        "sort": "volume",
    }


def test_search_spec_rejects_invalid_recurrence() -> None:
    with pytest.raises(UserInputError, match="recurrence must be one of"):
        gamma_actions.search_spec(q="x", recurrence="yearly")  # type: ignore[arg-type]


def test_search_spec_rejects_invalid_sort() -> None:
    with pytest.raises(UserInputError, match="sort must be one of"):
        gamma_actions.search_spec(q="x", sort="recent")  # type: ignore[arg-type]


def test_list_markets_spec_treats_bare_slug_string_as_single_item() -> None:
    spec = gamma_actions.list_markets_spec(slug="foo")

    assert spec.base_params == {"slug": ("foo",)}


def test_list_markets_spec_accepts_list_of_slugs() -> None:
    spec = gamma_actions.list_markets_spec(slug=["foo", "bar"])

    assert spec.base_params == {"slug": ("foo", "bar")}


def test_list_events_spec_treats_bare_int_id_as_single_item() -> None:
    spec = gamma_actions.list_events_spec(ids=10)

    assert spec.base_params == {"closed": False, "id": (10,)}


def test_list_events_spec_rejects_bytes_param() -> None:
    with pytest.raises(UserInputError, match="does not accept bytes"):
        gamma_actions.list_events_spec(slug=b"foo")  # type: ignore[arg-type]


def test_list_events_spec_rejects_bool_in_int_seq() -> None:
    with pytest.raises(UserInputError, match="got bool"):
        gamma_actions.list_events_spec(ids=True)  # type: ignore[arg-type]


def test_keyset_parser_rejects_missing_items_key() -> None:
    spec = gamma_actions.list_events_spec()
    with pytest.raises(__import__("polymarket").errors.UnexpectedResponseError):
        spec.parse_page({})


def test_keyset_parser_rejects_non_list_items() -> None:
    spec = gamma_actions.list_events_spec()
    with pytest.raises(__import__("polymarket").errors.UnexpectedResponseError):
        spec.parse_page({"events": "not-a-list"})


def test_keyset_parser_rejects_empty_next_cursor() -> None:
    spec = gamma_actions.list_events_spec()
    with pytest.raises(__import__("polymarket").errors.UnexpectedResponseError, match="non-empty"):
        spec.parse_page({"events": [], "next_cursor": ""})


def test_keyset_parser_rejects_non_string_next_cursor() -> None:
    spec = gamma_actions.list_events_spec()
    with pytest.raises(
        __import__("polymarket").errors.UnexpectedResponseError, match="must be a string"
    ):
        spec.parse_page({"events": [], "next_cursor": 123})


def test_keyset_parser_accepts_absent_next_cursor_as_terminal() -> None:
    spec = gamma_actions.list_events_spec()
    payload = spec.parse_page({"events": []})

    assert payload.items == ()
    assert payload.server_next_cursor is None


def test_keyset_parser_accepts_null_next_cursor_as_terminal() -> None:
    spec = gamma_actions.list_events_spec()
    payload = spec.parse_page({"events": [], "next_cursor": None})

    assert payload.server_next_cursor is None


def test_keyset_parser_accepts_valid_next_cursor() -> None:
    spec = gamma_actions.list_events_spec()
    payload = spec.parse_page({"events": [], "next_cursor": "opaque"})

    assert payload.server_next_cursor == "opaque"


@pytest.mark.parametrize(
    ("spec", "expected_max"),
    [
        (gamma_actions.list_series_spec(), 50),
        (gamma_actions.list_tags_spec(), 100),
        (gamma_actions.list_teams_spec(), 100),
        (
            gamma_actions.list_comments_spec(parent_entity_id="1", parent_entity_type="Event"),
            100,
        ),
        (gamma_actions.list_comments_by_user_address_spec(address="0x" + "a" * 40), 100),
    ],
    ids=["series", "tags", "teams", "comments", "comments-by-user-address"],
)
def test_offset_specs_cap_page_size_at_server_limit(spec: object, expected_max: int) -> None:
    # Each cap matches the server-side limit cap. Page sizes past the cap fail
    # fast instead of the server clamping the limit and pagination silently
    # misbehaving.
    assert isinstance(spec, OffsetPaginatedSpec)
    assert spec.max_page_size == expected_max


@pytest.mark.parametrize(
    ("spec", "expected_max_offset"),
    [
        (gamma_actions.list_series_spec(), None),
        (gamma_actions.list_tags_spec(), None),
        (gamma_actions.list_teams_spec(), None),
        (
            gamma_actions.list_comments_spec(parent_entity_id="1", parent_entity_type="Event"),
            200,
        ),
        (gamma_actions.list_comments_by_user_address_spec(address="0x" + "a" * 40), 200),
    ],
    ids=["series", "tags", "teams", "comments", "comments-by-user-address"],
)
def test_offset_specs_cap_offset_at_server_limit(
    spec: object, expected_max_offset: int | None
) -> None:
    # Only the comments listings reject deep offsets upstream; the cap here
    # must match so the SDK fails before the request rather than after it.
    assert isinstance(spec, OffsetPaginatedSpec)
    assert spec.max_offset == expected_max_offset


def test_list_comments_spec_counts_only_root_comments_as_page_fill() -> None:
    # A comments page holds `limit` top-level comments plus their replies, so
    # replies must not make a short page of roots look full.
    spec = gamma_actions.list_comments_spec(parent_entity_id="1", parent_entity_type="Event")
    assert spec.page_fill is not None

    root = Comment.parse_response({"id": "1", "body": "root"})
    reply = Comment.parse_response({"id": "2", "body": "reply", "parentCommentID": "1"})

    assert spec.page_fill((root, reply, reply)) == 1
    assert spec.page_fill((root, root)) == 2
    assert spec.page_fill(()) == 0


def test_list_comments_by_user_address_spec_counts_every_row_as_page_fill() -> None:
    # The by-address listing is flat: authored replies are rows of their own.
    spec = gamma_actions.list_comments_by_user_address_spec(address="0x" + "a" * 40)
    assert spec.page_fill is None


_KEYSET_DEFAULTS = {
    "parent_entity_id": "123",
    "parent_entity_type": "Event",
    "order": "createdAt",
    "ascending": False,
}


def test_list_comments_keyset_spec_pins_newest_first_by_default() -> None:
    spec = gamma_actions.list_comments_keyset_spec(
        parent_entity_id="123", parent_entity_type="Event"
    )

    assert isinstance(spec, KeysetPaginatedSpec)
    assert spec.path == "/comments/keyset"
    assert spec.cursor_param == "after_cursor"
    assert spec.max_page_size == 100
    assert spec.base_params == _KEYSET_DEFAULTS


def test_list_comments_keyset_spec_ignores_ascending_without_order() -> None:
    # The offset listing ignores `ascending` unless `order` is given; the
    # cursor listing keeps that behaviour so the two stay interchangeable.
    spec = gamma_actions.list_comments_keyset_spec(
        parent_entity_id="123", parent_entity_type="Event", ascending=True
    )

    assert spec.base_params == _KEYSET_DEFAULTS


@pytest.mark.parametrize(
    ("order", "ascending", "expected_ascending"),
    [("createdAt", None, True), ("id", None, True), ("id", False, False), ("id", True, True)],
)
def test_list_comments_keyset_spec_defaults_to_ascending_with_an_order(
    order: str, ascending: bool | None, expected_ascending: bool
) -> None:
    spec = gamma_actions.list_comments_keyset_spec(
        parent_entity_id="123", parent_entity_type="Event", order=order, ascending=ascending
    )

    assert spec.base_params is not None
    assert spec.base_params["order"] == order
    assert spec.base_params["ascending"] is expected_ascending


def test_list_comments_keyset_spec_rejects_unsupported_order() -> None:
    with pytest.raises(UserInputError, match="order must be one of: id, createdAt"):
        gamma_actions.list_comments_keyset_spec(
            parent_entity_id="123", parent_entity_type="Event", order="reactionCount"
        )


def test_list_comments_keyset_spec_validates_parent() -> None:
    with pytest.raises(UserInputError, match="parent_entity_id is required"):
        gamma_actions.list_comments_keyset_spec(parent_entity_id="", parent_entity_type="Event")
    with pytest.raises(UserInputError, match="parent_entity_type must be one of"):
        gamma_actions.list_comments_keyset_spec(
            parent_entity_id="123",
            parent_entity_type="Other",  # type: ignore[arg-type]
        )


def test_list_comments_keyset_spec_parses_envelope_and_terminal_pages() -> None:
    spec = gamma_actions.list_comments_keyset_spec(
        parent_entity_id="123", parent_entity_type="Event"
    )

    page = spec.parse_page(
        {"$schema": "x", "comments": [{"id": "1", "body": "root"}], "next_cursor": "tok"}
    )
    assert len(page.items) == 1
    assert isinstance(page.items[0], Comment)
    assert page.server_next_cursor == "tok"

    assert spec.parse_page({"comments": []}).server_next_cursor is None
    assert spec.parse_page({"comments": [], "next_cursor": None}).server_next_cursor is None


@pytest.mark.parametrize(
    ("get_positions", "holders_only", "order", "expected"),
    [
        (None, None, None, True),
        (False, False, "createdAt", True),
        (None, None, "id", True),
        (True, None, None, False),
        (None, True, None, False),
        (None, None, "reactionCount", False),
        (None, None, "", False),
        (None, None, " createdAt ", False),
        (None, None, "createdAt,id", False),
    ],
)
def test_comments_paginate_by_cursor_selects_supported_reads_only(
    get_positions: bool | None, holders_only: bool | None, order: str | None, expected: bool
) -> None:
    assert (
        gamma_actions.comments_paginate_by_cursor(
            get_positions=get_positions, holders_only=holders_only, order=order
        )
        is expected
    )
