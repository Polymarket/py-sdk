import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.gamma import (
    Comment,
    CommentMedia,
    CommentPosition,
    CommentProfile,
    Event,
    EventPartner,
    Market,
    PublicProfile,
    Reaction,
    RelatedTag,
    Series,
    SportsMarketTypes,
    SportsMetadata,
    Tag,
    TagReference,
    TeamOrdering,
    UmaResolutionStatus,
)

_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"


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


def test_market_parses_minimal_payload() -> None:
    market = Market.parse_response(_minimal_market_payload())

    assert market.id == "MARKET-1"
    assert market.outcomes.yes.label == "Yes"
    assert market.outcomes.yes.token_id == "TOKEN-YES"
    assert market.outcomes.yes.price == Decimal("0.6")
    assert market.outcomes.no.label == "No"
    assert market.outcomes.no.token_id == "TOKEN-NO"
    assert market.outcomes.no.price == Decimal("0.4")
    assert market.position_ids == ("POSITION-YES", "POSITION-NO")


def test_market_normalizes_groups_from_flat_payload() -> None:
    payload = _minimal_market_payload(
        slug="my-market",
        question="Will it rain?",
        groupItemTitle="Rain tomorrow",
        description="A market.",
        category="weather",
        image="https://example.test/i.png",
        icon="https://example.test/icon.png",
        conditionId=_CONDITION_ID,
        active=True,
        closed=False,
        archived=False,
        acceptingOrders=True,
        enableOrderBook=True,
        negRisk=False,
        startDate="2026-05-01T00:00:00Z",
        endDate="2026-06-01T00:00:00Z",
        closedTime=None,
        volume="100",
        volume24hr="20",
        liquidity="50",
        bestBid="0.59",
        bestAsk="0.61",
        lastTradePrice="0.6",
        spread="0.02",
        orderMinSize="5",
        orderPriceMinTickSize="0.01",
        secondsDelay=2,
        feesEnabled=True,
        feeType="standard",
        feeSchedule={
            "exponent": 1,
            "rate": "0.01",
            "takerOnly": False,
            "rebateRate": "0",
        },
        questionID="0xQID",
        umaResolutionStatus="resolved",
        resolutionSource="UMA",
        resolvedBy="0xRES",
        rewardsMinSize="10",
        rewardsMaxSpread=0.05,
        holdingRewardsEnabled=True,
        sportsMarketType="moneyline",
        line=2.5,
        gameId="GAME-1",
        gameStartTime="2026-05-15T18:00:00Z",
        events=[{"id": "EVENT-1", "slug": "e1", "title": "Event 1"}],
        tags=[{"id": "TAG-1", "slug": "t1", "label": "Tag 1"}],
    )

    market = Market.parse_response(payload)

    assert market.slug == "my-market"
    assert market.condition_id == _CONDITION_ID
    assert market.group_item_title == "Rain tomorrow"
    assert market.state.active is True
    assert market.state.start_date == datetime(2026, 5, 1, tzinfo=UTC)
    assert market.state.end_date == datetime(2026, 6, 1, tzinfo=UTC)
    assert market.metrics.volume == Decimal("100")
    assert market.metrics.volume_24hr == Decimal("20")
    assert market.metrics.liquidity == Decimal("50")
    assert market.prices.best_bid == Decimal("0.59")
    assert market.prices.spread == Decimal("0.02")
    assert market.trading.minimum_order_size == Decimal("5")
    assert market.trading.minimum_tick_size == Decimal("0.01")
    assert market.trading.fee_schedule is not None
    assert market.trading.fee_schedule.rate == Decimal("0.01")
    assert market.trading.fee_schedule.taker_only is False
    assert market.resolution.question_id == "0xQID"
    assert market.resolution.uma_resolution_status is UmaResolutionStatus.RESOLVED
    assert market.resolution.resolved_by == "0xRES"
    assert market.rewards.rewards_min_size == Decimal("10")
    assert market.sports.line == 2.5
    assert market.sports.game_start_time == datetime(2026, 5, 15, 18, 0, tzinfo=UTC)
    assert len(market.events) == 1
    assert market.events[0].id == "EVENT-1"
    assert market.tags[0].label == "Tag 1"


