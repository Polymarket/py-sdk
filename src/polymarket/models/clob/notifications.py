"""Account notification models."""

from __future__ import annotations

from enum import IntEnum
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    EpochOrIsoTimestamp,
    RequiredEpochOrIsoTimestamp,
    _DecimalFromNumberOrString,  # pyright: ignore[reportPrivateUsage]
    _DecimalFromString,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.clob.orders import OrderType
from polymarket.models.gamma.comment import CommentProfile
from polymarket.models.types import (
    ApiKey,
    ComboConditionId,
    CommentId,
    CtfConditionId,
    OrderId,
    OrderSide,
    PositionId,
    QuestionId,
    TokenId,
    validate_combo_condition_id,
)
from polymarket.types import EvmAddress, TransactionHash


class NotificationType(IntEnum):
    """Kind of account notification.

    Each kind carries a payload whose shape is tied to the kind.
    """

    ORDER_CANCELLATION = 1
    ORDER_FILL = 2
    MARKET_REGISTERED = 3
    MARKET_RESOLVED = 4
    REWARD_PAYOUT = 5
    CHILD_COMMENT_CREATED = 6
    YIELD_PAYOUT = 7
    ORDER_FILL_FAILED = 8
    AUTO_REDEEMED = 9
    COMBO_AUTO_REDEEMED = 10


def _empty_string_to_none(value: object) -> object:
    return None if value == "" else value


class OrderNotificationPayload(BaseModel):
    """Payload of an order lifecycle notification (cancellation, fill, and
    failed fill share this shape).

    ``transaction_hash`` and ``trade_id`` are only populated on fills. The
    market-display fields (``question``, ``market_slug``, ``icon``,
    ``image``, ``event_slug``, ``series_slug``) may be empty strings, and
    older notifications may omit them entirely, along with ``order_type``.
    """

    token_id: TokenId = Field(validation_alias="asset_id")
    condition_id: CtfConditionId = Field(validation_alias="market")
    order_id: OrderId
    side: OrderSide
    order_type: Annotated[OrderType | None, BeforeValidator(_empty_string_to_none)] = Field(
        default=None, validation_alias="type"
    )
    price: _DecimalFromString
    original_size: _DecimalFromString
    matched_size: _DecimalFromString
    remaining_size: _DecimalFromString
    outcome: str
    outcome_index: int
    transaction_hash: Annotated[TransactionHash | None, BeforeValidator(_empty_string_to_none)] = (
        None
    )
    trade_id: Annotated[str | None, BeforeValidator(_empty_string_to_none)] = None
    question: str | None = None
    market_slug: str | None = None
    icon: str | None = None
    image: str | None = None
    event_slug: str | None = Field(default=None, validation_alias="eventSlug")
    series_slug: str | None = Field(default=None, validation_alias="seriesSlug")


class MarketNotificationToken(BaseModel):
    """One outcome token inside a market lifecycle notification payload.

    On a market-resolved notification, ``winner`` marks the winning outcome.
    """

    token_id: TokenId
    outcome: str
    price: _DecimalFromNumberOrString | None = None
    winner: bool


class MarketNotificationRewardsRate(BaseModel):
    """Per-asset daily reward rate on a market lifecycle notification."""

    asset_address: str
    daily_rate: _DecimalFromNumberOrString = Field(validation_alias="rewards_daily_rate")


class MarketNotificationRewards(BaseModel):
    """Liquidity-rewards parameters carried on a market lifecycle notification."""

    min_size: _DecimalFromNumberOrString
    max_spread: float
    rates: tuple[MarketNotificationRewardsRate, ...] | None = None


