"""Perps model-specific domain types."""

from typing import Literal, NewType, TypeAlias

PerpsInstrumentId = NewType("PerpsInstrumentId", int)
PerpsOrderId = NewType("PerpsOrderId", int)
PerpsClientOrderId = NewType("PerpsClientOrderId", str)
PerpsTradeId = NewType("PerpsTradeId", int)
PerpsWithdrawalId = NewType("PerpsWithdrawalId", int)
PerpsEntityId = NewType("PerpsEntityId", int)

PerpsInstrumentCategory: TypeAlias = Literal["equity", "commodity", "index", "crypto"]
PerpsSide: TypeAlias = Literal["long", "short"]
PerpsTimeInForce: TypeAlias = Literal["gtc", "ioc", "fok"]
PerpsTpSlKind: TypeAlias = Literal["tp", "sl"]
PerpsTpSlScope: TypeAlias = Literal["order", "position"]
PerpsKlineInterval: TypeAlias = Literal["1s", "1m", "5m", "15m", "1h", "4h", "1d", "1w"]
PerpsStreamCandleInterval: TypeAlias = Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
PerpsPnlInterval: TypeAlias = Literal["1h", "4h", "1d", "1w"]
PerpsBookDepth: TypeAlias = Literal[10, 100, 500, 1000]

# Status vocabularies evolve independently of released clients: values not
# yet enumerated in the Known* aliases still parse and flow through as plain
# strings, so the status type aliases stay ``str``.

KnownPerpsDepositStatus = Literal["pending", "confirmed", "removed"]
"""Deposit statuses known to this release; new values arrive as plain strings."""
PerpsDepositStatus: TypeAlias = str

KnownPerpsWithdrawalStatus = Literal["pending", "confirmed", "removed"]
"""Withdrawal statuses known to this release; new values arrive as plain strings."""
PerpsWithdrawalStatus: TypeAlias = str

KnownPerpsTpSlLifecycleStatus = Literal["untriggered", "armed", "cancelled", "expired"]
"""TP/SL statuses known to this release; new values arrive as plain strings."""
PerpsTpSlLifecycleStatus: TypeAlias = str

KnownPerpsOrderStatus = Literal[
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
"""Order statuses known to this release; new values arrive as plain strings."""
PerpsOrderStatus: TypeAlias = str

__all__ = [
    "KnownPerpsDepositStatus",
    "KnownPerpsOrderStatus",
    "KnownPerpsTpSlLifecycleStatus",
    "KnownPerpsWithdrawalStatus",
    "PerpsBookDepth",
    "PerpsClientOrderId",
    "PerpsDepositStatus",
    "PerpsEntityId",
    "PerpsInstrumentCategory",
    "PerpsInstrumentId",
    "PerpsKlineInterval",
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
]