def test_market_parses_outcomes_from_json_encoded_strings() -> None:
    market = Market.parse_response(
        _minimal_market_payload(
            outcomes=json.dumps(["Yes", "No"]),
            outcomePrices=json.dumps(["0.7", "0.3"]),
            clobTokenIds=json.dumps(["A", "B"]),
        )
    )

    assert market.outcomes.yes.price == Decimal("0.7")
    assert market.outcomes.no.price == Decimal("0.3")
    assert market.outcomes.yes.token_id == "A"


def test_market_rejects_non_binary_outcomes() -> None:
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response(
            _minimal_market_payload(outcomes=["Yes", "No", "Maybe"]),
        )


def test_market_treats_empty_condition_id_as_none() -> None:
    market = Market.parse_response(_minimal_market_payload(conditionId=""))

    assert market.condition_id is None


def test_market_rejects_malformed_condition_id() -> None:
    with pytest.raises(UnexpectedResponseError, match="Market response"):
        Market.parse_response(_minimal_market_payload(conditionId="0x1234"))


def test_market_treats_empty_resolved_by_as_none() -> None:
    market = Market.parse_response(_minimal_market_payload(resolvedBy=""))

    assert market.resolution.resolved_by is None


def test_market_treats_empty_uma_status_as_none() -> None:
    market = Market.parse_response(_minimal_market_payload(umaResolutionStatus=""))

    assert market.resolution.uma_resolution_status is None


def test_market_currently_rejects_non_dict_tag_entries() -> None:
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response(
            _minimal_market_payload(
                tags=[{"id": "TAG-1", "slug": "t1", "label": "Tag 1"}, "ignored"],
            )
        )


def test_market_rejects_non_string_outcome_labels() -> None:
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response(_minimal_market_payload(outcomes=[1, 2]))


def test_market_rejects_non_string_clob_token_ids() -> None:
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response(_minimal_market_payload(clobTokenIds=[None, "TOK-2"]))


def test_market_rejects_integer_clob_token_ids() -> None:
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response(_minimal_market_payload(clobTokenIds=[123, 456]))


def test_market_rejects_non_string_position_ids() -> None:
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response(_minimal_market_payload(positionIds=[None, "POSITION-NO"]))


def test_market_rejects_malformed_outcome_price() -> None:
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response(_minimal_market_payload(outcomePrices=["bad", "0.5"]))


def test_market_rejects_malformed_metric() -> None:
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response(_minimal_market_payload(volume="not-a-decimal"))


def test_market_event_accepts_integer_id_per_ts_schema() -> None:
    market = Market.parse_response(
        _minimal_market_payload(events=[{"id": 12345, "slug": "e1", "title": "Event 1"}])
    )

    assert len(market.events) == 1
    assert market.events[0].id == "12345"


def _minimal_event_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"id": "EVENT-1"}
    payload.update(overrides)
    return payload


def test_event_parses_minimal_payload() -> None:
    event = Event.parse_response(_minimal_event_payload())

    assert event.id == "EVENT-1"
    assert event.markets == ()
    assert event.tags == ()
    assert event.series == ()
    assert event.creators == ()
    assert event.partners == ()


