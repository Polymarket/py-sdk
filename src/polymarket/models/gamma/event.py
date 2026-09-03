"""Event models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from pydantic import Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.gamma.common import (
    BestLine,
    ImageOptimization,
    Partner,
    SportsMetadata,
    Team,
    coerce_string_id,
    parse_dicts,
    parse_optional_date,
    parse_optional_datetime,
    parse_optional_decimal,
    parse_sequence,
)
from polymarket.models.gamma.market import Market, ProtocolVersion
from polymarket.models.types import (
    EventCreatorId,
    EventExternalPartnerMappingId,
    EventId,
    SeriesId,
    TagId,
)


class EventPartner(BaseModel):
    id: EventExternalPartnerMappingId
    external_id: str = Field(validation_alias="externalId")
    partner: Partner | None = None
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class EventState(BaseModel):
    active: bool | None = None
    closed: bool | None = None
    archived: bool | None = None
    new: bool | None = None
    featured: bool | None = None
    restricted: bool | None = None
    cyom: bool | None = None
    live: bool | None = None
    ended: bool | None = None
    automatically_active: bool | None = Field(default=None, validation_alias="automaticallyActive")
    comments_enabled: bool | None = Field(default=None, validation_alias="commentsEnabled")
    requires_translation: bool | None = Field(
        default=None,
        validation_alias="requiresTranslation",
    )


class EventSchedule(BaseModel):
    start_date: datetime | None = Field(default=None, validation_alias="startDate")
    creation_date: datetime | None = Field(default=None, validation_alias="creationDate")
    end_date: datetime | None = Field(default=None, validation_alias="endDate")
    closed_time: datetime | None = Field(default=None, validation_alias="closedTime")
    start_time: datetime | None = Field(default=None, validation_alias="startTime")
    event_date: date | None = Field(default=None, validation_alias="eventDate")
    event_week: int | None = Field(default=None, validation_alias="eventWeek")
    finished_at: datetime | None = Field(default=None, validation_alias="finishedAt")

    @field_validator(
        "start_date",
        "creation_date",
        "end_date",
        "closed_time",
        "start_time",
        "finished_at",
        mode="before",
    )
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)

    @field_validator("event_date", mode="before")
    @classmethod
    def _parse_event_date(cls, value: object) -> date | None:
        return parse_optional_date(value)


class EventMetrics(BaseModel):
    liquidity: Decimal | None = None
    liquidity_amm: Decimal | None = Field(default=None, validation_alias="liquidityAmm")
    liquidity_clob: Decimal | None = Field(default=None, validation_alias="liquidityClob")
    volume: Decimal | None = None
    volume_24hr: Decimal | None = Field(default=None, validation_alias="volume24hr")
    volume_1wk: Decimal | None = Field(default=None, validation_alias="volume1wk")
    volume_1mo: Decimal | None = Field(default=None, validation_alias="volume1mo")
    volume_1yr: Decimal | None = Field(default=None, validation_alias="volume1yr")
    open_interest: Decimal | None = Field(default=None, validation_alias="openInterest")
    competitive: float | None = None
    comment_count: int | None = Field(default=None, validation_alias="commentCount")
    tweet_count: int | None = Field(default=None, validation_alias="tweetCount")

    @field_validator(
        "liquidity",
        "liquidity_amm",
        "liquidity_clob",
        "volume",
        "volume_24hr",
        "volume_1wk",
        "volume_1mo",
        "volume_1yr",
        "open_interest",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class EventDisplay(BaseModel):
    sort_by: str | None = Field(default=None, validation_alias="sortBy")
    show_all_outcomes: bool | None = Field(default=None, validation_alias="showAllOutcomes")
    show_market_images: bool | None = Field(default=None, validation_alias="showMarketImages")
    gmp_chart_mode: str | None = Field(default=None, validation_alias="gmpChartMode")
    color: str | None = None
    featured_order: int | None = Field(default=None, validation_alias="featuredOrder")
    country_name: str | None = Field(default=None, validation_alias="countryName")
    election_type: str | None = Field(default=None, validation_alias="electionType")
    image_optimized: ImageOptimization | None = Field(
        default=None,
        validation_alias="imageOptimized",
    )
    icon_optimized: ImageOptimization | None = Field(default=None, validation_alias="iconOptimized")
    featured_image_optimized: ImageOptimization | None = Field(
        default=None,
        validation_alias="featuredImageOptimized",
    )


class EventTrading(BaseModel):
    enable_order_book: bool | None = Field(default=None, validation_alias="enableOrderBook")
    neg_risk: bool | None = Field(default=None, validation_alias="negRisk")
    neg_risk_market_id: str | None = Field(default=None, validation_alias="negRiskMarketId")
    neg_risk_fee_bips: float | None = Field(default=None, validation_alias="negRiskFeeBips")
    enable_neg_risk: bool | None = Field(default=None, validation_alias="enableNegRisk")
    neg_risk_augmented: bool | None = Field(default=None, validation_alias="negRiskAugmented")
    cumulative_markets: bool | None = Field(default=None, validation_alias="cumulativeMarkets")


class EventResolution(BaseModel):
    source: str | None = None
    automatically_resolved: bool | None = Field(
        default=None,
        validation_alias="automaticallyResolved",
    )


class EventEstimation(BaseModel):
    estimate_value: bool | None = Field(default=None, validation_alias="estimateValue")
    cant_estimate: bool | None = Field(default=None, validation_alias="cantEstimate")
    estimated_value: Decimal | None = Field(default=None, validation_alias="estimatedValue")

    @field_validator("estimated_value", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class EventSportsMetadata(BaseModel):
    series_slug: str | None = Field(default=None, validation_alias="seriesSlug")
    score: str | None = None
    elapsed: str | None = None
    period: str | None = None
    game_status: str | None = Field(default=None, validation_alias="gameStatus")
    game_id: int | None = Field(default=None, validation_alias="gameId")
    rescheduled_from_game_id: int | None = Field(
        default=None,
        validation_alias="rescheduledFromGameId",
    )
    sportsradar_match_id: str | None = Field(default=None, validation_alias="sportsradarMatchId")
    home_team_name: str | None = Field(default=None, validation_alias="homeTeamName")
    away_team_name: str | None = Field(default=None, validation_alias="awayTeamName")
    spreads_main_line: float | None = Field(default=None, validation_alias="spreadsMainLine")
    totals_main_line: float | None = Field(default=None, validation_alias="totalsMainLine")
    best_lines: tuple[BestLine, ...] = Field(default=())
    teams: tuple[Team, ...] = Field(default=())
    sport: SportsMetadata | None = None
    last_highlight: str | None = Field(default=None, validation_alias="lastHighlight")
    last_highlight_type: str | None = Field(default=None, validation_alias="lastHighlightType")
    last_highlight_at: datetime | None = Field(default=None, validation_alias="lastHighlightAt")

    @field_validator("last_highlight_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class EventSeries(BaseModel):
    id: SeriesId
    slug: str | None = None
    title: str | None = None
    subtitle: str | None = None
    description: str | None = None
    image: str | None = None
    icon: str | None = None
    active: bool | None = None
    closed: bool | None = None
    archived: bool | None = None
    volume: Decimal | None = None
    liquidity: Decimal | None = None
    start_date: datetime | None = Field(default=None, validation_alias="startDate")

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: object) -> object:
        return coerce_string_id(value)

    @field_validator("volume", "liquidity", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)

    @field_validator("start_date", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class EventTag(BaseModel):
    id: TagId
    slug: str | None = None
    label: str | None = None


class EventCreator(BaseModel):
    id: EventCreatorId
    name: str | None = None
    handle: str | None = None
    url: str | None = None
    image: str | None = None
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class Event(BaseModel):
    """A Polymarket event."""

    id: EventId
    version: ProtocolVersion | None = None
    parent_event_id: EventId | None = Field(default=None, validation_alias="parentEventId")
    ticker: str | None = None
    slug: str | None = None
    title: str | None = None
    subtitle: str | None = None
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    image: str | None = None
    icon: str | None = None
    featured_image: str | None = Field(default=None, validation_alias="featuredImage")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")
    published_at: datetime | None = Field(default=None, validation_alias="publishedAt")
    state: EventState
    schedule: EventSchedule
    metrics: EventMetrics
    display: EventDisplay
    trading: EventTrading
    resolution: EventResolution
    estimation: EventEstimation
    sports: EventSportsMetadata
    partners: tuple[EventPartner, ...]
    metadata: dict[str, object] | None = None
    markets: tuple[Market, ...]
    series: tuple[EventSeries, ...]
    tags: tuple[EventTag, ...]
    creators: tuple[EventCreator, ...]

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr

        @safe_html_repr
        def render(self: Event) -> str:
            if self.state.closed or self.state.ended:
                status = "closed"
            elif self.state.active:
                status = "open"
            elif self.state.archived:
                status = "archived"
            else:
                status = "unknown"
            title = f"{self.title or '(no title)'}  ·  {status}"
            rows: list[tuple[str, str]] = []
            if self.slug:
                rows.append(("slug", self.slug))
            rows.append(("markets", str(len(self.markets))))
            if self.schedule.end_date is not None:
                rows.append(("end", self.schedule.end_date.date().isoformat()))
            return card(title, rows=rows)

        return render(self)

    @field_validator("id", "parent_event_id", mode="before")
    @classmethod
    def _coerce_id(cls, value: object) -> object:
        return coerce_string_id(value)

    @field_validator("created_at", "updated_at", "published_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize_event(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = cast(dict[str, Any], value)
        if "state" in data:
            return data

        return {
            "id": data.get("id"),
            "version": data.get("version"),
            "parent_event_id": data.get("parentEventId"),
            "ticker": data.get("ticker"),
            "slug": data.get("slug"),
            "title": data.get("title"),
            "subtitle": data.get("subtitle"),
            "description": data.get("description"),
            "category": data.get("category"),
            "subcategory": data.get("subcategory"),
            "image": data.get("image"),
            "icon": data.get("icon"),
            "featured_image": data.get("featuredImage"),
            "created_at": data.get("createdAt"),
            "updated_at": data.get("updatedAt"),
            "published_at": data.get("published_at"),
            "state": {
                "active": data.get("active"),
                "closed": data.get("closed"),
                "archived": data.get("archived"),
                "new": data.get("new"),
                "featured": data.get("featured"),
                "restricted": data.get("restricted"),
                "cyom": data.get("cyom"),
                "live": data.get("live"),
                "ended": data.get("ended"),
                "automatically_active": data.get("automaticallyActive"),
                "comments_enabled": data.get("commentsEnabled"),
                "requires_translation": data.get("requiresTranslation"),
            },
            "schedule": {
                "start_date": data.get("startDate"),
                "creation_date": data.get("creationDate"),
                "end_date": data.get("endDate"),
                "closed_time": data.get("closedTime"),
                "start_time": data.get("startTime"),
                "event_date": data.get("eventDate"),
                "event_week": data.get("eventWeek"),
                "finished_at": data.get("finishedTimestamp"),
            },
            "metrics": {
                "liquidity": data.get("liquidity"),
                "liquidity_amm": data.get("liquidityAmm"),
                "liquidity_clob": data.get("liquidityClob"),
                "volume": data.get("volume"),
                "volume_24hr": data.get("volume24hr"),
                "volume_1wk": data.get("volume1wk"),
                "volume_1mo": data.get("volume1mo"),
                "volume_1yr": data.get("volume1yr"),
                "open_interest": data.get("openInterest"),
                "competitive": data.get("competitive"),
                "comment_count": data.get("commentCount"),
                "tweet_count": data.get("tweetCount"),
            },
            "display": {
                "sort_by": data.get("sortBy"),
                "show_all_outcomes": data.get("showAllOutcomes"),
                "show_market_images": data.get("showMarketImages"),
                "gmp_chart_mode": data.get("gmpChartMode"),
                "color": data.get("color"),
                "featured_order": data.get("featuredOrder"),
                "country_name": data.get("countryName"),
                "election_type": data.get("electionType"),
                "image_optimized": data.get("imageOptimized"),
                "icon_optimized": data.get("iconOptimized"),
                "featured_image_optimized": data.get("featuredImageOptimized"),
            },
            "trading": {
                "enable_order_book": data.get("enableOrderBook"),
                "neg_risk": data.get("negRisk"),
                "neg_risk_market_id": data.get("negRiskMarketID"),
                "neg_risk_fee_bips": data.get("negRiskFeeBips"),
                "enable_neg_risk": data.get("enableNegRisk"),
                "neg_risk_augmented": data.get("negRiskAugmented"),
                "cumulative_markets": data.get("cumulativeMarkets"),
            },
            "resolution": {
                "source": data.get("resolutionSource"),
                "automatically_resolved": data.get("automaticallyResolved"),
            },
            "estimation": {
                "estimate_value": data.get("estimateValue"),
                "cant_estimate": data.get("cantEstimate"),
                "estimated_value": data.get("estimatedValue"),
            },
            "sports": {
                "series_slug": data.get("seriesSlug"),
                "score": data.get("score"),
                "elapsed": data.get("elapsed"),
                "period": data.get("period"),
                "game_status": data.get("gameStatus"),
                "game_id": data.get("gameId"),
                "rescheduled_from_game_id": data.get("rescheduledFromGameId"),
                "sportsradar_match_id": data.get("sportsradarMatchId"),
                "home_team_name": data.get("homeTeamName"),
                "away_team_name": data.get("awayTeamName"),
                "spreads_main_line": data.get("spreadsMainLine"),
                "totals_main_line": data.get("totalsMainLine"),
                "best_lines": data.get("bestLines") or [],
                "teams": data.get("teams") or [],
                "sport": data.get("sport"),
                "last_highlight": data.get("lastHighlight"),
                "last_highlight_type": data.get("lastHighlightType"),
                "last_highlight_at": data.get("lastHighlightAt"),
            },
            "partners": [
                _normalize_event_partner(item) for item in parse_dicts(data.get("externalPartners"))
            ],
            "metadata": data.get("eventMetadata"),
            "markets": [
                market
                for item in parse_dicts(data.get("markets"))
                if (market := _normalize_event_market(item)) is not None
            ],
            "series": [_normalize_event_series(item) for item in parse_dicts(data.get("series"))],
            "tags": [_normalize_event_tag(item) for item in parse_dicts(data.get("tags"))],
            "creators": [
                _normalize_event_creator(item) for item in parse_dicts(data.get("eventCreators"))
            ],
        }


def _normalize_event_partner(partner: dict[str, Any]) -> dict[str, object]:
    raw_partner = partner.get("partner")
    parsed_partner = cast(dict[str, Any], raw_partner) if isinstance(raw_partner, dict) else None
    return {
        "id": partner.get("id"),
        "external_id": partner.get("externalId"),
        "partner": {
            "id": parsed_partner.get("id"),
            "slug": parsed_partner.get("slug"),
            "name": parsed_partner.get("name"),
        }
        if parsed_partner is not None
        else None,
        "created_at": partner.get("createdAt"),
        "updated_at": partner.get("updatedAt"),
    }


def _normalize_event_market(market: dict[str, Any]) -> Market | None:
    if len(parse_sequence(market.get("outcomes"))) != 2:
        return None

    return Market.parse_response(market)


def _normalize_event_series(series: dict[str, Any]) -> dict[str, object]:
    return {
        "id": series.get("id"),
        "slug": series.get("slug"),
        "title": series.get("title"),
        "subtitle": series.get("subtitle"),
        "description": series.get("description"),
        "image": series.get("image"),
        "icon": series.get("icon"),
        "active": series.get("active"),
        "closed": series.get("closed"),
        "archived": series.get("archived"),
        "volume": series.get("volume"),
        "liquidity": series.get("liquidity"),
        "start_date": series.get("startDate"),
    }


def _normalize_event_tag(tag: dict[str, Any]) -> dict[str, object]:
    return {"id": tag.get("id"), "slug": tag.get("slug"), "label": tag.get("label")}


def _normalize_event_creator(creator: dict[str, Any]) -> dict[str, object]:
    return {
        "id": creator.get("id"),
        "name": creator.get("creatorName"),
        "handle": creator.get("creatorHandle"),
        "url": creator.get("creatorUrl") or creator.get("creatorURL"),
        "image": creator.get("creatorImage"),
        "created_at": creator.get("createdAt"),
        "updated_at": creator.get("updatedAt"),
    }


__all__ = [
    "Event",
    "EventCreator",
    "EventDisplay",
    "EventEstimation",
    "EventMetrics",
    "EventPartner",
    "EventResolution",
    "EventSchedule",
    "EventSeries",
    "EventSportsMetadata",
    "EventState",
    "EventTag",
    "EventTrading",
]
