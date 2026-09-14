from collections.abc import Sequence
from typing import Any, cast

from polymarket._internal.actions.exchange_asset import resolve_optional_asset_id
from polymarket._internal.validation import require_nonempty
from polymarket.errors import UserInputError
from polymarket.models.clob.cancel import CancelOrdersResponse

_MAX_CANCEL_BATCH = 3000


def build_cancel_order_request(*, order_id: str) -> tuple[str, dict[str, str]]:
    validated = require_nonempty("order_id", order_id)
    return "/order", {"orderID": validated}


def build_cancel_orders_request(*, order_ids: Sequence[str]) -> tuple[str, list[str]]:
    if isinstance(order_ids, str | bytes):
        raise UserInputError("order_ids must be a sequence of strings, not a single string.")
    items = list(order_ids)
    if not items:
        raise UserInputError("order_ids must be a non-empty sequence.")
    if len(items) > _MAX_CANCEL_BATCH:
        raise UserInputError(f"order_ids cannot exceed {_MAX_CANCEL_BATCH} entries.")
    validated = [require_nonempty("order id", item) for item in items]
    return "/orders", validated


def build_cancel_all_request() -> tuple[str, None]:
    return "/cancel-all", None


def build_cancel_market_orders_request(
    *,
    market: str | None = None,
    asset_id: str | None = None,
    token_id: str | None = None,
) -> tuple[str, dict[str, str]]:
    resolved_asset = resolve_optional_asset_id(asset_id=asset_id, token_id=token_id)
    if market is None and resolved_asset is None:
        raise UserInputError("At least one of market or asset_id is required.")
    body: dict[str, str] = {}
    if resolved_asset is not None:
        body["asset_id"] = resolved_asset
    if market is not None:
        body["market"] = require_nonempty("market", market)
    return "/cancel-market-orders", body


def parse_cancel_orders_response(data: object) -> CancelOrdersResponse:
    if not isinstance(data, dict):
        from polymarket.errors import UnexpectedResponseError

        raise UnexpectedResponseError("cancel response did not match expected shape")
    payload = cast(dict[str, Any], data)
    return CancelOrdersResponse.parse_response(payload)


__all__ = [
    "build_cancel_all_request",
    "build_cancel_market_orders_request",
    "build_cancel_order_request",
    "build_cancel_orders_request",
    "parse_cancel_orders_response",
]