def test_event_normalizes_groups_from_flat_payload() -> None:
    payload = _minimal_event_payload(
        ticker="TICK",
        slug="event-slug",
        title="An Event",
        subtitle="sub",
        description="desc",
        category="cat",
        image="https://example.test/i.png",
        featuredImage="https://example.test/f.png",
        createdAt="2026-01-01T00:00:00Z",
        updatedAt="2026-02-01T00:00:00Z",
        active=True,
        closed=False,
        archived=False,
        new=False,
        featured=True,
        restricted=False,
        liquidity="100",
        volume="500",
        volume24hr="50",
        openInterest="200",
        competitive=1.5,
        commentCount=10,
        tweetCount=4,
        startDate="2026-05-01T00:00:00Z",
        endDate="2026-06-01T00:00:00Z",
        showAllOutcomes=True,
        color="#ff0000",
        countryName="USA",
        electionType="general",
        enableOrderBook=True,
        negRisk=True,
        negRiskMarketID="NRMID",
        negRiskFeeBips=5.0,
        resolutionSource="UMA",
        automaticallyResolved=True,
        estimateValue=True,
        cantEstimate=False,
        estimatedValue="123.45",
        seriesSlug="sport-series",
        gameStatus="live",
        gameId=999,
        homeTeamName="Home",
        awayTeamName="Away",
        teams=[{"id": 114315, "name": "Paris Saint-Germain FC", "ordering": "home"}],
        bestLines=[],
        markets=[],
        externalPartners=[
            {
                "id": 7,
                "externalId": "EXT-7",
                "partner": {"id": 1, "slug": "partner-a", "name": "Partner A"},
                "createdAt": "2026-03-01T00:00:00Z",
                "updatedAt": None,
            }
        ],
        eventCreators=[
            {
                "id": "CREATOR-1",
                "creatorName": "Alice",
                "creatorHandle": "@alice",
                "creatorUrl": "https://example.test/alice",
                "creatorImage": "https://example.test/alice.png",
                "createdAt": "2026-04-01T00:00:00Z",
                "updatedAt": "2026-04-02T00:00:00Z",
            }
        ],
        series=[
            {
                "id": "SERIES-1",
                "slug": "s1",
                "title": "Series 1",
                "volume": "1000",
                "liquidity": "500",
                "startDate": "2026-01-01T00:00:00Z",
            }
        ],
        tags=[{"id": "TAG-1", "slug": "t1", "label": "Tag 1"}],
        eventMetadata={"k": "v"},
    )

    event = Event.parse_response(payload)

    assert event.slug == "event-slug"
    assert event.title == "An Event"
    assert event.featured_image == "https://example.test/f.png"
    assert event.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert event.state.featured is True
    assert event.schedule.start_date == datetime(2026, 5, 1, tzinfo=UTC)
    assert event.metrics.volume == Decimal("500")
    assert event.metrics.open_interest == Decimal("200")
    assert event.metrics.comment_count == 10
    assert event.display.country_name == "USA"
    assert event.trading.neg_risk is True
    assert event.trading.neg_risk_market_id == "NRMID"
    assert event.resolution.source == "UMA"
    assert event.estimation.estimated_value == Decimal("123.45")
    assert event.sports.series_slug == "sport-series"
    assert event.sports.game_id == 999
    assert event.sports.teams[0].ordering is TeamOrdering.HOME
    assert len(event.partners) == 1
    assert event.partners[0].external_id == "EXT-7"
    assert event.partners[0].partner is not None
    assert event.partners[0].partner.slug == "partner-a"
    assert len(event.creators) == 1
    assert event.creators[0].name == "Alice"
    assert event.creators[0].url == "https://example.test/alice"
    assert len(event.series) == 1
    assert event.series[0].volume == Decimal("1000")
    assert event.tags[0].label == "Tag 1"
    assert event.metadata == {"k": "v"}


def test_event_skips_markets_with_non_binary_outcomes() -> None:
    event = Event.parse_response(
        _minimal_event_payload(
            markets=[
                {
                    "id": "M1",
                    "outcomes": ["Yes", "No"],
                    "outcomePrices": ["0.5", "0.5"],
                    "clobTokenIds": ["A", "B"],
                    "marketMakerAddress": "0xMM",
                },
                {
                    "id": "M2",
                    "outcomes": ["Only"],
                    "outcomePrices": ["1"],
                    "clobTokenIds": ["X"],
                    "marketMakerAddress": "0xMM",
                },
            ],
        )
    )

    assert len(event.markets) == 1
    assert event.markets[0].id == "M1"


def test_event_creator_falls_back_to_uppercase_url_field() -> None:
    event = Event.parse_response(
        _minimal_event_payload(
            eventCreators=[
                {
                    "id": "CREATOR-2",
                    "creatorName": "Bob",
                    "creatorURL": "https://example.test/bob",
                }
            ],
        )
    )

    assert event.creators[0].url == "https://example.test/bob"


def test_event_partner_without_partner_object() -> None:
    event = Event.parse_response(
        _minimal_event_payload(
            externalPartners=[{"id": 8, "externalId": "EXT-8", "partner": None}],
        )
    )

    assert isinstance(event.partners[0], EventPartner)
    assert event.partners[0].id == 8
    assert event.partners[0].partner is None


def test_event_accepts_integer_id_per_ts_schema() -> None:
    event = Event.parse_response({"id": 902661})

    assert event.id == "902661"


