"""Shared public SDK models."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, cast

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.types import (
    BestLineId,
    CategoryId,
    ChatId,
    CollectionId,
    ImageOptimizationId,
    PartnerId,
    SeriesId,
    SportId,
    TagId,
    TeamId,
    TemplateId,
)


class ImageOptimization(BaseModel):
    id: ImageOptimizationId
    image_url_source: str | None = Field(default=None, validation_alias="imageUrlSource")
    image_url_optimized: str | None = Field(default=None, validation_alias="imageUrlOptimized")
    image_size_kb_source: float | None = Field(default=None, validation_alias="imageSizeKbSource")
    image_size_kb_optimized: float | None = Field(
        default=None,
        validation_alias="imageSizeKbOptimized",
    )
    image_optimized_complete: bool | None = Field(
        default=None,
        validation_alias="imageOptimizedComplete",
    )
    image_optimized_last_updated: datetime | None = Field(
        default=None,
        validation_alias="imageOptimizedLastUpdated",
    )
    rel_id: int | None = Field(default=None, validation_alias="relID")
    field: str | None = None
    relname: str | None = None


class CategoryReference(BaseModel):
    id: CategoryId
    label: str | None = None
    parent_category: str | None = Field(default=None, validation_alias="parentCategory")
    slug: str | None = None
    published_at: datetime | None = Field(default=None, validation_alias="publishedAt")
    created_by: str | None = Field(default=None, validation_alias="createdBy")
    updated_by: str | None = Field(default=None, validation_alias="updatedBy")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")

    @field_validator("published_at", "created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class TagReference(BaseModel):
    id: TagId
    label: str | None = None
    slug: str | None = None
    force_show: bool | None = Field(default=None, validation_alias="forceShow")
    published_at: datetime | None = Field(default=None, validation_alias="publishedAt")
    created_by: int | None = Field(default=None, validation_alias="createdBy")
    updated_by: int | None = Field(default=None, validation_alias="updatedBy")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")
    force_hide: bool | None = Field(default=None, validation_alias="forceHide")
    is_carousel: bool | None = Field(default=None, validation_alias="isCarousel")
    requires_translation: bool | None = Field(
        default=None,
        validation_alias="requiresTranslation",
    )
    active_events_count: int | None = Field(default=None, validation_alias="activeEventsCount")

    @field_validator("published_at", "created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class CollectionReference(BaseModel):
    id: CollectionId
    ticker: str | None = None
    slug: str | None = None
    title: str | None = None
    subtitle: str | None = None
    collection_type: str | None = Field(default=None, validation_alias="collectionType")
    description: str | None = None
    tags: str | None = None
    image: str | None = None
    icon: str | None = None
    header_image: str | None = Field(default=None, validation_alias="headerImage")
    layout: str | None = None
    active: bool | None = None
    closed: bool | None = None
    archived: bool | None = None
    new: bool | None = None
    featured: bool | None = None
    restricted: bool | None = None
    is_template: bool | None = Field(default=None, validation_alias="isTemplate")
    template_variables: str | None = Field(default=None, validation_alias="templateVariables")
    published_at: datetime | None = Field(default=None, validation_alias="publishedAt")
    created_by: str | None = Field(default=None, validation_alias="createdBy")
    updated_by: str | None = Field(default=None, validation_alias="updatedBy")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")
    disqus_thread: str | None = Field(default=None, validation_alias="disqusThread")
    comments_enabled: bool | None = Field(default=None, validation_alias="commentsEnabled")

    @field_validator("published_at", "created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class SeriesReference(BaseModel):
    id: SeriesId
    ticker: str | None = None
    slug: str | None = None
    title: str | None = None
    subtitle: str | None = None
    series_type: str | None = Field(default=None, validation_alias="seriesType")
    recurrence: str | None = None
    description: str | None = None
    image: str | None = None
    icon: str | None = None
    layout: str | None = None
    active: bool | None = None
    closed: bool | None = None
    archived: bool | None = None
    new: bool | None = None
    featured: bool | None = None
    restricted: bool | None = None
    is_template: bool | None = Field(default=None, validation_alias="isTemplate")
    template_variables: bool | None = Field(default=None, validation_alias="templateVariables")
    published_at: datetime | None = Field(default=None, validation_alias="publishedAt")
    created_by: str | None = Field(default=None, validation_alias="createdBy")
    updated_by: str | None = Field(default=None, validation_alias="updatedBy")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")
    comments_enabled: bool | None = Field(default=None, validation_alias="commentsEnabled")
    competitive: str | None = None
    volume_24hr: Decimal | None = Field(default=None, validation_alias="volume24hr")
    volume: Decimal | None = None
    liquidity: Decimal | None = None
    start_date: datetime | None = Field(default=None, validation_alias="startDate")
    pyth_token_id: str | None = Field(default=None, validation_alias="pythTokenID")
    cg_asset_name: str | None = Field(default=None, validation_alias="cgAssetName")
    score: int | None = None
    comment_count: int | None = Field(default=None, validation_alias="commentCount")
    requires_translation: bool | None = Field(
        default=None,
        validation_alias="requiresTranslation",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: object) -> object:
        return coerce_string_id(value)

    @field_validator("volume_24hr", "volume", "liquidity", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)

    @field_validator("published_at", "created_at", "updated_at", "start_date", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class TemplateReference(BaseModel):
    id: TemplateId
    display_name: str | None = Field(default=None, validation_alias="displayName")
    event_title: str | None = Field(default=None, validation_alias="eventTitle")
    event_slug: str | None = Field(default=None, validation_alias="eventSlug")
    description: str | None = None
    resolution_source: str | None = Field(default=None, validation_alias="resolutionSource")
    markets_order: str | None = Field(default=None, validation_alias="marketsOrder")
    markets_neg_risk: bool | None = Field(default=None, validation_alias="marketsNegRisk")
    markets_augmented_neg_risk: bool | None = Field(
        default=None,
        validation_alias="marketsAugmentedNegRisk",
    )
    markets_show_images: bool | None = Field(default=None, validation_alias="marketsShowImages")
    markets: str | None = None
    user_variables: str | None = Field(default=None, validation_alias="userVariables")
    creator_user_id: str | None = Field(default=None, validation_alias="creatorUserId")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class Chat(BaseModel):
    id: ChatId
    channel_id: str | None = Field(default=None, validation_alias="channelId")
    channel_name: str | None = Field(default=None, validation_alias="channelName")
    channel_image: str | None = Field(default=None, validation_alias="channelImage")
    live: bool | None = None
    start_time: datetime | None = Field(default=None, validation_alias="startTime")
    end_time: datetime | None = Field(default=None, validation_alias="endTime")

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class Partner(BaseModel):
    id: PartnerId
    slug: str
    name: str


class BestLine(BaseModel):
    id: BestLineId
    line_type: str | None = Field(default=None, validation_alias="lineType")
    line: float | None = None


class TeamOrdering(StrEnum):
    """A team's side in a sports event."""

    HOME = "home"
    AWAY = "away"


