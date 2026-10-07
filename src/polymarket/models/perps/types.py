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
PerpsTpSlLifecycleStatus: TypeAlias = Literal["untriggered", "armed", "cancelled", "expired"]

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
    "PerpsKnownWithdrawalStatus",
    "PerpsMarginType",
    "PerpsNotificationId",
    "PerpsNotificationOrderType",
    "PerpsNotificationType",
    "PerpsOrderId",
    "PerpsOrderStatus",
    "PerpsPnlInterval",
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
