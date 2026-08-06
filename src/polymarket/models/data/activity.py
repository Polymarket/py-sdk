from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import Field, field_validator

from polymarket.errors import UnexpectedResponseError
from polymarket.models.base import BaseModel
from polymarket.models.data.portfolio import ComboPositionLeg
from polymarket.models.gamma.common import (
    empty_string_to_none,
    parse_epoch_seconds_optional,
    parse_optional_decimal,
)
from polymarket.models.types import (
    ComboActivityId,
    ComboConditionId,
    CtfConditionId,
    PositionId,
    TokenId,
    validate_combo_condition_id,
    validate_ctf_condition_id,
    validate_optional_ctf_condition_id,
)
from polymarket.types import EvmAddress, TransactionHash


class Trade(BaseModel):
    wallet: EvmAddress | None = Field(default=None, validation_alias="proxyWallet")
    token_id: TokenId | None = Field(default=None, validation_alias="asset")
    condition_id: CtfConditionId | None = Field(default=None, validation_alias="conditionId")
    side: Literal["BUY", "SELL"] | None = None
    size: Decimal | None = None
    price: Decimal | None = None
    timestamp: datetime | None = None
    title: str | None = None
    slug: str | None = None
    icon: str | None = None
    event_slug: str | None = Field(default=None, validation_alias="eventSlug")
    outcome: str | None = None
    outcome_index: int | None = Field(default=None, validation_alias="outcomeIndex")
    name: str | None = None
    pseudonym: str | None = None
    bio: str | None = None
    profile_image: str | None = Field(default=None, validation_alias="profileImage")
    profile_image_optimized: str | None = Field(
        default=None, validation_alias="profileImageOptimized"
    )
    transaction_hash: TransactionHash | None = Field(
        default=None, validation_alias="transactionHash"
    )

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> CtfConditionId | None:
        return validate_optional_ctf_condition_id(value)

    @field_validator("size", "price", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime | None:
        return parse_epoch_seconds_optional(value)

    @field_validator("icon", mode="before")
    @classmethod
    def _normalize_icon(cls, value: object) -> object | None:
        return empty_string_to_none(value)


ActivityType = Literal[
    "TRADE",
    "SPLIT",
    "MERGE",
    "REDEEM",
    "REWARD",
    "CONVERSION",
    "DEPOSIT",
    "WITHDRAWAL",
    "MAKER_REBATE",
    "TAKER_REBATE",
    "REFERRAL_REWARD",
    "YIELD",
]


class _KnownActivityBase(BaseModel):
    wallet: EvmAddress = Field(validation_alias="proxyWallet")
    timestamp: datetime
    transaction_hash: TransactionHash = Field(validation_alias="transactionHash")
    name: str | None = None
    pseudonym: str | None = None
    bio: str | None = None
    profile_image: str | None = Field(default=None, validation_alias="profileImage")
    profile_image_optimized: str | None = Field(
        default=None, validation_alias="profileImageOptimized"
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime | None:
        return parse_epoch_seconds_optional(value)

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
    is_combo: Literal[False] = Field(default=False, validation_alias="isCombo")
    condition_id: CtfConditionId = Field(validation_alias="conditionId")
    token_id: TokenId = Field(validation_alias="asset")
    side: Literal["BUY", "SELL"]
    shares: Decimal = Field(validation_alias="size")
    amount: Decimal
    price: Decimal
    outcome: str
    outcome_index: int = Field(validation_alias="outcomeIndex")
    title: str
    slug: str
    icon: str | None = None
    event_slug: str = Field(validation_alias="eventSlug")

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> CtfConditionId:
        return validate_ctf_condition_id(value)

    @field_validator("shares", "amount", "price", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class ComboTradeActivity(_KnownActivityBase):
    type: Literal["TRADE"]
    is_combo: Literal[True] = Field(validation_alias="isCombo")
    condition_id: ComboConditionId = Field(validation_alias="conditionId")
    position_id: PositionId = Field(validation_alias="asset")
    side: Literal["BUY", "SELL"]
    shares: Decimal = Field(validation_alias="size")
    amount: Decimal
    price: Decimal
    title: str
    icon: str | None = None

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ComboConditionId:
        return validate_combo_condition_id(value)

    @field_validator("shares", "amount", "price", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class _MarketEventActivity(_KnownActivityBase):
    condition_id: CtfConditionId = Field(validation_alias="conditionId")
    amount: Decimal
    title: str
    slug: str
    icon: str | None = None
    event_slug: str = Field(validation_alias="eventSlug")

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> CtfConditionId:
        return validate_ctf_condition_id(value)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


class SplitActivity(_MarketEventActivity):
    type: Literal["SPLIT"]


class MergeActivity(_MarketEventActivity):
    type: Literal["MERGE"]


class RedeemActivity(_MarketEventActivity):
    type: Literal["REDEEM"]


class ConversionActivity(_MarketEventActivity):
    type: Literal["CONVERSION"]


class _AccountCreditActivity(_KnownActivityBase):
    amount: Decimal

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


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


class YieldActivity(_AccountCreditActivity):
    type: Literal["YIELD"]


class UnknownActivity(BaseModel):
    type: str
    wallet: EvmAddress | None = Field(default=None, validation_alias="proxyWallet")
    timestamp: datetime | None = None
    transaction_hash: TransactionHash | None = Field(
        default=None, validation_alias="transactionHash"
    )
    name: str | None = None
    pseudonym: str | None = None
    bio: str | None = None
    profile_image: str | None = Field(default=None, validation_alias="profileImage")
    profile_image_optimized: str | None = Field(
        default=None, validation_alias="profileImageOptimized"
    )
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime | None:
        return parse_epoch_seconds_optional(value)

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
    | UnknownActivity
)

ComboActivityType = Literal["SPLIT", "MERGE", "CONVERT", "COMPRESS", "WRAP", "UNWRAP", "REDEEM"]


class _ComboActivityBase(BaseModel):
    id: ComboActivityId
    wallet: EvmAddress = Field(validation_alias="user_address")
    condition_id: ComboConditionId = Field(validation_alias="combo_condition_id")
    module_id: int
    amount: Decimal | None = Field(default=None, validation_alias="amount_usdc")
    timestamp: datetime
    transaction_at: datetime = Field(validation_alias="tx_dttm")
    transaction_hash: TransactionHash = Field(validation_alias="tx_hash")
    log_index: int
    block_number: int
    legs: tuple[ComboPositionLeg, ...]

    @field_validator("condition_id", mode="before")
    @classmethod
    def _validate_condition_id(cls, value: object) -> ComboConditionId:
        return validate_combo_condition_id(value)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime | None:
        return parse_epoch_seconds_optional(value)


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
    position_id: PositionId = Field(validation_alias="combo_position_id")
    payout: Decimal | None = Field(default=None, validation_alias="payout_usdc")

    @field_validator("payout", mode="before")
    @classmethod
    def _parse_payout(cls, value: object) -> Decimal | None:
        return parse_optional_decimal(value)


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
    data = _normalize_activity_payload(cast(dict[str, Any], payload))
    activity_type = data.get("type")
    if activity_type == "TRADE" and data.get("isCombo") is True:
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


def _normalize_activity_payload(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)

    if normalized.get("outcomeIndex") == 999:
        normalized.pop("outcomeIndex", None)

    for sentinel_key in ("conditionId", "asset", "side", "outcome", "icon"):
        if normalized.get(sentinel_key) == "":
            normalized.pop(sentinel_key, None)

    if "amount" not in normalized:
        amount = normalized.get("usdcSize")
        if amount is None:
            amount = normalized.get("size")
        if amount is not None:
            normalized["amount"] = amount

    return normalized


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
    "parse_activities",
    "parse_activity",
    "parse_combo_activities",
    "parse_combo_activity",
]
