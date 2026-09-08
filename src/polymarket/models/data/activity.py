from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import Field, computed_field, field_validator

from polymarket.errors import UnexpectedResponseError
from polymarket.models.base import BaseModel
from polymarket.models.data.common import (
    ActivityTypeFilter,
    TipSide,
    datetime_from_epoch_seconds,
    decimal_from_number,
    optional_datetime_from_epoch_seconds,
    optional_decimal_from_number,
    optional_outcome_index,
    optional_text,
)
from polymarket.models.data.portfolio import ComboPositionLeg
from polymarket.models.types import (
    ClobAssetId,
    ComboActivityId,
    ComboConditionId,
    ConditionId,
    OrderSide,
    PositionId,
    validate_combo_condition_id,
    validate_condition_id_response,
)
from polymarket.types import EvmAddress, TransactionHash


class Trade(BaseModel):
    """An executed trade; size is shares and price is USDC per share."""

    wallet: EvmAddress = Field(validation_alias="proxy_wallet")
    asset_id: ClobAssetId = Field(validation_alias="token_id")
    condition_id: ConditionId
    side: OrderSide
    size: Decimal
    price: Decimal
    timestamp: datetime
    transaction_hash: TransactionHash
    title: str | None = None
    slug: str | None = None
    icon: str | None = None
    event_slug: str | None = None
    outcome: str | None = None
    outcome_index: int | None = None
    name: str | None = None
    pseudonym: str | None = None
    bio: str | None = None
    profile_image: str | None = None
    profile_image_optimized: str | None = None

    _decimal = field_validator("size", "price", mode="before")(decimal_from_number)
    _timestamp = field_validator("timestamp", mode="before")(datetime_from_epoch_seconds)
    _condition = field_validator("condition_id", mode="before")(validate_condition_id_response)
    _text = field_validator(
        "title",
        "slug",
        "icon",
        "event_slug",
        "outcome",
        "name",
        "pseudonym",
        "bio",
        "profile_image",
        "profile_image_optimized",
        mode="before",
    )(optional_text)
    _index = field_validator("outcome_index", mode="before")(optional_outcome_index)

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""
        return self.asset_id


ActivityType = ActivityTypeFilter


class _KnownActivityBase(BaseModel):
    """Wallet activity with amounts in USDC and shares in outcome units.

    Prices are USDC per share.
    """

    wallet: EvmAddress = Field(validation_alias="proxy_wallet")
    timestamp: datetime
    transaction_hash: TransactionHash = Field(validation_alias="transaction_hash")
    name: str | None = None
    pseudonym: str | None = None
    bio: str | None = None
    profile_image: str | None = Field(default=None, validation_alias="profile_image")
    profile_image_optimized: str | None = Field(
        default=None, validation_alias="profile_image_optimized"
    )

    _profile_text = field_validator(
        "name", "pseudonym", "bio", "profile_image", "profile_image_optimized", mode="before"
    )(optional_text)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime | None:
        return optional_datetime_from_epoch_seconds(value)

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: _KnownActivityBase) -> str:
            title = type(self).__name__
            rows: list[tuple[str, str]] = [
                ("timestamp", self.timestamp.isoformat()),
                ("tx", truncate_mid(self.transaction_hash)),
                ("wallet", truncate_mid(self.wallet)),
            ]
            for attr in ("amount", "shares", "price", "side", "outcome", "title"):
                value = getattr(self, attr, None)
                if value is not None:
                    rows.append((attr, str(value)))
            return card(title, rows=rows)

        return render(self)