def test_event_parent_event_id_coerces_integer_to_event_id() -> None:
    event = Event.parse_response(_minimal_event_payload(parentEventId=570146))

    assert event.parent_event_id == "570146"


def test_event_parent_event_id_defaults_to_none() -> None:
    assert Event.parse_response(_minimal_event_payload()).parent_event_id is None
    assert Event.parse_response(_minimal_event_payload(parentEventId=None)).parent_event_id is None


def test_event_nested_series_accepts_integer_id() -> None:
    event = Event.parse_response(
        _minimal_event_payload(series=[{"id": 7, "slug": "s1", "title": "Series 1"}])
    )

    assert len(event.series) == 1
    assert event.series[0].id == "7"


def test_series_parses_with_nested_collections() -> None:
    series = Series.parse_response(
        {
            "id": "SERIES-1",
            "ticker": "S1",
            "slug": "series-slug",
            "title": "Series 1",
            "volume": "1500",
            "liquidity": "800",
            "events": [{"id": "EVENT-1"}],
            "collections": [{"id": "COLL-1", "slug": "c1"}],
            "tags": [{"id": "TAG-1", "label": "Tag 1"}],
        }
    )

    assert series.id == "SERIES-1"
    assert series.volume == Decimal("1500")
    assert series.events is not None and len(series.events) == 1
    assert series.collections is not None and series.collections[0].slug == "c1"


def test_series_accepts_integer_id_per_ts_schema() -> None:
    series = Series.parse_response({"id": 42, "slug": "march-madness"})

    assert series.id == "42"


def test_tag_inherits_tag_reference_fields_and_adds_chats() -> None:
    tag = Tag.parse_response(
        {
            "id": "TAG-1",
            "label": "Politics",
            "slug": "politics",
            "isCarousel": True,
            "templates": [
                {
                    "id": "TPL-1",
                    "displayName": "Template",
                }
            ],
        }
    )

    assert tag.id == "TAG-1"
    assert tag.label == "Politics"
    assert tag.is_carousel is True
    assert tag.templates is not None and tag.templates[0].display_name == "Template"


def test_tag_reference_parses_dates() -> None:
    ref = TagReference.parse_response(
        {
            "id": "TAG-1",
            "publishedAt": "2026-01-01T00:00:00Z",
            "createdAt": "2026-01-02T00:00:00Z",
            "updatedAt": "2026-01-03T00:00:00Z",
        }
    )

    assert ref.published_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert ref.created_at == datetime(2026, 1, 2, tzinfo=UTC)
    assert ref.updated_at == datetime(2026, 1, 3, tzinfo=UTC)


def test_related_tag_renames_id_aliases() -> None:
    related = RelatedTag.parse_response({"id": "REL-1", "tagID": 10, "relatedTagID": 20, "rank": 3})

    assert related.id == "REL-1"
    assert related.tag_id == 10
    assert related.related_tag_id == 20
    assert related.rank == 3


def test_comment_renames_parent_ids_to_strings() -> None:
    comment = Comment.parse_response(
        {
            "id": "C-1",
            "body": "hello",
            "parentEntityType": "Event",
            "parentEntityID": 12345,
            "parentCommentID": 67890,
            "userAddress": "0xUSER",
            "createdAt": "2026-01-01T00:00:00Z",
            "reportCount": 0,
            "reactionCount": 2,
        }
    )

    assert comment.id == "C-1"
    assert comment.parent_entity_id == "12345"
    assert comment.parent_comment_id == "67890"
    assert comment.user_address == "0xUSER"
    assert comment.created_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_comment_nests_profile_media_and_reactions() -> None:
    comment = Comment.parse_response(
        {
            "id": "C-2",
            "body": "with attachments",
            "profile": {
                "name": "Alice",
                "proxyWallet": "0xALICE",
                "isMod": True,
                "positions": [{"tokenId": "TOK-1", "positionSize": 100}],
            },
            "media": [
                {
                    "id": "M-1",
                    "commentID": 2,
                    "url": "https://example.test/m.png",
                    "mediaType": "image",
                    "createdAt": "2026-02-01T00:00:00Z",
                }
            ],
            "reactions": [
                {
                    "id": "R-1",
                    "commentID": 2,
                    "reactionType": "HEART",
                    "userAddress": "0xBOB",
                    "createdAt": "2026-02-02T00:00:00Z",
                }
            ],
        }
    )

    assert comment.profile is not None
    assert comment.profile.wallet == "0xALICE"
    assert comment.profile.is_mod is True
    assert comment.profile.positions is not None
    assert comment.profile.positions[0].token_id == "TOK-1"
    assert comment.media is not None
    assert comment.media[0].url == "https://example.test/m.png"
    assert comment.reactions is not None
    assert comment.reactions[0].reaction_type == "HEART"
    assert comment.reactions[0].user_address == "0xBOB"