class MarketNotificationPayload(BaseModel):
    """Payload of a market lifecycle notification (market registered and
    market resolved share this shape: the market the notification is about).

    Fields that default to ``None`` may be absent on older notifications.
    """

    condition_id: CtfConditionId
    question_id: QuestionId
    question: str
    description: str
    market_slug: str
    icon: str
    image: str
    fpmm: str
    active: bool
    closed: bool
    archived: bool | None = None
    accepting_orders: bool
    accepting_orders_timestamp: EpochOrIsoTimestamp = Field(
        default=None,
        validation_alias="accepting_order_timestamp",
    )
    enable_order_book: bool | None = None
    end_date: EpochOrIsoTimestamp = Field(default=None, validation_alias="end_date_iso")
    game_start_time: EpochOrIsoTimestamp = None
    seconds_delay: int
    minimum_order_size: _DecimalFromNumberOrString
    minimum_tick_size: _DecimalFromNumberOrString
    maker_base_fee: int | None = None
    taker_base_fee: int | None = None
    notifications_enabled: bool | None = None
    neg_risk: bool | None = None
    neg_risk_market_id: str | None = None
    neg_risk_request_id: str | None = None
    is_50_50_outcome: bool | None = None
    rewards: MarketNotificationRewards | None = None
    tokens: tuple[MarketNotificationToken, ...]
    tags: tuple[str, ...] | None = None
    event_slug: str | None = Field(default=None, validation_alias="eventSlug")


class RewardPayoutNotificationPayload(BaseModel):
    """Payload of a liquidity-reward payout notification."""

    proxy_wallet: EvmAddress = Field(validation_alias="proxyWallet")
    reward: _DecimalFromNumberOrString
    transaction_hash: TransactionHash = Field(validation_alias="txnHash")


class YieldPayoutNotificationPayload(BaseModel):
    """Payload of a yield payout notification."""

    proxy_wallet: EvmAddress = Field(validation_alias="proxyWallet")
    amount: _DecimalFromNumberOrString
    transaction_hash: TransactionHash = Field(validation_alias="txnHash")


class ChildCommentNotificationPayload(BaseModel):
    """Payload of a child-comment notification: the reply comment, its
    author's profile, and the event or series the thread belongs to.
    """

    id: CommentId
    body: str | None = None
    parent_entity_type: Literal["Event", "Series"] | None = Field(
        default=None,
        validation_alias="parentEntityType",
    )
    parent_entity_id: int | None = Field(default=None, validation_alias="parentEntityID")
    parent_comment_id: CommentId | None = Field(
        default=None,
        validation_alias="parentCommentID",
    )
    user_address: EvmAddress | None = Field(default=None, validation_alias="userAddress")
    created_at: EpochOrIsoTimestamp = Field(default=None, validation_alias="createdAt")
    profile: CommentProfile | None = None
    event_slug: str | None = Field(default=None, validation_alias="eventSlug")
    event_title: str | None = Field(default=None, validation_alias="eventTitle")
    series_slug: str | None = Field(default=None, validation_alias="seriesSlug")
    series_title: str | None = Field(default=None, validation_alias="seriesTitle")
    image: str | None = None


class AutoRedeemedNotificationPayload(BaseModel):
    """Payload of an auto-redeem notification: a winning position redeemed
    on-chain on the account's behalf.
    """

    proxy_wallet: EvmAddress = Field(validation_alias="proxyWallet")
    amount: _DecimalFromNumberOrString
    condition_id: CtfConditionId = Field(validation_alias="conditionId")
    question: str
    image: str
    market_slug: str = Field(validation_alias="slug")
    position: str | None = None
    market_url: str | None = Field(default=None, validation_alias="marketUrl")
    portfolio_url: str | None = Field(default=None, validation_alias="portfolioUrl")
    neg_risk: bool = Field(validation_alias="negRisk")
    transaction_hash: TransactionHash = Field(validation_alias="txnHash")


class ComboAutoRedeemedNotificationPayload(BaseModel):
    """Payload of a combo auto-redeem notification: a winning combo position
    redeemed on-chain on the account's behalf. ``legs`` is the combo arity.
    """

    proxy_wallet: EvmAddress = Field(validation_alias="proxyWallet")
    amount: _DecimalFromNumberOrString
    position_id: PositionId = Field(validation_alias="positionId")
    condition_id: ComboConditionId = Field(validation_alias="conditionId")
    outcome_index: int = Field(validation_alias="outcomeIndex")
    legs: int
    portfolio_url: str | None = Field(default=None, validation_alias="portfolioUrl")
    transaction_hash: TransactionHash = Field(validation_alias="txnHash")

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ComboConditionId:
        return validate_combo_condition_id(value)


