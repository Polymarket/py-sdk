"""Perps model-specific domain types."""

from typing import Literal, NewType, TypeAlias

PerpsInstrumentId = NewType("PerpsInstrumentId", int)
PerpsOrderId = NewType("PerpsOrderId", int)
PerpsClientOrderId = NewType("PerpsClientOrderId", str)
PerpsNotificationId = NewType("PerpsNotificationId", str)
PerpsTradeId = NewType("PerpsTradeId", int)
PerpsWithdrawalId = NewType("PerpsWithdrawalId", int)
PerpsEntityId = NewType("PerpsEntityId", int)

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
]
PerpsSide: TypeAlias = Literal["long", "short"]
PerpsTimeInForce: TypeAlias = Literal["gtc", "ioc", "fok"]
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
    "reduce_only_invalid",
    "reduce_only_expired",
    "order_expired",
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
    "PerpsBookDepth",
    "PerpsClientOrderId",
    "PerpsDepositStatus",
    "PerpsEntityId",
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
