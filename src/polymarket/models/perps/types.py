"""Perps model-specific domain types."""

from enum import StrEnum
from typing import Literal, NewType, TypeAlias

PerpsInstrumentId = NewType("PerpsInstrumentId", int)
PerpsOrderId = NewType("PerpsOrderId", int)
PerpsClientOrderId = NewType("PerpsClientOrderId", str)
PerpsNotificationId = NewType("PerpsNotificationId", str)
PerpsFundingPaymentId = NewType("PerpsFundingPaymentId", int)
PerpsTradeId = NewType("PerpsTradeId", int)
PerpsWithdrawalId = NewType("PerpsWithdrawalId", int)
PerpsInternalTransferId = NewType("PerpsInternalTransferId", int)
PerpsEntityId = NewType("PerpsEntityId", int)


class PerpsKnownInternalTransferType(StrEnum):
    """Known classifications of settled internal transfers."""

    TRANSFER = "transfer"
    REFERRAL_PAYOUT = "referral_payout"


PerpsInternalTransferType: TypeAlias = PerpsKnownInternalTransferType | str


class PerpsInternalTransferDirection(StrEnum):
    """Movement relative to the authenticated account."""

    IN = "in"
    OUT = "out"


class PerpsKnownPricingMode(StrEnum):
    """Known pricing modes for a Perps instrument.

    ``EXTERNAL`` is normal pricing. Treat any other value, including values not
    enumerated here, as non-normal pricing.
    """

    EXTERNAL = "external"
    HOLD = "hold"
    INTERNAL = "internal"
    FROZEN = "frozen"
    BOUNDED = "bounded"
    RECOVERY_PENDING = "recovery_pending"


# The pricing mode set can grow between SDK releases, so unknown values flow
# through as plain strings instead of failing validation.
PerpsPricingMode: TypeAlias = PerpsKnownPricingMode | str


class PerpsKnownPricingReason(StrEnum):
    """Known reasons for the current pricing mode of a Perps instrument."""

    EXTERNAL_AVAILABLE = "external_available"
    ALL_SOURCES_UNAVAILABLE = "all_sources_unavailable"
    ACTIVATION_DELAY = "activation_delay"
    MISSING_ORACLE_CONFIGURATION = "missing_oracle_configuration"
    SOURCE_DISAGREEMENT = "source_disagreement"
    UNKNOWN_SOURCE_STATE = "unknown_source_state"
    EXPLICIT_HALT = "explicit_halt"
    DISABLED = "disabled"
    PROCESS_DISABLED = "process_disabled"
    MANUAL_FREEZE = "manual_freeze"
    INSUFFICIENT_BID_DEPTH = "insufficient_bid_depth"
    INSUFFICIENT_ASK_DEPTH = "insufficient_ask_depth"
    INVALID_BOOK = "invalid_book"
    IMPACT_SPREAD_TOO_WIDE = "impact_spread_too_wide"
    INVALID_PRECISION = "invalid_precision"
    ARITHMETIC_FAILURE = "arithmetic_failure"
    SESSION_BOUND = "session_bound"
    RECOVERY_CONFIRMATION = "recovery_confirmation"
    MATERIAL_RECOVERY_GAP = "material_recovery_gap"


# The pricing reason set can grow between SDK releases, so unknown values flow
# through as plain strings instead of failing validation.
PerpsPricingReason: TypeAlias = PerpsKnownPricingReason | str


class PerpsKnownPricingIndexSource(StrEnum):
    """Known sources of the retained index price of a Perps instrument."""

    UNKNOWN = "unknown"
    EXTERNAL = "external"
    INTERNAL = "internal"


# The index source set can grow between SDK releases, so unknown values flow
# through as plain strings instead of failing validation.
PerpsPricingIndexSource: TypeAlias = PerpsKnownPricingIndexSource | str


