from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, computed_field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.data.common import (
    ComboPositionStatus,
    PositionStatus,
    UserPnlFidelity,
    UserPnlInterval,
    date_from_calendar_string,
    datetime_from_epoch_seconds,
    decimal_from_number,
    optional_datetime_from_epoch_or_iso,
    optional_datetime_from_epoch_seconds,
    optional_decimal_from_number,
    optional_event_id,
    optional_outcome_index,
    optional_text,
)
from polymarket.models.types import (
    ClobAssetId,
    ComboConditionId,
    ConditionId,
    EventId,
    MarketId,
    PositionId,
    validate_combo_condition_id,
    validate_condition_id_response,
)
from polymarket.types import EvmAddress


class Position(BaseModel):
    """A wallet position. Sizes are shares; prices, costs, values and PnL are USDC.

    ``entry_cost_usdc`` is fee-exclusive. ``entry_fees_usdc`` is disclosure only.
    Percentage fields are percentages."""

    wallet: EvmAddress = Field(validation_alias="proxy_wallet")
    asset_id: ClobAssetId = Field(validation_alias="token_id")
    condition_id: ConditionId
    current_size: Decimal
    avg_price: Decimal
    entry_cost_usdc: Decimal
    entry_fees_usdc: Decimal
    total_cost_usdc: Decimal
    current_price: Decimal
    current_value: Decimal
    total_size: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    percent_pnl: Decimal
    percent_realized_pnl: Decimal
    status: PositionStatus
    redeemable: bool
    mergeable: bool
    negative_risk: bool
    archived: bool
    verified: bool
    title: str | None = None
    slug: str | None = None
    icon: str | None = None
    event_slug: str | None = None
    outcome: str | None = None
    opposite_outcome: str | None = None
    name: str | None = None
    profile_image: str | None = None
    event_id: EventId | None = None
    outcome_index: int | None = None
    opposite_asset_id: ClobAssetId | None = Field(
        default=None, validation_alias="opposite_token_id"
    )
    end_date: date | None = None
    last_event_at: datetime | None = None

    _validate_condition_id_response = field_validator("condition_id", mode="before")(
        validate_condition_id_response
    )

    _decimal_from_number = field_validator(
        "current_size",
        "avg_price",
        "entry_cost_usdc",
        "entry_fees_usdc",
        "total_cost_usdc",
        "current_price",
        "current_value",
        "total_size",
        "realized_pnl",
        "unrealized_pnl",
        "total_pnl",
        "percent_pnl",
        "percent_realized_pnl",
        mode="before",
    )(decimal_from_number)

    _optional_text = field_validator(
        "title",
        "slug",
        "icon",
        "event_slug",
        "outcome",
        "opposite_outcome",
        "name",
        "profile_image",
        "opposite_asset_id",
        mode="before",
    )(optional_text)

    _optional_event_id = field_validator("event_id", mode="before")(optional_event_id)

    _optional_outcome_index = field_validator("outcome_index", mode="before")(
        optional_outcome_index
    )

    _date_from_calendar_string = field_validator("end_date", mode="before")(
        date_from_calendar_string
    )

    _optional_datetime_from_epoch_seconds = field_validator("last_event_at", mode="before")(
        optional_datetime_from_epoch_seconds
    )

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""
        return self.asset_id

    @computed_field
    @property
    def opposite_token_id(self) -> ClobAssetId | None:
        """Deprecated alias for :attr:`opposite_asset_id`."""
        return self.opposite_asset_id

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: Position) -> str:
            label = self.title or truncate_mid(self.condition_id)
            title = f"Position  ·  {label}"
            rows: list[tuple[str, str]] = []
            if self.outcome:
                rows.append(("side", self.outcome))
            rows.append(("size", str(self.current_size)))
            rows.append(("avg_price", str(self.avg_price)))
            rows.append(("current", str(self.current_price)))
            rows.append(("pnl", str(self.total_pnl)))
            return card(title, rows=rows)

        return render(self)


class ComboPositionMarketEvent(BaseModel):
    event_id: EventId | None = None
    event_slug: str | None = None
    event_title: str | None = None
    event_image: str | None = None

    _optional_event_id = field_validator("event_id", mode="before")(optional_event_id)

    _optional_text = field_validator("event_slug", "event_title", "event_image", mode="before")(
        optional_text
    )


class ComboPositionMarket(BaseModel):
    market_id: MarketId | None = None
    slug: str | None = None
    title: str | None = None
    question: str | None = None
    group_item_title: str | None = None
    sports_market_type: str | None = None
    line: Decimal | None = None
    outcomes: tuple[str, ...] | None = None
    outcome: str | None = None
    image_url: str | None = None
    icon_url: str | None = None
    category: str | None = None
    subcategory: str | None = None
    tags: tuple[str, ...] | None = None
    end_date: datetime | None = None
    event: ComboPositionMarketEvent | None = None

    _optional_text = field_validator(
        "slug",
        "title",
        "question",
        "group_item_title",
        "sports_market_type",
        "outcome",
        "image_url",
        "icon_url",
        "category",
        "subcategory",
        mode="before",
    )(optional_text)

    _optional_decimal_from_number = field_validator("line", mode="before")(
        optional_decimal_from_number
    )

    _optional_datetime_from_epoch_or_iso = field_validator("end_date", mode="before")(
        optional_datetime_from_epoch_or_iso
    )