class Team(BaseModel):
    id: TeamId
    name: str | None = None
    league: str | None = None
    record: str | None = None
    logo: str | None = None
    abbreviation: str | None = None
    alias: str | None = None
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")
    provider_id: int | None = Field(default=None, validation_alias="providerId")
    color: str | None = None
    ordering: TeamOrdering | None = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class SportsMetadata(BaseModel):
    id: SportId
    sport: str
    image: str
    resolution: str
    ordering: str
    tags: str
    series: str
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class SportsMarketTypes(BaseModel):
    market_types: tuple[str, ...] | None = Field(default=None, validation_alias="marketTypes")


def parse_sequence(value: object) -> tuple[Any, ...]:
    if value is None:
        return ()

    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            msg = "expected a JSON array"
            raise ValueError(msg)
        return tuple(cast(list[Any], parsed))

    if isinstance(value, list | tuple):
        return tuple(cast(list[Any] | tuple[Any, ...], value))

    msg = "expected a sequence"
    raise ValueError(msg)


def parse_dicts(value: object) -> tuple[dict[str, Any], ...]:
    items = parse_sequence(value)
    dicts: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            msg = "expected an object"
            raise ValueError(msg)
        dicts.append(cast(dict[str, Any], item))
    return tuple(dicts)


def parse_string_sequence(value: object) -> tuple[str, ...]:
    items = parse_sequence(value)
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            msg = f"expected a string, got {type(item).__name__}"
            raise ValueError(msg)
        result.append(item)
    return tuple(result)


def coerce_string_id(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    return value


def empty_string_to_none(value: object) -> object | None:
    return None if value == "" else value


def parse_optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        msg = f"invalid decimal: {value!r}"
        raise ValueError(msg) from error


def parse_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        msg = f"invalid decimal: {value!r}"
        raise ValueError(msg) from error


def parse_optional_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        normalized = value.replace(" ", "T", 1)
        if normalized.endswith("+00"):
            normalized = f"{normalized}:00"
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))

    msg = "expected a datetime"
    raise ValueError(msg)


def parse_optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        if len(value) == 10 and value[4] == "-" and value[7] == "-":
            try:
                return date.fromisoformat(value)
            except ValueError as error:
                msg = f"invalid date: {value!r}"
                raise ValueError(msg) from error
        parsed = parse_optional_datetime(value)
        if parsed is None:
            return None
        return parsed.date()

    msg = "expected a date"
    raise ValueError(msg)


def parse_epoch_seconds_optional(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(int(value), tz=UTC)
    if isinstance(value, str) and value.isdigit():
        return datetime.fromtimestamp(int(value), tz=UTC)
    if isinstance(value, datetime):
        return value
    return None


__all__ = [
    "BestLine",
    "CategoryReference",
    "Chat",
    "CollectionReference",
    "ImageOptimization",
    "Partner",
    "SeriesReference",
    "SportsMarketTypes",
    "SportsMetadata",
    "TagReference",
    "Team",
    "TeamOrdering",
    "TemplateReference",
    "coerce_string_id",
    "empty_string_to_none",
    "parse_decimal",
    "parse_dicts",
    "parse_epoch_seconds_optional",
    "parse_optional_date",
    "parse_optional_datetime",
    "parse_optional_decimal",
    "parse_sequence",
    "parse_string_sequence",
]
