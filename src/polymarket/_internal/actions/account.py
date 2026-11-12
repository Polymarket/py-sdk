from collections.abc import Sequence
from typing import cast

from eth_utils.address import is_address
from pydantic import TypeAdapter, ValidationError

from polymarket._internal.actions._cursor import (
    END_CURSOR,
    next_cursor_or_none,
    validate_cursor,
)
from polymarket._internal.actions.exchange_asset import resolve_optional_asset_id
from polymarket._internal.request import QueryParamValue
from polymarket._internal.validation import require_nonempty
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.clob import (
    AssetType,
    BalanceAllowance,
    ClobTrade,
    Notification,
    OpenOrder,
    WalletOpenOrder,
)
from polymarket.pagination import Page

_OpenOrdersAdapter = TypeAdapter(tuple[OpenOrder, ...])
_WalletOpenOrdersAdapter = TypeAdapter(tuple[WalletOpenOrder, ...])
_ClobTradesAdapter = TypeAdapter(tuple[ClobTrade, ...])
_NotificationsAdapter = TypeAdapter(tuple[Notification, ...])

_VALID_ASSET_TYPES: frozenset[str] = frozenset({"COLLATERAL", "CONDITIONAL", "CONDITIONAL-V2"})


def _validate_asset_type(asset_type: object) -> None:
    if asset_type not in _VALID_ASSET_TYPES:
        raise UserInputError(
            "asset_type must be 'COLLATERAL', 'CONDITIONAL', or "
            f"'CONDITIONAL-V2', got {asset_type!r}."
        )


def _add_optional(params: dict[str, QueryParamValue], key: str, value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str | int | float | bool):
        raise UserInputError(f"{key} must be a primitive, got {type(value).__name__}.")
    params[key] = value


def build_closed_only_mode_request() -> tuple[str, dict[str, str]]:
    return "/auth/ban-status/closed-only", {}


def parse_closed_only_mode(data: object) -> bool:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("closed-only mode response did not match expected shape")
    raw = cast(dict[str, object], data).get("closed_only")
    if not isinstance(raw, bool):
        raise UnexpectedResponseError(
            f"closed-only mode response 'closed_only' must be a bool, got {type(raw).__name__}"
        )
    return raw


def build_list_open_orders_request(
    *,
    asset_id: str | None = None,
    token_id: str | None = None,
    id: str | None = None,
    market: str | None = None,
    cursor: str | None = None,
) -> tuple[str, dict[str, QueryParamValue]]:
    params: dict[str, QueryParamValue] = {}
    resolved_asset = resolve_optional_asset_id(asset_id=asset_id, token_id=token_id)
    if resolved_asset is not None:
        if market is None or not require_nonempty("market", market).strip():
            raise UserInputError("market is required when filtering by asset_id or token_id.")
        _add_optional(params, "asset_id", resolved_asset)
    if id is not None:
        _add_optional(params, "id", require_nonempty("id", id))
    if market is not None:
        _add_optional(params, "market", require_nonempty("market", market))
    validated_cursor = validate_cursor(cursor)
    if validated_cursor is not None:
        _add_optional(params, "next_cursor", validated_cursor)
    return "/data/orders", params