class ComboPositionLeg(BaseModel):
    """A combo leg; ``leg_current_price`` is USDC per share."""

    leg_index: int
    leg_position_id: PositionId
    leg_condition_id: ConditionId
    leg_outcome_index: int
    leg_outcome_label: str | None = None
    leg_status: ComboPositionStatus
    leg_resolved_at: datetime | None = None
    leg_current_price: Decimal | None = None
    market: ComboPositionMarket | None = None

    _validate_condition_id_response = field_validator("leg_condition_id", mode="before")(
        validate_condition_id_response
    )

    _optional_text = field_validator("leg_outcome_label", mode="before")(optional_text)

    _optional_decimal_from_number = field_validator("leg_current_price", mode="before")(
        optional_decimal_from_number
    )


class ComboPosition(BaseModel):
    """A combo position. ``current_size`` is shares; prices, costs and payouts are USDC.

    The fee-exclusive basis is ``gross_entry_cost_usdc - entry_fees_usdc``;
    ``entry_cost_usdc`` is a rounded weighted-average cost."""

    condition_id: ComboConditionId = Field(validation_alias="combo_condition_id")
    position_id: PositionId = Field(validation_alias="combo_position_id")
    wallet: EvmAddress = Field(validation_alias="proxy_wallet")
    outcome_index: int
    outcome_label: str
    current_size: Decimal
    entry_avg_price_usdc: Decimal
    entry_cost_usdc: Decimal
    gross_entry_cost_usdc: Decimal
    entry_fees_usdc: Decimal
    realized_payout_usdc: Decimal
    status: ComboPositionStatus
    redeemable: bool
    first_entry_at: datetime
    resolved_at: datetime | None = None
    updated_at: datetime
    legs_total: int
    legs_resolved: int
    legs_pending: int
    legs: tuple[ComboPositionLeg, ...]

    _validate_combo_condition_id = field_validator("condition_id", mode="before")(
        validate_combo_condition_id
    )

    _decimal_from_number = field_validator(
        "current_size",
        "entry_avg_price_usdc",
        "entry_cost_usdc",
        "gross_entry_cost_usdc",
        "entry_fees_usdc",
        "realized_payout_usdc",
        mode="before",
    )(decimal_from_number)


class PortfolioValue(BaseModel):
    """Current portfolio value in USDC."""

    wallet: EvmAddress = Field(validation_alias="proxy_wallet")
    value: Decimal

    _decimal_from_number = field_validator("value", mode="before")(decimal_from_number)


class UserPnlPoint(BaseModel):
    """Cumulative wallet metrics. ``volume`` is shares; all monetary amounts are USDC.

    Missing cumulative amounts remain ``None``."""

    timestamp: datetime
    source_block: int
    trade_count: int
    realized_market_pnl: Decimal
    realized_lp_pnl: Decimal
    realized_combo_pnl: Decimal
    realized_pnl: Decimal
    volume: Decimal
    volume_usdc: Decimal
    unrealized_pnl: Decimal | None = None
    fees_refunded: Decimal | None = None
    maker_rebate: Decimal | None = None
    taker_rebate: Decimal | None = None
    reward_income: Decimal | None = None
    yield_income: Decimal | None = None
    referral_income: Decimal | None = None
    sponsored_income: Decimal | None = None
    deposits: Decimal | None = None
    withdrawals: Decimal | None = None
    cashflow_net: Decimal | None = None
    wallet_income: Decimal | None = None
    position_pnl: Decimal | None = None
    settled_pnl: Decimal | None = None
    economic_pnl: Decimal | None = None
    trade_pnl: Decimal | None = None
    fees: Decimal | None = None
    fees_paid: Decimal | None = None

    _datetime_from_epoch_seconds = field_validator("timestamp", mode="before")(
        datetime_from_epoch_seconds
    )

    _decimal_from_number = field_validator(
        "realized_market_pnl",
        "realized_lp_pnl",
        "realized_combo_pnl",
        "realized_pnl",
        "volume",
        "volume_usdc",
        mode="before",
    )(decimal_from_number)

    _optional_decimal_from_number = field_validator(
        "unrealized_pnl",
        "fees_refunded",
        "maker_rebate",
        "taker_rebate",
        "reward_income",
        "yield_income",
        "referral_income",
        "sponsored_income",
        "deposits",
        "withdrawals",
        "cashflow_net",
        "wallet_income",
        "position_pnl",
        "settled_pnl",
        "economic_pnl",
        "trade_pnl",
        "fees",
        "fees_paid",
        mode="before",
    )(optional_decimal_from_number)


class UserStats(BaseModel):
    """Wallet statistics; ``biggest_win`` is USDC."""

    wallet: EvmAddress = Field(validation_alias="proxy_wallet")
    traded_market_count: int = Field(validation_alias="trades")
    biggest_win: Decimal
    views: int
    join_date: datetime | None = None
    all_time_pnl: UserPnlPoint | None = None

    _decimal_from_number = field_validator("biggest_win", mode="before")(decimal_from_number)

    _optional_datetime_from_epoch_seconds = field_validator("join_date", mode="before")(
        optional_datetime_from_epoch_seconds
    )


class UserPnlSeries(BaseModel):
    """A cumulative PnL time series for a wallet."""

    wallet: EvmAddress = Field(validation_alias="proxy_wallet")
    interval: UserPnlInterval
    fidelity: UserPnlFidelity
    source_fidelity: UserPnlFidelity
    points: tuple[UserPnlPoint, ...]


class UserVolume(BaseModel):
    """Trading volume in shares and USDC, with a trade count."""

    volume: Decimal
    volume_usdc: Decimal
    trade_count: int

    _decimal_from_number = field_validator("volume", "volume_usdc", mode="before")(
        decimal_from_number
    )


__all__ = [
    "Position",
    "ComboPositionMarketEvent",
    "ComboPositionMarket",
    "ComboPositionLeg",
    "ComboPosition",
    "PortfolioValue",
    "UserPnlPoint",
    "UserStats",
    "UserPnlSeries",
    "UserVolume",
]
