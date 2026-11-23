from collections.abc import Sequence
from typing import Any

from pydantic import TypeAdapter, ValidationError

from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.clob.order_response import (
    OrderResponse,
    RawOrderResponse,
    normalize_order_response,
)
from polymarket.models.clob.orders import SignedOrder

_MAX_BATCH = 15

_RawOrderResponsesAdapter = TypeAdapter(tuple[RawOrderResponse, ...])


def build_post_order_request(
    signed_order: SignedOrder, *, owner_api_key: str
) -> tuple[str, dict[str, Any]]:
    return "/v1/orders", _build_send_order_payload(signed_order, owner_api_key=owner_api_key)


def build_post_orders_request(
    signed_orders: Sequence[SignedOrder], *, owner_api_key: str
) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(signed_orders, str | bytes):
        raise UserInputError("signed_orders must be a sequence of SignedOrder values.")
    items = list(signed_orders)
    if not items:
        raise UserInputError("signed_orders must be a non-empty sequence.")
    if len(items) > _MAX_BATCH:
        raise UserInputError(f"signed_orders cannot exceed {_MAX_BATCH} entries.")
    payload = [_build_send_order_payload(order, owner_api_key=owner_api_key) for order in items]
    return "/v1/orders/batch", payload


def parse_order_response(data: object) -> OrderResponse:
    try:
        raw = RawOrderResponse.parse_response(data)
    except UnexpectedResponseError:
        raise
    return normalize_order_response(raw)


def parse_order_responses(data: object) -> tuple[OrderResponse, ...]:
    try:
        raw_items = _RawOrderResponsesAdapter.validate_python(data)
    except ValidationError as error:
        raise UnexpectedResponseError(
            "post-orders response did not match expected shape"
        ) from error
    return tuple(normalize_order_response(item) for item in raw_items)


def _build_send_order_payload(order: SignedOrder, *, owner_api_key: str) -> dict[str, Any]:
    if order.post_only and order.order_type not in ("GTC", "GTD"):
        raise UserInputError("post-only orders are only supported for GTC and GTD order types.")
    payload: dict[str, Any] = {
        "deferExec": False,
        "order": {
            "builder": order.builder,
            "expiration": str(order.expiration),
            "maker": order.maker,
            "makerAmount": str(order.maker_amount),
            "metadata": order.metadata,
            "salt": order.salt,
            "side": order.side,
            "signature": order.signature,
            "signatureType": order.signature_type,
            "signer": order.signer,
            "takerAmount": str(order.taker_amount),
            "timestamp": str(order.timestamp),
            "tokenId": order.token_id,
        },
        "orderType": order.order_type,
        "owner": owner_api_key,
    }
    if order.post_only:
        payload["postOnly"] = True
    return payload


__all__ = [
    "build_post_order_request",
    "build_post_orders_request",
    "parse_order_response",
    "parse_order_responses",
]