def _parse_notification_id(value: object) -> object:
    if isinstance(value, bool):
        msg = f"notification id must be an integer, got bool {value!r}"
        raise ValueError(msg)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and (
        value.isdigit() or (value.startswith("-") and value[1:].isdigit())
    ):
        return int(value)
    msg = f"notification id must be an integer or numeric string, got {type(value).__name__}"
    raise ValueError(msg)


_NotificationId = Annotated[int, BeforeValidator(_parse_notification_id)]


class _NotificationBase(BaseModel):
    id: _NotificationId
    owner: ApiKey
    timestamp: RequiredEpochOrIsoTimestamp


class OrderCancellationNotification(_NotificationBase):
    """An order owned by the account was canceled."""

    type: Literal[NotificationType.ORDER_CANCELLATION]
    payload: OrderNotificationPayload


class OrderFillNotification(_NotificationBase):
    """An order owned by the account was filled."""

    type: Literal[NotificationType.ORDER_FILL]
    payload: OrderNotificationPayload


class MarketRegisteredNotification(_NotificationBase):
    """A market was registered for trading."""

    type: Literal[NotificationType.MARKET_REGISTERED]
    payload: MarketNotificationPayload


class MarketResolvedNotification(_NotificationBase):
    """A market the account holds a position in resolved."""

    type: Literal[NotificationType.MARKET_RESOLVED]
    payload: MarketNotificationPayload


class RewardPayoutNotification(_NotificationBase):
    """The account received a liquidity-reward payout."""

    type: Literal[NotificationType.REWARD_PAYOUT]
    payload: RewardPayoutNotificationPayload


class ChildCommentCreatedNotification(_NotificationBase):
    """Someone replied to one of the account's comments."""

    type: Literal[NotificationType.CHILD_COMMENT_CREATED]
    payload: ChildCommentNotificationPayload


class YieldPayoutNotification(_NotificationBase):
    """The account received a yield payout."""

    type: Literal[NotificationType.YIELD_PAYOUT]
    payload: YieldPayoutNotificationPayload


class OrderFillFailedNotification(_NotificationBase):
    """A fill on an order owned by the account failed to settle."""

    type: Literal[NotificationType.ORDER_FILL_FAILED]
    payload: OrderNotificationPayload


class AutoRedeemedNotification(_NotificationBase):
    """A winning position was redeemed on-chain on the account's behalf."""

    type: Literal[NotificationType.AUTO_REDEEMED]
    payload: AutoRedeemedNotificationPayload


class ComboAutoRedeemedNotification(_NotificationBase):
    """A winning combo position was redeemed on-chain on the account's behalf."""

    type: Literal[NotificationType.COMBO_AUTO_REDEEMED]
    payload: ComboAutoRedeemedNotificationPayload


Notification = Annotated[
    OrderCancellationNotification
    | OrderFillNotification
    | MarketRegisteredNotification
    | MarketResolvedNotification
    | RewardPayoutNotification
    | ChildCommentCreatedNotification
    | YieldPayoutNotification
    | OrderFillFailedNotification
    | AutoRedeemedNotification
    | ComboAutoRedeemedNotification,
    Field(discriminator="type"),
]
"""Account notification.

Discriminated on ``type``: narrowing on it also narrows ``payload`` to the
shape carried by that notification kind.
"""


__all__ = [
    "AutoRedeemedNotification",
    "AutoRedeemedNotificationPayload",
    "ChildCommentCreatedNotification",
    "ChildCommentNotificationPayload",
    "ComboAutoRedeemedNotification",
    "ComboAutoRedeemedNotificationPayload",
    "MarketNotificationPayload",
    "MarketNotificationRewards",
    "MarketNotificationRewardsRate",
    "MarketNotificationToken",
    "MarketRegisteredNotification",
    "MarketResolvedNotification",
    "Notification",
    "NotificationType",
    "OrderCancellationNotification",
    "OrderFillFailedNotification",
    "OrderFillNotification",
    "OrderNotificationPayload",
    "RewardPayoutNotification",
    "RewardPayoutNotificationPayload",
    "YieldPayoutNotification",
    "YieldPayoutNotificationPayload",
]
