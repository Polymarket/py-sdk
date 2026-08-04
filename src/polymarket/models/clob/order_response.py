from __future__ import annotations

from decimal import Decimal
from typing import Literal, TypeAlias

from pydantic import Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    _DecimalFromString,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.types import OrderId
from polymarket.types import TransactionHash

OrderPostStatus: TypeAlias = Literal["live", "matched", "delayed"]
OrderResponseErrorCode: TypeAlias = Literal[
    "unmatched",
    "market_not_ready",
    "not_enough_balance",
    "invalid_nonce",
    "invalid_expiration",
    "post_only_would_cross",
    "fok_not_filled",
    "fak_not_filled",
    "unknown",
]

_ORDER_POST_STATUSES: frozenset[str] = frozenset({"live", "matched", "delayed"})

_FOK_NOT_FILLED_MSG = "order couldn't be fully filled. FOK orders are fully filled or killed."
_FAK_NOT_FILLED_MSG = (
    "no orders found to match with FAK order. "
    "FAK orders are partially filled or killed if no match is found."
)

_ERROR_MSG_TO_CODE: dict[str, OrderResponseErrorCode] = {
    "the market is not yet ready to process new orders": "market_not_ready",
    "invalid nonce": "invalid_nonce",
    "invalid expiration": "invalid_expiration",
    "invalid post-only order: order crosses book": "post_only_would_cross",
    _FOK_NOT_FILLED_MSG: "fok_not_filled",
    _FAK_NOT_FILLED_MSG: "fak_not_filled",
}


class RawOrderResponse(BaseModel):
    error_msg: str = Field(validation_alias="errorMsg")
    making_amount: _DecimalFromString = Field(validation_alias="makingAmount")
    order_id: str = Field(validation_alias="orderID")
    status: str
    success: bool
    taking_amount: _DecimalFromString = Field(validation_alias="takingAmount")
    trade_ids: tuple[str, ...] = Field(default=(), validation_alias="tradeIDs")
    transactions_hashes: tuple[str, ...] = Field(default=(), validation_alias="transactionsHashes")

    @field_validator("making_amount", "taking_amount", mode="before")
    @classmethod
    def _empty_string_to_zero(cls, value: object) -> object:
        return "0" if value == "" else value


class AcceptedOrder(BaseModel):
    """A successfully placed order.

    ``trade_ids`` identifies the trades created by fills at placement; it is
    empty when the order did not match, and later fills of a resting order
    create new trades that are not listed here. ``transactions_hashes`` holds
    the settlement transaction hashes of those fills on a best-effort basis:
    settlement happens asynchronously, so it can be empty even when the order
    matched. Use ``wait_for_order_fill_settlement`` to obtain hashes reliably.
    """

    ok: Literal[True] = True
    order_id: OrderId
    status: OrderPostStatus
    making_amount: Decimal
    taking_amount: Decimal
    trade_ids: tuple[str, ...]
    transactions_hashes: tuple[TransactionHash, ...]

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: AcceptedOrder) -> str:
            title = f"OrderResponse  ·  accepted  ·  {self.status}"
            rows: list[tuple[str, str]] = [
                ("order_id", truncate_mid(self.order_id)),
                ("making_amount", str(self.making_amount)),
                ("taking_amount", str(self.taking_amount)),
                ("trades", str(len(self.trade_ids))),
                ("tx hashes", str(len(self.transactions_hashes))),
            ]
            return card(title, rows=rows)

        return render(self)


class RejectedOrder(BaseModel):
    """An order that was refused at placement, with a machine-readable code."""

    ok: Literal[False] = False
    code: OrderResponseErrorCode
    message: str

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr

        @safe_html_repr
        def render(self: RejectedOrder) -> str:
            title = f"OrderResponse  ·  rejected  ·  {self.code}"
            return card(title, rows=[("message", self.message)])

        return render(self)


OrderResponse: TypeAlias = AcceptedOrder | RejectedOrder


def normalize_order_response(raw: RawOrderResponse) -> OrderResponse:
    if _is_accepted(raw):
        return AcceptedOrder(
            order_id=OrderId(raw.order_id),
            status=raw.status,  # type: ignore[arg-type]
            making_amount=raw.making_amount,
            taking_amount=raw.taking_amount,
            trade_ids=raw.trade_ids,
            transactions_hashes=tuple(TransactionHash(tx) for tx in raw.transactions_hashes),
        )
    return RejectedOrder(
        code=_infer_error_code(raw),
        message=raw.error_msg or "Unknown order failure",
    )


def _is_accepted(raw: RawOrderResponse) -> bool:
    return (
        raw.success
        and raw.error_msg == ""
        and raw.order_id != ""
        and raw.status in _ORDER_POST_STATUSES
    )


def _infer_error_code(raw: RawOrderResponse) -> OrderResponseErrorCode:
    if raw.status == "unmatched":
        return "unmatched"
    mapped = _ERROR_MSG_TO_CODE.get(raw.error_msg)
    if mapped is not None:
        return mapped
    if "not enough balance / allowance" in raw.error_msg:
        return "not_enough_balance"
    return "unknown"


__all__ = [
    "AcceptedOrder",
    "OrderPostStatus",
    "OrderResponse",
    "OrderResponseErrorCode",
    "RawOrderResponse",
    "RejectedOrder",
    "normalize_order_response",
]
