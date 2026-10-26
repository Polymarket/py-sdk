"""Search models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from pydantic import Field, field_validator, model_validator

from polymarket._internal.request import PageBasedPagePayload
from polymarket.errors import UnexpectedResponseError
from polymarket.models.base import BaseModel
from polymarket.models.gamma.common import (
    ImageOptimization,
    parse_optional_datetime,
    parse_optional_decimal,
    parse_sequence,
    parse_string_sequence,
)
from polymarket.models.gamma.event import Event
from polymarket.models.types import EventId, MarketId, TagId
from polymarket.types import EvmAddress


class Profile(BaseModel):
    id: str | None = None
    name: str | None = None
    user: int | None = None
    referral: str | None = None
    created_by: int | None = Field(default=None, validation_alias="createdBy")
    updated_by: int | None = Field(default=None, validation_alias="updatedBy")
    created_at: datetime | None = Field(default=None, validation_alias="createdAt")
    updated_at: datetime | None = Field(default=None, validation_alias="updatedAt")
    utm_source: str | None = Field(default=None, validation_alias="utmSource")
    utm_medium: str | None = Field(default=None, validation_alias="utmMedium")
    utm_campaign: str | None = Field(default=None, validation_alias="utmCampaign")
    utm_content: str | None = Field(default=None, validation_alias="utmContent")
    utm_term: str | None = Field(default=None, validation_alias="utmTerm")
    wallet_activated: bool | None = Field(default=None, validation_alias="walletActivated")
    pseudonym: str | None = None
    display_username_public: bool | None = Field(
        default=None,
        validation_alias="displayUsernamePublic",
    )
    profile_image: str | None = Field(default=None, validation_alias="profileImage")
    bio: str | None = None
    wallet: EvmAddress | None = None
    profile_image_optimized: ImageOptimization | None = Field(
        default=None,
        validation_alias="profileImageOptimized",
    )
    is_close_only: bool | None = Field(default=None, validation_alias="isCloseOnly")
    is_cert_req: bool | None = Field(default=None, validation_alias="isCertReq")
    cert_req_date: datetime | None = Field(default=None, validation_alias="certReqDate")
    discord_username: str | None = Field(default=None, validation_alias="discordUsername")
    x_username: str | None = Field(default=None, validation_alias="xUsername")
    verified_badge: bool | None = Field(default=None, validation_alias="verifiedBadge")
    dub_partner_id: str | None = Field(default=None, validation_alias="dubPartnerId")
    terms_accepted_at: datetime | None = Field(default=None, validation_alias="termsAcceptedAt")
    view_only_acknowledged_at: datetime | None = Field(
        default=None,
        validation_alias="viewOnlyAcknowledgedAt",
    )
    is_referral_restricted: bool | None = Field(
        default=None,
        validation_alias="isReferralRestricted",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_profile(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(cast(dict[str, Any], value))
        if "wallet" not in data:
            data["wallet"] = data.get("proxyWallet")
        return data

    @field_validator(
        "created_at",
        "updated_at",
        "cert_req_date",
        "terms_accepted_at",
        "view_only_acknowledged_at",
        mode="before",
    )
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class SearchTag(BaseModel):
    id: TagId
    label: str | None = None
    slug: str | None = None
    event_count: int | None = Field(default=None, validation_alias="event_count")


class SearchMarket(BaseModel):
    """A compact market search result; identifiers may be absent."""

    id: MarketId | None = None
    question: str | None = None
    slug: str | None = None
    group_item_title: str | None = Field(default=None, validation_alias="groupItemTitle")
    active: bool | None = None
    archived: bool | None = None
    closed: bool | None = None
    outcomes: tuple[str, ...] = ()
    outcome_prices: tuple[Decimal, ...] = Field(default=(), validation_alias="outcomePrices")
    best_bid: Decimal | None = Field(default=None, validation_alias="bestBid")
    best_ask: Decimal | None = Field(default=None, validation_alias="bestAsk")
    last_trade_price: Decimal | None = Field(default=None, validation_alias="lastTradePrice")
    spread: Decimal | None = None

    @field_validator("outcomes", mode="before")
    @classmethod
    def _parse_outcomes(cls, value: object) -> tuple[str, ...]:
        return parse_string_sequence(value)

    @field_validator("outcome_prices", mode="before")
    @classmethod
    def _parse_prices(cls, value: object) -> tuple[object, ...]:
        return parse_sequence(value)

    @field_validator("best_bid", "best_ask", "last_trade_price", "spread", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class SearchEvent(BaseModel):
    """A compact event search result containing market summaries."""

    id: EventId
    title: str | None = None
    slug: str | None = None
    image: str | None = None
    active: bool | None = None
    archived: bool | None = None
    closed: bool | None = None
    ended: bool | None = None
    neg_risk: bool | None = Field(default=None, validation_alias="negRisk")
    start_date: datetime | None = Field(default=None, validation_alias="startDate")
    end_date: datetime | None = Field(default=None, validation_alias="endDate")
    markets: tuple[SearchMarket, ...] = ()

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


def _parse_search_event(value: object) -> Event | SearchEvent:
    if isinstance(value, dict):
        data = cast(dict[str, Any], value)
        markets = data.get("markets")
        if isinstance(markets, list) and any(
            isinstance(market, dict) and "id" not in market
            for market in cast(list[object], markets)
        ):
            return SearchEvent.parse_response(data)
        return Event.parse_response(data)
    return Event.parse_response(value)


class SearchResults(BaseModel):
    events: tuple[Event | SearchEvent, ...] = ()
    tags: tuple[SearchTag, ...] = ()
    profiles: tuple[Profile, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _normalize_results(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = cast(dict[str, Any], value)

        def _array(key: str) -> tuple[Any, ...]:
            raw = data.get(key)
            if raw is None:
                return ()
            if not isinstance(raw, list):
                msg = f"'{key}' must be an array or null, got {type(raw).__name__}"
                raise ValueError(msg)
            return tuple(cast(list[Any], raw))

        return {
            "events": tuple(_parse_search_event(event) for event in _array("events")),
            "tags": _array("tags"),
            "profiles": _array("profiles"),
        }

    @classmethod
    def parse_page_response(cls, data: object) -> PageBasedPagePayload[SearchResults]:
        if not isinstance(data, dict):
            raise UnexpectedResponseError("SearchResults response did not match expected shape")
        payload = cast(dict[str, Any], data)

        raw_pagination = payload.get("pagination")
        if raw_pagination is None:
            has_more = False
            total_count: int | None = None
        elif isinstance(raw_pagination, dict):
            pag = cast(dict[str, Any], raw_pagination)
            raw_has_more = pag.get("hasMore")
            if raw_has_more is None:
                has_more = False
            elif isinstance(raw_has_more, bool):
                has_more = raw_has_more
            else:
                raise UnexpectedResponseError(
                    "'pagination.hasMore' must be a bool when present, "
                    f"got {type(raw_has_more).__name__}"
                )
            raw_total = pag.get("totalResults")
            if raw_total is None:
                total_count = None
            elif isinstance(raw_total, bool):
                raise UnexpectedResponseError(
                    "'pagination.totalResults' must be an integer when present, got bool"
                )
            elif isinstance(raw_total, int):
                total_count = raw_total
            else:
                raise UnexpectedResponseError(
                    "'pagination.totalResults' must be an integer when present, "
                    f"got {type(raw_total).__name__}"
                )
        else:
            raise UnexpectedResponseError(
                f"'pagination' must be an object when present, got {type(raw_pagination).__name__}"
            )

        if "hasMore" in payload:
            raw_has_more = payload["hasMore"]
            if not isinstance(raw_has_more, bool):
                raise UnexpectedResponseError("'hasMore' must be a bool when present")
            has_more = raw_has_more

        return PageBasedPagePayload(
            items=cls.parse_response(payload),
            has_more=has_more,
            total_count=total_count,
        )


__all__ = ["Profile", "SearchEvent", "SearchMarket", "SearchResults", "SearchTag"]