def parse_open_orders_page(data: object) -> Page[OpenOrder]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("open orders response did not match expected shape")
    payload = cast(dict[str, object], data)
    try:
        items = _OpenOrdersAdapter.validate_python(payload.get("data"))
    except ValidationError as error:
        raise UnexpectedResponseError("open orders response items malformed") from error
    next_cursor = next_cursor_or_none(payload.get("next_cursor"))
    return Page(
        items=items,
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


def build_list_wallet_open_orders_request(
    *,
    market: str | None = None,
    asset_id: str | None = None,
    signer_addresses: Sequence[str] | None = None,
    cursor: str | None = None,
) -> tuple[str, dict[str, QueryParamValue]]:
    params: dict[str, QueryParamValue] = {}
    if market is not None:
        params["market"] = require_nonempty("market", market)
    if asset_id is not None:
        params["asset_id"] = require_nonempty("asset_id", asset_id)
    if signer_addresses is not None:
        # An empty filter must not widen into every signer's orders.
        if isinstance(signer_addresses, str | bytes) or not 1 <= len(signer_addresses) <= 50:
            raise UserInputError("signer_addresses must contain between 1 and 50 addresses.")
        if not all(
            isinstance(a, str) and a.startswith("0x") and is_address(a)
            for a in cast(Sequence[object], signer_addresses)
        ):
            raise UserInputError("signer_addresses must contain valid EVM addresses.")
        params["session_keys"] = ",".join(signer_addresses)
    validated_cursor = validate_cursor(cursor)
    if validated_cursor is not None:
        params["cursor"] = validated_cursor
    return "/data/wallet-open-orders", params


def parse_wallet_open_orders_page(data: object) -> Page[WalletOpenOrder]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("wallet open orders response did not match expected shape")
    payload = cast(dict[str, object], data)
    try:
        items = _WalletOpenOrdersAdapter.validate_python(payload.get("data"))
    except ValidationError as error:
        raise UnexpectedResponseError("wallet open orders response items malformed") from error
    cursor = payload.get("next_cursor")
    if not isinstance(cursor, str):
        raise UnexpectedResponseError("wallet open orders next_cursor must be a string")
    return Page(items=items, has_more=bool(cursor), next_cursor=cursor or None)


def build_get_order_request(*, order_id: str) -> tuple[str, dict[str, str]]:
    validated = require_nonempty("order_id", order_id)
    return f"/data/order/{validated}", {}


def parse_open_order(data: object) -> OpenOrder:
    return OpenOrder.parse_response(data)


def build_list_account_trades_request(
    *,
    asset_id: str | None = None,
    token_id: str | None = None,
    id: str | None = None,
    market: str | None = None,
    maker_address: str | None = None,
    after: str | None = None,
    before: str | None = None,
    cursor: str | None = None,
) -> tuple[str, dict[str, QueryParamValue]]:
    params: dict[str, QueryParamValue] = {}
    resolved_asset = resolve_optional_asset_id(asset_id=asset_id, token_id=token_id)
    if resolved_asset is not None:
        _add_optional(params, "asset_id", resolved_asset)
    if id is not None:
        _add_optional(params, "id", require_nonempty("id", id))
    if market is not None:
        _add_optional(params, "market", require_nonempty("market", market))
    if maker_address is not None:
        _add_optional(params, "maker_address", require_nonempty("maker_address", maker_address))
    if after is not None:
        _add_optional(params, "after", require_nonempty("after", after))
    if before is not None:
        _add_optional(params, "before", require_nonempty("before", before))
    validated_cursor = validate_cursor(cursor)
    if validated_cursor is not None:
        _add_optional(params, "next_cursor", validated_cursor)
    return "/data/trades", params


def parse_account_trades_page(data: object) -> Page[ClobTrade]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("account trades response did not match expected shape")
    payload = cast(dict[str, object], data)
    try:
        items = _ClobTradesAdapter.validate_python(payload.get("data"))
    except ValidationError as error:
        raise UnexpectedResponseError("account trades response items malformed") from error
    next_cursor = next_cursor_or_none(payload.get("next_cursor"))
    return Page(
        items=items,
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


def build_notifications_request(*, signature_type: int) -> tuple[str, dict[str, QueryParamValue]]:
    return "/notifications", {"signature_type": signature_type}


def parse_notifications(data: object) -> tuple[Notification, ...]:
    try:
        return _NotificationsAdapter.validate_python(data)
    except ValidationError as error:
        raise UnexpectedResponseError(
            "notifications response did not match expected shape"
        ) from error


def build_drop_notifications_request(
    *, ids: Sequence[int | str], signature_type: int
) -> tuple[str, dict[str, QueryParamValue]]:
    if isinstance(ids, str | bytes):
        raise UserInputError("ids must be a sequence of notification ids, not a single string.")
    if not ids:
        raise UserInputError("ids must be a non-empty sequence.")
    validated: list[str] = []
    for entry in cast(Sequence[object], ids):
        if isinstance(entry, bool) or not isinstance(entry, int | str):
            raise UserInputError(f"ids entry must be an int or string, got {type(entry).__name__}.")
        if isinstance(entry, str):
            validated.append(require_nonempty("notification id", entry))
        else:
            validated.append(str(entry))
    return "/notifications", {
        "ids": ",".join(validated),
        "signature_type": signature_type,
    }


def build_balance_allowance_request(
    *,
    asset_type: AssetType,
    asset_id: str | None = None,
    token_id: str | None = None,
    signature_type: int,
) -> tuple[str, dict[str, QueryParamValue]]:
    _validate_asset_type(asset_type)
    params: dict[str, QueryParamValue] = {
        "asset_type": asset_type,
        "signature_type": signature_type,
    }
    resolved_asset = resolve_optional_asset_id(asset_id=asset_id, token_id=token_id)
    if resolved_asset is not None:
        params["token_id"] = resolved_asset
    return "/balance-allowance", params


def parse_balance_allowance(data: object) -> BalanceAllowance:
    return BalanceAllowance.parse_response(data)


def build_update_balance_allowance_request(
    *,
    asset_type: AssetType,
    asset_id: str | None = None,
    token_id: str | None = None,
    signature_type: int,
) -> tuple[str, dict[str, QueryParamValue]]:
    _validate_asset_type(asset_type)
    params: dict[str, QueryParamValue] = {
        "asset_type": asset_type,
        "signature_type": signature_type,
    }
    resolved_asset = resolve_optional_asset_id(asset_id=asset_id, token_id=token_id)
    if resolved_asset is not None:
        params["token_id"] = resolved_asset
    return "/balance-allowance/update", params


__all__ = [
    "END_CURSOR",
    "build_balance_allowance_request",
    "build_closed_only_mode_request",
    "build_drop_notifications_request",
    "build_get_order_request",
    "build_list_account_trades_request",
    "build_list_open_orders_request",
    "build_list_wallet_open_orders_request",
    "build_notifications_request",
    "build_update_balance_allowance_request",
    "parse_account_trades_page",
    "parse_balance_allowance",
    "parse_closed_only_mode",
    "parse_notifications",
    "parse_open_order",
    "parse_open_orders_page",
    "parse_wallet_open_orders_page",
]