def test_comment_profile_position_parses_token_id() -> None:
    position = CommentPosition.parse_response({"tokenId": "TOK-99", "positionSize": 42})

    assert position.token_id == "TOK-99"
    assert position.position_size == 42


def test_comment_profile_handles_missing_wallet() -> None:
    profile = CommentProfile.parse_response({"name": "Bob"})

    assert profile.name == "Bob"
    assert profile.wallet is None


def test_comment_media_parses_created_at() -> None:
    media = CommentMedia.parse_response({"id": "M-1", "createdAt": "2026-01-01T00:00:00Z"})

    assert media.created_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_reaction_parses_profile_and_dates() -> None:
    reaction = Reaction.parse_response(
        {
            "id": "R-1",
            "commentID": 5,
            "reactionType": "HEART",
            "userAddress": "0xUSER",
            "createdAt": "2026-01-01T00:00:00Z",
            "profile": {"name": "Carol", "proxyWallet": "0xCAROL"},
        }
    )

    assert reaction.comment_id == 5
    assert reaction.reaction_type == "HEART"
    assert reaction.profile is not None
    assert reaction.profile.wallet == "0xCAROL"


def test_public_profile_renames_proxy_wallet_and_parses_created_at() -> None:
    profile = PublicProfile.parse_response(
        {
            "createdAt": "2026-01-01T00:00:00Z",
            "proxyWallet": "0xUSER",
            "displayUsernamePublic": True,
            "pseudonym": "anonymous",
            "name": "Alice",
            "users": [{"id": "U-1", "creator": True, "mod": False}],
            "verifiedBadge": True,
        }
    )

    assert profile.wallet == "0xUSER"
    assert profile.display_username_public is True
    assert profile.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert profile.users is not None
    assert profile.users[0].creator is True


def test_public_profile_handles_missing_proxy_wallet() -> None:
    profile = PublicProfile.parse_response({"name": "Bob"})

    assert profile.name == "Bob"
    assert profile.wallet is None


def test_sports_metadata_requires_all_string_fields() -> None:
    meta = SportsMetadata.parse_response(
        {
            "id": 1,
            "sport": "Basketball",
            "image": "https://example.test/b.png",
            "resolution": "live",
            "ordering": "manual",
            "tags": "nba",
            "series": "regular",
            "createdAt": "2026-01-01T00:00:00Z",
        }
    )

    assert meta.id == 1
    assert meta.sport == "Basketball"
    assert meta.created_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_sports_market_types_parses_market_types() -> None:
    types = SportsMarketTypes.parse_response({"marketTypes": ["moneyline", "spread"]})

    assert types.market_types == ("moneyline", "spread")


def test_sports_market_types_handles_missing_field() -> None:
    types = SportsMarketTypes.parse_response({})

    assert types.market_types is None


def test_profile_renames_proxy_wallet() -> None:
    from polymarket.models.gamma import Profile

    profile = Profile.parse_response(
        {
            "id": "P-1",
            "name": "Alice",
            "proxyWallet": "0xABC",
            "createdAt": "2026-01-01T00:00:00Z",
            "verifiedBadge": True,
        }
    )

    assert profile.id == "P-1"
    assert profile.name == "Alice"
    assert profile.wallet == "0xABC"
    assert profile.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert profile.verified_badge is True


def test_profile_handles_missing_wallet() -> None:
    from polymarket.models.gamma import Profile

    profile = Profile.parse_response({"name": "Bob"})

    assert profile.name == "Bob"
    assert profile.wallet is None


def test_search_tag_parses_event_count() -> None:
    from polymarket.models.gamma import SearchTag

    tag = SearchTag.parse_response(
        {"id": "TAG-1", "label": "Politics", "slug": "politics", "event_count": 42}
    )

    assert tag.id == "TAG-1"
    assert tag.label == "Politics"
    assert tag.event_count == 42