class TradeActivity(_KnownActivityBase):
    type: Literal["TRADE"]
    is_combo: Literal[False] = Field(default=False, validation_alias="is_combo")
    condition_id: ConditionId = Field(validation_alias="condition_id")
    asset_id: ClobAssetId = Field(validation_alias="token_id")
    side: OrderSide
    shares: Decimal = Field(validation_alias="size")
    amount: Decimal = Field(validation_alias="usdc_size")
    price: Decimal
    outcome: str | None = None
    outcome_index: int | None = None
    title: str | None = None
    slug: str | None = None
    icon: str | None = None
    event_slug: str | None = None

    _display_text = field_validator(
        "title", "slug", "icon", "event_slug", "outcome", mode="before"
    )(optional_text)
    _outcome_index = field_validator("outcome_index", mode="before")(optional_outcome_index)

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId:
        return validate_condition_id_response(value)

    @field_validator("shares", "amount", "price", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return optional_decimal_from_number(value)


class ComboTradeActivity(_KnownActivityBase):
    type: Literal["TRADE"]
    is_combo: Literal[True] = Field(validation_alias="is_combo")
    condition_id: ComboConditionId = Field(validation_alias="condition_id")
    position_id: PositionId = Field(validation_alias="token_id")
    side: OrderSide
    shares: Decimal = Field(validation_alias="size")
    amount: Decimal = Field(validation_alias="usdc_size")
    price: Decimal
    title: str | None = None
    icon: str | None = None

    _display_text = field_validator("title", "icon", mode="before")(optional_text)

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ComboConditionId:
        return validate_combo_condition_id(value)

    @field_validator("shares", "amount", "price", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return optional_decimal_from_number(value)


class _MarketEventActivity(_KnownActivityBase):
    condition_id: ConditionId = Field(validation_alias="condition_id")
    amount: Decimal = Field(validation_alias="usdc_size")
    title: str | None = None
    slug: str | None = None
    icon: str | None = None
    event_slug: str | None = None

    _display_text = field_validator("title", "slug", "icon", "event_slug", mode="before")(
        optional_text
    )

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ConditionId:
        return validate_condition_id_response(value)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return optional_decimal_from_number(value)


class SplitActivity(_MarketEventActivity):
    type: Literal["SPLIT"]


class MergeActivity(_MarketEventActivity):
    type: Literal["MERGE"]


class RedeemActivity(_MarketEventActivity):
    type: Literal["REDEEM"]


class ConversionActivity(_MarketEventActivity):
    type: Literal["CONVERSION"]


class _AccountCreditActivity(_KnownActivityBase):
    amount: Decimal = Field(validation_alias="usdc_size")

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return optional_decimal_from_number(value)


class RewardActivity(_AccountCreditActivity):
    type: Literal["REWARD"]


class DepositActivity(_AccountCreditActivity):
    type: Literal["DEPOSIT"]


class WithdrawalActivity(_AccountCreditActivity):
    type: Literal["WITHDRAWAL"]


class MakerRebateActivity(_AccountCreditActivity):
    type: Literal["MAKER_REBATE"]


class TakerRebateActivity(_AccountCreditActivity):
    type: Literal["TAKER_REBATE"]


class ReferralRewardActivity(_AccountCreditActivity):
    type: Literal["REFERRAL_REWARD"]


class MigrationActivity(_AccountCreditActivity):
    type: Literal["MIGRATION"]


class TipActivity(_AccountCreditActivity):
    type: Literal["TIP"]
    side: TipSide | None = None

    _side = field_validator("side", mode="before")(optional_text)


class YieldActivity(_AccountCreditActivity):
    type: Literal["YIELD"]


class UnknownActivity(BaseModel):
    type: str
    wallet: EvmAddress | None = Field(default=None, validation_alias="proxy_wallet")
    timestamp: datetime | None = None
    transaction_hash: TransactionHash | None = Field(
        default=None, validation_alias="transaction_hash"
    )
    name: str | None = None
    pseudonym: str | None = None
    bio: str | None = None
    profile_image: str | None = Field(default=None, validation_alias="profile_image")
    profile_image_optimized: str | None = Field(
        default=None, validation_alias="profile_image_optimized"
    )
    raw: dict[str, Any] = Field(default_factory=dict)

    _profile_text = field_validator(
        "name", "pseudonym", "bio", "profile_image", "profile_image_optimized", mode="before"
    )(optional_text)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime | None:
        return optional_datetime_from_epoch_seconds(value)

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: UnknownActivity) -> str:
            title = f"UnknownActivity  ·  {self.type or '(no type)'}"
            rows: list[tuple[str, str]] = []
            if self.timestamp is not None:
                rows.append(("timestamp", self.timestamp.isoformat()))
            if self.transaction_hash is not None:
                rows.append(("tx", truncate_mid(self.transaction_hash)))
            rows.append(("raw fields", str(len(self.raw))))
            return card(title, rows=rows)

        return render(self)


Activity = (
    TradeActivity
    | ComboTradeActivity
    | SplitActivity
    | MergeActivity
    | RedeemActivity
    | ConversionActivity
    | RewardActivity
    | DepositActivity
    | WithdrawalActivity
    | MakerRebateActivity
    | TakerRebateActivity
    | ReferralRewardActivity
    | YieldActivity
    | MigrationActivity
    | TipActivity
    | UnknownActivity
)

ComboActivityType = Literal["SPLIT", "MERGE", "CONVERT", "COMPRESS", "WRAP", "UNWRAP", "REDEEM"]


class _ComboActivityBase(BaseModel):
    id: ComboActivityId
    wallet: EvmAddress = Field(validation_alias="proxy_wallet")
    condition_id: ComboConditionId = Field(validation_alias="combo_condition_id")
    position_id: PositionId = Field(validation_alias="combo_position_id")
    amount: Decimal | None = Field(default=None, validation_alias="amount_usdc")
    timestamp: datetime
    transaction_hash: TransactionHash = Field(validation_alias="transaction_hash")
    block_number: int
    legs: tuple[ComboPositionLeg, ...]

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ComboConditionId:
        return validate_combo_condition_id(value)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return optional_decimal_from_number(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime | None:
        return optional_datetime_from_epoch_seconds(value)


class ComboSplitActivity(_ComboActivityBase):
    type: Literal["SPLIT"]


class ComboMergeActivity(_ComboActivityBase):
    type: Literal["MERGE"]


class ComboConvertActivity(_ComboActivityBase):
    type: Literal["CONVERT"]


class ComboCompressActivity(_ComboActivityBase):
    type: Literal["COMPRESS"]


class ComboWrapActivity(_ComboActivityBase):
    type: Literal["WRAP"]


class ComboUnwrapActivity(_ComboActivityBase):
    type: Literal["UNWRAP"]


class ComboRedeemActivity(_ComboActivityBase):
    type: Literal["REDEEM"]
    payout: Decimal | None = Field(default=None, validation_alias="payout_usdc")

    @field_validator("payout", mode="before")
    @classmethod
    def _parse_payout(cls, value: object) -> Decimal | None:
        return optional_decimal_from_number(value)


ComboActivity = (
    ComboSplitActivity
    | ComboMergeActivity
    | ComboConvertActivity
    | ComboCompressActivity
    | ComboWrapActivity
    | ComboUnwrapActivity
    | ComboRedeemActivity
)


_KNOWN_ACTIVITY_TYPES: dict[str, type[_KnownActivityBase]] = {
    "TRADE": TradeActivity,
    "SPLIT": SplitActivity,
    "MERGE": MergeActivity,
    "REDEEM": RedeemActivity,
    "CONVERSION": ConversionActivity,
    "REWARD": RewardActivity,
    "DEPOSIT": DepositActivity,
    "WITHDRAWAL": WithdrawalActivity,
    "MAKER_REBATE": MakerRebateActivity,
    "TAKER_REBATE": TakerRebateActivity,
    "REFERRAL_REWARD": ReferralRewardActivity,
    "YIELD": YieldActivity,
    "MIGRATION": MigrationActivity,
    "TIP": TipActivity,
}

_COMBO_ACTIVITY_TYPES: dict[ComboActivityType, type[_ComboActivityBase]] = {
    "SPLIT": ComboSplitActivity,
    "MERGE": ComboMergeActivity,
    "CONVERT": ComboConvertActivity,
    "COMPRESS": ComboCompressActivity,
    "WRAP": ComboWrapActivity,
    "UNWRAP": ComboUnwrapActivity,
    "REDEEM": ComboRedeemActivity,
}


def parse_activity(payload: object) -> Activity:
    if not isinstance(payload, dict):
        raise UnexpectedResponseError("Activity payload must be an object.")
    data = dict(cast(dict[str, Any], payload))
    activity_type = data.get("type")
    if activity_type == "TRADE" and data.get("is_combo") is True:
        return ComboTradeActivity.parse_response(data)
    if isinstance(activity_type, str) and activity_type in _KNOWN_ACTIVITY_TYPES:
        cls = _KNOWN_ACTIVITY_TYPES[activity_type]
        return cast(Activity, cls.parse_response(data))
    raw_type = activity_type if isinstance(activity_type, str) else ""
    return UnknownActivity.parse_response({**data, "type": raw_type, "raw": dict(data)})


def parse_activities(payload: object) -> tuple[Activity, ...]:
    if not isinstance(payload, list):
        raise UnexpectedResponseError("Activity list payload must be a list.")
    return tuple(parse_activity(item) for item in cast(list[object], payload))


def parse_combo_activity(payload: object) -> ComboActivity:
    if not isinstance(payload, dict):
        raise UnexpectedResponseError("Combo activity payload must be an object.")
    data = dict(cast(dict[str, Any], payload))
    raw_type = data.get("type")
    if not isinstance(raw_type, str) or raw_type not in _COMBO_ACTIVITY_TYPES:
        raise UnexpectedResponseError("Combo activity response did not match expected shape")
    cls = _COMBO_ACTIVITY_TYPES[raw_type]
    return cast(ComboActivity, cls.parse_response(data))


def parse_combo_activities(payload: object) -> tuple[ComboActivity, ...]:
    if not isinstance(payload, list):
        raise UnexpectedResponseError("Combo activity list payload must be a list.")
    return tuple(parse_combo_activity(item) for item in cast(list[object], payload))


__all__ = [
    "Activity",
    "ActivityType",
    "ComboActivity",
    "ComboActivityType",
    "ComboCompressActivity",
    "ComboConvertActivity",
    "ComboMergeActivity",
    "ComboRedeemActivity",
    "ComboSplitActivity",
    "ComboTradeActivity",
    "ComboUnwrapActivity",
    "ComboWrapActivity",
    "ConversionActivity",
    "DepositActivity",
    "MakerRebateActivity",
    "MergeActivity",
    "RedeemActivity",
    "ReferralRewardActivity",
    "RewardActivity",
    "SplitActivity",
    "TakerRebateActivity",
    "Trade",
    "TradeActivity",
    "UnknownActivity",
    "WithdrawalActivity",
    "YieldActivity",
    "MigrationActivity",
    "TipActivity",
    "parse_activities",
    "parse_activity",
    "parse_combo_activities",
    "parse_combo_activity",
]
