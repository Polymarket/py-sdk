"""Perps order and fill models."""

from typing import Any, Literal, cast

from pydantic import AliasChoices, Field, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.perps._validators import (
    OptionalTxHash,
    PerpsTimestamp,
    _Decimal,
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
    trigger_price: _Decimal = Field(validation_alias="trp")
    parent_order_id: PerpsOrderId | None = Field(default=None, validation_alias="parent_oid")
    armed_quantity: _Decimal | None = Field(default=None, validation_alias="armed_qty")
    slippage_bps: int | None = Field(default=None, validation_alias="slip_bps")


class PerpsOrder(BaseModel):
    """One Perps order."""

    id: PerpsOrderId = Field(validation_alias=AliasChoices("order_id", "oid"))
    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    side: OrderSide = Field(validation_alias="buy")
    price: _Decimal = Field(validation_alias=AliasChoices("price", "p"))
    quantity: _Decimal = Field(validation_alias=AliasChoices("quantity", "qty"))
    time_in_force: PerpsTimeInForce = Field(validation_alias="tif")
    post_only: bool = Field(validation_alias=AliasChoices("post_only", "po"))
    reduce_only: bool = Field(validation_alias="ro")
    status: PerpsOrderStatus
    resting_quantity: _Decimal = Field(validation_alias=AliasChoices("resting_quantity", "rest"))
    filled_quantity: _Decimal = Field(validation_alias=AliasChoices("filled_quantity", "fill"))
    created_at: PerpsTimestamp = Field(validation_alias=AliasChoices("created_timestamp", "cts"))
    updated_at: PerpsTimestamp = Field(validation_alias=AliasChoices("updated_timestamp", "uts"))
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


class PerpsFill(BaseModel):
    """One fill on a Perps order for the account."""

    trade_id: PerpsTradeId = Field(validation_alias=AliasChoices("trade_id", "tid"))
    order_id: PerpsOrderId = Field(validation_alias=AliasChoices("order_id", "oid"))
    instrument_id: PerpsInstrumentId = Field(validation_alias=AliasChoices("instrument_id", "iid"))
    side: PerpsSide
    price: _Decimal = Field(validation_alias=AliasChoices("price", "p"))
    quantity: _Decimal = Field(validation_alias=AliasChoices("quantity", "qty"))
    taker: bool
    fee: _Decimal
    fee_asset: str = Field(validation_alias=AliasChoices("fee_asset", "fea"))
    previous_size: _Decimal = Field(validation_alias=AliasChoices("previous_size", "psz"))
    previous_entry_price: _Decimal = Field(
        validation_alias=AliasChoices("previous_entry_price", "pep")
    )
    pnl: _Decimal
    liquidation: bool = Field(validation_alias=AliasChoices("liquidation", "liq"))
    timestamp: PerpsTimestamp = Field(validation_alias=AliasChoices("timestamp", "ts"))
    hash: OptionalTxHash = None
    client_order_id: str | None = Field(default=None, validation_alias="coid")


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

    ``deadline`` echoes the armed cancellation time in epoch milliseconds, or
    ``0`` when the schedule was cleared.
    """

    status: Literal["ok"]
    deadline: int


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