PerpsInstrumentCategory: TypeAlias = Literal["equity", "commodity", "index", "crypto"]
PerpsMarginType: TypeAlias = Literal["cross", "isolated"]
PerpsNotificationOrderType: TypeAlias = Literal["market", "limit", "take_profit", "stop_loss"]
PerpsNotificationType: TypeAlias = Literal[
    "position_opened",
    "position_increased",
    "position_reduced",
    "position_closed",
    "limit_order_canceled",
    "liquidation_warning",
    "position_liquidated",
    "position_deleveraged",
]
PerpsSide: TypeAlias = Literal["long", "short"]
PerpsTimeInForce: TypeAlias = Literal["gtc", "ioc", "fok", "gtd"]
PerpsTpSlKind: TypeAlias = Literal["tp", "sl"]
PerpsTpSlScope: TypeAlias = Literal["order", "position"]
PerpsDepositStatus: TypeAlias = Literal["pending", "confirmed", "removed"]
PerpsKnownWithdrawalStatus: TypeAlias = Literal["pending", "confirmed", "removed", "failed"]
# The withdrawal status set can grow between SDK releases, so unknown values
# flow through as plain strings instead of failing validation.
PerpsWithdrawalStatus: TypeAlias = PerpsKnownWithdrawalStatus | str
PerpsKlineInterval: TypeAlias = Literal["1s", "1m", "5m", "15m", "1h", "4h", "1d", "1w"]
PerpsStreamCandleInterval: TypeAlias = Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
PerpsPnlInterval: TypeAlias = Literal["1h", "4h", "1d", "1w"]
PerpsSortDirection: TypeAlias = Literal["desc", "asc"]
PerpsBookDepth: TypeAlias = Literal[10, 100, 500, 1000]
PerpsTpSlLifecycleStatus: TypeAlias = Literal[
    "untriggered", "armed", "activated", "cancelled", "expired"
]

PerpsOrderStatus: TypeAlias = Literal[
    "accepted",
    "open",
    "partial",
    "filled",
    "cancelled",
    "auto_cancelled",
    "post_only_rejected",
    "fok_unfilled",
    "ioc_no_fill",
    "ioc_expired",
    "stp_cancelled",
    "zero_quantity",
    "duplicate_order",
    "order_not_found",
    "order_already_terminal",
    "reduce_only_invalid",
    "reduce_only_expired",
    "order_expired",
    "sweep_cap_exceeded",
    "resting_order_limit_exceeded",
    "below_min_notional",
    "instrument_disabled",
    "instrument_close_only",
    "instrument_settled",
    "insufficient_margin_at_fill",
    "mark_price_unavailable",
    "untriggered",
    "armed",
    "triggered",
    "parent_cancelled",
    "position_closed",
    "position_flipped",
    "reduce_only_invalid_at_trigger",
    "expired",
]

__all__ = [
    "PerpsInternalTransferId",
    "PerpsInternalTransferType",
    "PerpsKnownInternalTransferType",
    "PerpsInternalTransferDirection",
    "PerpsBookDepth",
    "PerpsClientOrderId",
    "PerpsDepositStatus",
    "PerpsEntityId",
    "PerpsFundingPaymentId",
    "PerpsInstrumentCategory",
    "PerpsInstrumentId",
    "PerpsKlineInterval",
    "PerpsKnownPricingIndexSource",
    "PerpsKnownPricingMode",
    "PerpsKnownPricingReason",
    "PerpsKnownWithdrawalStatus",
    "PerpsMarginType",
    "PerpsNotificationId",
    "PerpsNotificationOrderType",
    "PerpsNotificationType",
    "PerpsOrderId",
    "PerpsOrderStatus",
    "PerpsPnlInterval",
    "PerpsPricingIndexSource",
    "PerpsPricingMode",
    "PerpsPricingReason",
    "PerpsSide",
    "PerpsStreamCandleInterval",
    "PerpsTimeInForce",
    "PerpsTpSlKind",
    "PerpsTpSlLifecycleStatus",
    "PerpsTpSlScope",
    "PerpsTradeId",
    "PerpsWithdrawalId",
    "PerpsWithdrawalStatus",
]