def test_search_results_parses_bundle_payload() -> None:
    from polymarket.models.gamma import SearchResults

    results = SearchResults.parse_response(
        {
            "events": [{"id": "E-1"}],
            "tags": [{"id": "T-1", "label": "T", "slug": "t", "event_count": 1}],
            "profiles": [{"id": "P-1", "name": "Alice"}],
            "pagination": {"hasMore": True, "totalResults": 100},
        }
    )

    assert len(results.events) == 1
    assert len(results.tags) == 1
    assert len(results.profiles) == 1


def test_search_results_handles_empty_response() -> None:
    from polymarket.models.gamma import SearchResults

    results = SearchResults.parse_response({})

    assert results.events == ()
    assert results.tags == ()
    assert results.profiles == ()


def test_search_results_accepts_null_arrays_as_empty() -> None:
    from polymarket.models.gamma import SearchResults

    results = SearchResults.parse_response(
        {"events": None, "tags": None, "profiles": None, "pagination": None}
    )

    assert results.events == ()
    assert results.tags == ()
    assert results.profiles == ()


def test_search_results_rejects_non_list_events() -> None:
    from polymarket.models.gamma import SearchResults

    with pytest.raises(UnexpectedResponseError):
        SearchResults.parse_response({"events": ""})


def test_search_results_rejects_integer_events() -> None:
    from polymarket.models.gamma import SearchResults

    with pytest.raises(UnexpectedResponseError):
        SearchResults.parse_response({"events": 0})


def test_search_page_response_extracts_pagination_metadata() -> None:
    from polymarket.models.gamma import SearchResults

    page_payload = SearchResults.parse_page_response(
        {
            "events": [{"id": "E-1"}],
            "tags": [],
            "profiles": [],
            "pagination": {"hasMore": True, "totalResults": 100},
        }
    )

    assert page_payload.has_more is True
    assert page_payload.total_count == 100
    assert len(page_payload.items.events) == 1


def test_search_page_response_handles_missing_pagination() -> None:
    from polymarket.models.gamma import SearchResults

    page_payload = SearchResults.parse_page_response({"events": [], "tags": [], "profiles": []})

    assert page_payload.has_more is False
    assert page_payload.total_count is None


def test_search_page_response_handles_null_pagination() -> None:
    from polymarket.models.gamma import SearchResults

    page_payload = SearchResults.parse_page_response({"pagination": None})

    assert page_payload.has_more is False
    assert page_payload.total_count is None


def test_search_page_response_rejects_non_object_pagination() -> None:
    from polymarket.models.gamma import SearchResults

    with pytest.raises(UnexpectedResponseError):
        SearchResults.parse_page_response({"pagination": "terminal"})


def test_search_page_response_rejects_string_has_more() -> None:
    from polymarket.models.gamma import SearchResults

    with pytest.raises(UnexpectedResponseError):
        SearchResults.parse_page_response({"pagination": {"hasMore": "false"}})


def test_search_page_response_rejects_int_has_more() -> None:
    from polymarket.models.gamma import SearchResults

    with pytest.raises(UnexpectedResponseError):
        SearchResults.parse_page_response({"pagination": {"hasMore": 1}})


def test_search_page_response_accepts_null_has_more_as_false() -> None:
    from polymarket.models.gamma import SearchResults

    page_payload = SearchResults.parse_page_response({"pagination": {"hasMore": None}})

    assert page_payload.has_more is False


def test_search_page_response_rejects_bool_total_results() -> None:
    from polymarket.models.gamma import SearchResults

    with pytest.raises(UnexpectedResponseError):
        SearchResults.parse_page_response({"pagination": {"totalResults": True}})


def test_search_page_response_rejects_string_total_results() -> None:
    from polymarket.models.gamma import SearchResults

    with pytest.raises(UnexpectedResponseError):
        SearchResults.parse_page_response({"pagination": {"totalResults": "10"}})


def test_tag_reference_parse_response_list_rejects_non_list() -> None:
    with pytest.raises(UnexpectedResponseError):
        TagReference.parse_response_list({"not": "a list"})


def test_market_parse_response_raises_unexpected_response_on_bad_payload() -> None:
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response({"id": "MARKET-1"})
