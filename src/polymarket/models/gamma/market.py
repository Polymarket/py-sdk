"""Market models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, TypeAlias, cast

from pydantic import AliasChoices, Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.gamma.common import (
    coerce_string_id,
    empty_string_to_none,
    parse_decimal,
    parse_dicts,
    parse_optional_datetime,
    parse_optional_decimal,
    parse_sequence,
    parse_string_sequence,
)
from polymarket.models.types import (
    ClobRewardId,
    ConditionId,
    EventId,
    MarketId,
    PositionId,
    QuestionId,
    ResolutionRequestId,
    TagId,
    TokenId,
    validate_condition_id_response,
    validate_optional_condition_id_response,
)
from polymarket.types import EvmAddress

ComboKnownStatus: TypeAlias = Literal["pending", "enabled", "disabled"]
# The Combo status set can grow between SDK releases, so unknown values flow
# through as plain strings instead of failing validation.
ComboStatus: TypeAlias = ComboKnownStatus | str


class ProtocolVersion(StrEnum):
    """Known market protocol versions."""

    V1 = "v1"
    V2 = "v2"


class UmaResolutionStatus(StrEnum):
    """Resolution lifecycle state for a market."""

    DISPUTED = "disputed"
    PROPOSED = "proposed"
    REQUESTED = "requested"
    RESOLVED = "resolved"
    SETTLED = "settled"


class MarketState(BaseModel):
    """Operational state and timing for a market."""

    active: bool | None = None
    closed: bool | None = None
    archived: bool | None = None
    combo_status: ComboStatus | None = Field(
        default=None,
        validation_alias="comboStatus",
    )
    accepting_orders: bool | None = Field(
        default=None,
        validation_alias="acceptingOrders",
    )
    enable_order_book: bool | None = Field(
        default=None,
        validation_alias="enableOrderBook",
    )
    neg_risk: bool | None = Field(
        default=None,
        validation_alias="negRisk",
    )
    start_date: datetime | None = Field(
        default=None,
        validation_alias="startDate",
    )
    end_date: datetime | None = Field(
        default=None,
        validation_alias="endDate",
    )
    closed_time: datetime | None = Field(
        default=None,
        validation_alias="closedTime",
    )

    @field_validator("start_date", "end_date", "closed_time", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class MarketOutcome(BaseModel):
    """One tradable outcome in a binary market."""

    label: str
    token_id: TokenId | None = Field(
        default=None,
        validation_alias="tokenId",
        description="CTF token ID for this outcome, when available.",
    )
    position_id: PositionId | None = Field(
        default=None,
        validation_alias="positionId",
        description="Polymarket V2 position ID for this outcome, when available.",
    )
    price: Decimal | None = None

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class MarketOutcomes(BaseModel):
    """Binary market outcomes."""

    yes: MarketOutcome
    no: MarketOutcome


class MarketMetrics(BaseModel):
    """Volume and liquidity metrics for a market."""

    volume: Decimal | None = None
    volume_num: Decimal | None = Field(
        default=None,
        validation_alias="volumeNum",
    )
    volume_24hr: Decimal | None = Field(
        default=None,
        validation_alias="volume24hr",
    )
    volume_1wk: Decimal | None = Field(
        default=None,
        validation_alias="volume1wk",
    )
    volume_1mo: Decimal | None = Field(
        default=None,
        validation_alias="volume1mo",
    )
    volume_1yr: Decimal | None = Field(
        default=None,
        validation_alias="volume1yr",
    )
    volume_amm: Decimal | None = Field(
        default=None,
        validation_alias="volumeAmm",
    )
    volume_clob: Decimal | None = Field(
        default=None,
        validation_alias="volumeClob",
    )
    liquidity: Decimal | None = None
    liquidity_num: Decimal | None = Field(
        default=None,
        validation_alias="liquidityNum",
    )
    liquidity_clob: Decimal | None = Field(
        default=None,
        validation_alias="liquidityClob",
    )

    @field_validator("*", mode="before")
    @classmethod
    def _parse_metric(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class MarketPrices(BaseModel):
    """Current price and price-change data for a market."""

    best_bid: Decimal | None = Field(
        default=None,
        validation_alias="bestBid",
    )
    best_ask: Decimal | None = Field(
        default=None,
        validation_alias="bestAsk",
    )
    last_trade_price: Decimal | None = Field(
        default=None,
        validation_alias="lastTradePrice",
    )
    spread: Decimal | None = None
    one_hour_price_change: Decimal | None = Field(
        default=None,
        validation_alias="oneHourPriceChange",
    )
    one_day_price_change: Decimal | None = Field(
        default=None,
        validation_alias="oneDayPriceChange",
    )
    one_week_price_change: Decimal | None = Field(
        default=None,
        validation_alias="oneWeekPriceChange",
    )
    one_month_price_change: Decimal | None = Field(
        default=None,
        validation_alias="oneMonthPriceChange",
    )
    one_year_price_change: Decimal | None = Field(
        default=None,
        validation_alias="oneYearPriceChange",
    )

    @field_validator("*", mode="before")
    @classmethod
    def _parse_price(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class FeeSchedule(BaseModel):
    """Fee schedule applied to market trading."""

    exponent: int | float
    rate: Decimal
    taker_only: bool = Field(validation_alias="takerOnly")
    rebate_rate: Decimal = Field(validation_alias="rebateRate")

    @field_validator("rate", "rebate_rate", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal:
        return parse_decimal(value)


class MarketTrading(BaseModel):
    """Trading configuration and constraints for a market."""

    minimum_order_size: Decimal | None = Field(
        default=None,
        validation_alias="minimumOrderSize",
    )
    minimum_tick_size: Decimal | None = Field(
        default=None,
        validation_alias="minimumTickSize",
    )
    seconds_delay: int | None = Field(
        default=None,
        validation_alias="secondsDelay",
    )
    fees_enabled: bool | None = Field(
        default=None,
        validation_alias="feesEnabled",
    )
    fee_type: str | None = Field(
        default=None,
        validation_alias="feeType",
    )
    fee_schedule: FeeSchedule | None = Field(
        default=None,
        validation_alias="feeSchedule",
    )

    @field_validator("minimum_order_size", "minimum_tick_size", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class MarketResolution(BaseModel):
    """Resolution metadata for a market."""

    question_id: QuestionId | None = Field(
        default=None,
        validation_alias="questionId",
    )
    neg_risk_request_id: ResolutionRequestId | None = Field(
        default=None,
        validation_alias="negRiskRequestId",
    )
    uma_resolution_status: UmaResolutionStatus | None = Field(
        default=None,
        validation_alias="umaResolutionStatus",
    )
    source: str | None = None
    resolved_by: EvmAddress | None = Field(
        default=None,
        validation_alias="resolvedBy",
    )

    @field_validator("question_id", "neg_risk_request_id", "resolved_by", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> object | None:
        return None if value == "" else value

    @field_validator("uma_resolution_status", mode="before")
    @classmethod
    def _parse_uma_status(cls, value: object) -> object | None:
        return None if value in (None, "") else value


class ClobReward(BaseModel):
    """Reward configuration attached to a market condition."""

    id: ClobRewardId
    condition_id: ConditionId = Field(validation_alias="conditionId")
    asset_address: str = Field(validation_alias="assetAddress")
    rewards_amount: Decimal = Field(validation_alias="rewardsAmount")
    rewards_daily_rate: Decimal = Field(validation_alias="rewardsDailyRate")
    start_date: date = Field(validation_alias="startDate")
    end_date: date | None = Field(
        default=None,
        validation_alias="endDate",
    )

    @field_validator("rewards_amount", "rewards_daily_rate", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal:
        return parse_decimal(value)

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId:
        return validate_condition_id_response(value)


class MarketRewards(BaseModel):
    """Reward settings for a market."""

    clob_rewards: tuple[ClobReward, ...] | None = Field(
        default=None,
        validation_alias="clobRewards",
    )
    rewards_min_size: Decimal | None = Field(
        default=None,
        validation_alias="rewardsMinSize",
    )
    rewards_max_spread: float | None = Field(
        default=None,
        validation_alias="rewardsMaxSpread",
    )
    holding_rewards_enabled: bool | None = Field(
        default=None,
        validation_alias="holdingRewardsEnabled",
    )

    @field_validator("rewards_min_size", mode="before")
    @classmethod
    def _parse_optional_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class MarketSportsMetadata(BaseModel):
    """Sports-specific metadata for a market."""

    sports_market_type: str | None = Field(
        default=None,
        validation_alias="sportsMarketType",
    )
    line: float | None = None
    game_id: str | None = Field(
        default=None,
        validation_alias="gameId",
    )
    game_start_time: datetime | None = Field(
        default=None,
        validation_alias="gameStartTime",
    )

    @field_validator("game_start_time", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> datetime | None:
        return parse_optional_datetime(value)


class MarketEvent(BaseModel):
    """Event reference attached to a market."""

    id: EventId
    slug: str | None = None
    title: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: object) -> object:
        return coerce_string_id(value)


class MarketTag(BaseModel):
    """Tag reference attached to a market."""

    id: TagId
    slug: str | None = None
    label: str | None = None


class Market(BaseModel):
    """A Polymarket market."""

    id: MarketId
    version: ProtocolVersion | None = None
    slug: str | None = None
    condition_id: ConditionId | None = Field(
        default=None,
        validation_alias=AliasChoices("conditionId", "condition"),
    )
    question: str | None = None
    group_item_title: str | None = Field(default=None, validation_alias="groupItemTitle")
    description: str | None = None
    category: str | None = None
    image: str | None = None
    icon: str | None = None
    state: MarketState
    outcomes: MarketOutcomes
    metrics: MarketMetrics
    prices: MarketPrices
    trading: MarketTrading
    resolution: MarketResolution
    rewards: MarketRewards
    sports: MarketSportsMetadata
    events: tuple[MarketEvent, ...]
    tags: tuple[MarketTag, ...]
    position_ids: tuple[PositionId, ...] = Field(
        default=(),
        validation_alias="positionIds",
        deprecated="Use the position_id on each outcome instead.",
        description="Deprecated market-level Polymarket V2 position IDs.",
    )

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: Market) -> str:
            if self.state.closed:
                status = "closed"
            elif self.state.active:
                status = "open"
            elif self.state.archived:
                status = "archived"
            else:
                status = "unknown"
            title = f"{self.question or '(no question)'}  ·  {status}"
            rows: list[tuple[str, str]] = []
            if self.slug:
                rows.append(("slug", self.slug))
            if self.condition_id:
                rows.append(("condition", truncate_mid(self.condition_id)))
            if self.state.end_date is not None:
                rows.append(("end", self.state.end_date.date().isoformat()))
            yes = self.outcomes.yes.price
            no = self.outcomes.no.price
            if yes is not None and no is not None:
                rows.append(("yes / no", f"{yes} / {no}"))
            return card(title, rows=rows)

        return render(self)

    @model_validator(mode="before")
    @classmethod
    def _normalize_market(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = cast(dict[str, Any], value)
        if "state" in data:
            return data

        outcomes = parse_string_sequence(data.get("outcomes"))
        outcome_prices = tuple(
            parse_decimal(item) for item in parse_sequence(data.get("outcomePrices"))
        )
        token_ids = parse_string_sequence(data.get("clobTokenIds"))
        position_ids = tuple(
            PositionId(item) for item in parse_string_sequence(data.get("positionIds"))
        )

        if len(outcomes) != 2:
            msg = f"Expected binary market outcomes, received {len(outcomes)}"
            raise ValueError(msg)

        return {
            "id": data.get("id"),
            "version": data.get("version"),
            "slug": data.get("slug"),
            "condition_id": empty_string_to_none(data.get("conditionId")),
            "question": data.get("question"),
            "group_item_title": data.get("groupItemTitle"),
            "description": data.get("description"),
            "category": data.get("category"),
            "image": data.get("image"),
            "icon": data.get("icon"),
            "state": {
                "active": data.get("active"),
                "closed": data.get("closed"),
                "archived": data.get("archived"),
                "combo_status": data.get("comboStatus"),
                "accepting_orders": data.get("acceptingOrders"),
                "enable_order_book": data.get("enableOrderBook"),
                "neg_risk": data.get("negRisk"),
                "start_date": data.get("startDate"),
                "end_date": data.get("endDate"),
                "closed_time": data.get("closedTime"),
            },
            "outcomes": {
                "yes": {
                    "label": outcomes[0],
                    "token_id": token_ids[0] if len(token_ids) > 0 else None,
                    "position_id": position_ids[0] if len(position_ids) > 0 else None,
                    "price": outcome_prices[0] if len(outcome_prices) > 0 else None,
                },
                "no": {
                    "label": outcomes[1],
                    "token_id": token_ids[1] if len(token_ids) > 1 else None,
                    "position_id": position_ids[1] if len(position_ids) > 1 else None,
                    "price": outcome_prices[1] if len(outcome_prices) > 1 else None,
                },
            },
            "metrics": {
                "volume": data.get("volume"),
                "volume_num": data.get("volumeNum"),
                "volume_24hr": data.get("volume24hr"),
                "volume_1wk": data.get("volume1wk"),
                "volume_1mo": data.get("volume1mo"),
                "volume_1yr": data.get("volume1yr"),
                "volume_amm": data.get("volumeAmm"),
                "volume_clob": data.get("volumeClob"),
                "liquidity": data.get("liquidity"),
                "liquidity_num": data.get("liquidityNum"),
                "liquidity_clob": data.get("liquidityClob"),
            },
            "prices": {
                "best_bid": data.get("bestBid"),
                "best_ask": data.get("bestAsk"),
                "last_trade_price": data.get("lastTradePrice"),
                "spread": data.get("spread"),
                "one_hour_price_change": data.get("oneHourPriceChange"),
                "one_day_price_change": data.get("oneDayPriceChange"),
                "one_week_price_change": data.get("oneWeekPriceChange"),
                "one_month_price_change": data.get("oneMonthPriceChange"),
                "one_year_price_change": data.get("oneYearPriceChange"),
            },
            "trading": {
                "minimum_order_size": data.get("orderMinSize"),
                "minimum_tick_size": data.get("orderPriceMinTickSize"),
                "seconds_delay": data.get("secondsDelay"),
                "fees_enabled": data.get("feesEnabled"),
                "fee_type": data.get("feeType"),
                "fee_schedule": data.get("feeSchedule"),
            },
            "resolution": {
                "question_id": empty_string_to_none(data.get("questionID")),
                "neg_risk_request_id": empty_string_to_none(data.get("negRiskRequestID")),
                "uma_resolution_status": empty_string_to_none(data.get("umaResolutionStatus")),
                "source": data.get("resolutionSource"),
                "resolved_by": empty_string_to_none(data.get("resolvedBy")),
            },
            "rewards": {
                "clob_rewards": data.get("clobRewards"),
                "rewards_min_size": data.get("rewardsMinSize"),
                "rewards_max_spread": data.get("rewardsMaxSpread"),
                "holding_rewards_enabled": data.get("holdingRewardsEnabled"),
            },
            "sports": {
                "sports_market_type": data.get("sportsMarketType"),
                "line": data.get("line"),
                "game_id": data.get("gameId"),
                "game_start_time": data.get("gameStartTime"),
            },
            "events": [
                {
                    "id": event.get("id"),
                    "slug": event.get("slug"),
                    "title": event.get("title"),
                }
                for event in parse_dicts(data.get("events"))
            ],
            "tags": [
                {
                    "id": tag.get("id"),
                    "slug": tag.get("slug"),
                    "label": tag.get("label"),
                }
                for tag in parse_dicts(data.get("tags"))
            ],
            "position_ids": position_ids,
        }

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId | None:
        return validate_optional_condition_id_response(value)


__all__ = [
    "ClobReward",
    "ComboKnownStatus",
    "ComboStatus",
    "FeeSchedule",
    "Market",
    "MarketEvent",
    "MarketMetrics",
    "MarketOutcome",
    "MarketOutcomes",
    "MarketPrices",
    "MarketResolution",
    "MarketRewards",
    "MarketSportsMetadata",
    "MarketState",
    "MarketTag",
    "MarketTrading",
    "ProtocolVersion",
    "UmaResolutionStatus",
]
