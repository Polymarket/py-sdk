"""Perps order and fill models."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import AliasChoices, Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    _coerce_decimalish,  # pyright: ignore[reportPrivateUsage]
    _parse_auto_cancel_deadline,  # pyright: ignore[reportPrivateUsage]
    _parse_tx_hash,  # pyright: ignore[reportPrivateUsage]
    _require_epoch_ms,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.perps.types import (
    PerpsInstrumentId,
    PerpsOrderId,
    PerpsOrderStatus,
    PerpsSide,
    PerpsTimeInForce,
    PerpsTpSlKind,
    PerpsTpSlScope,
    PerpsTradeId,
)
from polymarket.models.types import OrderSide

_DEFAULT_ACK_ERROR = "Perps command was rejected."


def _side_from_buy(value: object) -> OrderSide:
    if value is True:
        return "BUY"
    if value is False:
        return "SELL"
    msg = f"expected buy flag to be a bool, got {type(value).__name__}"
    raise ValueError(msg)


class PerpsTpSlOrderFields(BaseModel):
    """Take-profit/stop-loss metadata attached to a trigger order."""

    kind: PerpsTpSlKind
    scope: PerpsTpSlScope
    trigger_price: Decimal = Field(validation_alias="trp")
    parent_order_id: PerpsOrderId | None = Field(default=None, validation_alias="parent_oid")
    armed_quantity: Decimal | None = Field(default=None, validation_alias="armed_qty")
    slippage_bps: int | None = Field(default=None, validation_alias="slip_bps")

    @field_validator("trigger_price", "armed_quantity", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)


class PerpsOrder(BaseModel):
    """One Perps order."""

    id: PerpsOrderId = Field(validation_alias=AliasChoices("order_id", "oid"))
    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    side: OrderSide = Field(validation_alias="buy")
    price: Decimal = Field(validation_alias=AliasChoices("price", "p"))
    quantity: Decimal = Field(validation_alias=AliasChoices("quantity", "qty"))
    time_in_force: PerpsTimeInForce = Field(validation_alias="tif")
    post_only: bool = Field(validation_alias=AliasChoices("post_only", "po"))
    reduce_only: bool = Field(validation_alias="ro")
    status: PerpsOrderStatus
    resting_quantity: Decimal = Field(validation_alias=AliasChoices("resting_quantity", "rest"))
    filled_quantity: Decimal = Field(validation_alias=AliasChoices("filled_quantity", "fill"))
    created_at: datetime = Field(validation_alias=AliasChoices("created_timestamp", "cts"))
    updated_at: datetime = Field(validation_alias=AliasChoices("updated_timestamp", "uts"))
    client_order_id: str | None = Field(
        default=None, validation_alias=AliasChoices("client_order_id", "coid")
    )
    tp_sl: PerpsTpSlOrderFields | None = Field(default=None, validation_alias="tpsl")

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        wire = cast("dict[str, Any]", data)
        if "buy" not in wire:
            return wire
        normalized = dict(wire)
        normalized["buy"] = _side_from_buy(normalized["buy"])
        return normalized

    @field_validator("price", "quantity", "resting_quantity", "filled_quantity", mode="before")
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_timestamps(cls, value: object) -> object:
        return _require_epoch_ms(value)


class PerpsFill(BaseModel):
    """One fill on a Perps order for the account."""

    trade_id: PerpsTradeId = Field(validation_alias=AliasChoices("trade_id", "tid"))
    order_id: PerpsOrderId = Field(validation_alias=AliasChoices("order_id", "oid"))
    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    side: PerpsSide
    price: Decimal = Field(validation_alias=AliasChoices("price", "p"))
    quantity: Decimal = Field(validation_alias=AliasChoices("quantity", "qty"))
    taker: bool
    fee: Decimal
    fee_asset: str = Field(validation_alias=AliasChoices("fee_asset", "fea"))
    previous_size: Decimal = Field(validation_alias=AliasChoices("previous_size", "psz"))
    previous_entry_price: Decimal = Field(
        validation_alias=AliasChoices("previous_entry_price", "pep")
    )
    pnl: Decimal
    liquidation: bool = Field(validation_alias=AliasChoices("liquidation", "liq"))
    timestamp: datetime = Field(validation_alias=AliasChoices("timestamp", "ts"))
    hash: str | None = None
    client_order_id: str | None = Field(default=None, validation_alias="coid")

    @field_validator(
        "price",
        "quantity",
        "fee",
        "previous_size",
        "previous_entry_price",
        "pnl",
        mode="before",
    )
    @classmethod
    def _parse_decimals(cls, value: object) -> object:
        return _coerce_decimalish(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _require_epoch_ms(value)

    @field_validator("hash", mode="before")
    @classmethod
    def _normalize_hash(cls, value: object) -> object:
        return _parse_tx_hash(value)


def _default_ack_error(data: object) -> object:
    if not isinstance(data, dict):
        return data
    wire = cast("dict[str, Any]", data)
    if wire.get("status") == "err" and not wire.get("error"):
        normalized = dict(wire)
        normalized["error"] = _DEFAULT_ACK_ERROR
        return normalized
    return wire


class PerpsPostOrderAck(BaseModel):
    """Acknowledgement for one posted Perps order."""

    status: Literal["ok", "err"]
    order_id: PerpsOrderId | None = Field(default=None, validation_alias="oid")
    client_order_id: str | None = Field(default=None, validation_alias="coid")
    error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _default_ack_error(data)

    @model_validator(mode="after")
    def _check(self) -> "PerpsPostOrderAck":
        if self.status == "ok" and self.order_id is None:
            msg = "expected Perps post order acknowledgement order id"
            raise ValueError(msg)
        return self


class PerpsCancelOrderResult(BaseModel):
    """Result of one Perps order cancellation."""

    status: Literal["ok", "err"]
    order_id: PerpsOrderId | None = Field(default=None, validation_alias="oid")
    client_order_id: str | None = Field(default=None, validation_alias="coid")
    error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: object) -> object:
        return _default_ack_error(data)


class PerpsCancelAllOrdersResponse(BaseModel):
    """Accepted response for a Perps cancel-all request."""

    status: Literal["ok"]


class PerpsAutoCancelResponse(BaseModel):
    """Accepted response for a Perps auto-cancel update.

    ``deadline`` echoes the armed cancellation time, or ``None`` when the
    schedule was disarmed.
    """

    status: Literal["ok"]
    deadline: datetime | None

    @field_validator("deadline", mode="before")
    @classmethod
    def _parse_deadline(cls, value: object) -> object:
        return _parse_auto_cancel_deadline(value)


class PerpsUpdateLeverageResult(BaseModel):
    """Result of a Perps leverage update."""

    status: Literal["ok"]
    instrument_id: PerpsInstrumentId
    leverage: int
    cross_margin: bool = Field(validation_alias="cross")


__all__ = [
    "PerpsAutoCancelResponse",
    "PerpsCancelAllOrdersResponse",
    "PerpsCancelOrderResult",
    "PerpsFill",
    "PerpsOrder",
    "PerpsPostOrderAck",
    "PerpsTpSlOrderFields",
    "PerpsUpdateLeverageResult",
]
