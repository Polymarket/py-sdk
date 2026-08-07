from __future__ import annotations

from typing import TYPE_CHECKING

from polymarket._internal.actions import account as _account_actions
from polymarket._internal.actions.orders import post as _post_actions
from polymarket._internal.actions.orders.allowance import (
    fetch_current_order_allowance,
    fetch_current_order_allowance_sync,
)
from polymarket._internal.actions.orders.context import resolve_exchange_address
from polymarket._internal.wallet import signature_type_for
from polymarket.errors import RequestRejectedError
from polymarket.models.clob import AssetType
from polymarket.models.clob.order_response import OrderResponse
from polymarket.models.clob.orders import SignedOrder

if TYPE_CHECKING:
    from polymarket.clients.async_secure import AsyncSecureClient
    from polymarket.clients.secure import SecureClient

_ALLOWANCE_REJECTION_TOKEN = "allowance is not enough"


def is_balance_or_allowance_rejection(error: BaseException) -> bool:
    return (
        isinstance(error, RequestRejectedError)
        and error.status == 400
        and _ALLOWANCE_REJECTION_TOKEN in str(error)
    )


async def post_order_with_allowance_recovery(
    client: AsyncSecureClient, signed_order: SignedOrder
) -> OrderResponse:
    try:
        return await _post_order(client, signed_order)
    except Exception as error:
        if not is_balance_or_allowance_rejection(error):
            raise
        approved = await _approve_order_if_under_allowance(client, signed_order)
        if not approved:
            raise
        return await _post_order(client, signed_order)


def post_order_with_allowance_recovery_sync(
    client: SecureClient, signed_order: SignedOrder
) -> OrderResponse:
    try:
        return _post_order_sync(client, signed_order)
    except Exception as error:
        if not is_balance_or_allowance_rejection(error):
            raise
        approved = _approve_order_if_under_allowance_sync(client, signed_order)
        if not approved:
            raise
        return _post_order_sync(client, signed_order)


async def _post_order(client: AsyncSecureClient, signed_order: SignedOrder) -> OrderResponse:
    ctx = client._ctx  # pyright: ignore[reportPrivateUsage]
    path, payload = _post_actions.build_post_order_request(
        signed_order, owner_api_key=ctx.credentials.key
    )
    return _post_actions.parse_order_response(await ctx.secure_clob.post_json(path, json=payload))


def _post_order_sync(client: SecureClient, signed_order: SignedOrder) -> OrderResponse:
    ctx = client._ctx  # pyright: ignore[reportPrivateUsage]
    path, payload = _post_actions.build_post_order_request(
        signed_order, owner_api_key=ctx.credentials.key
    )
    return _post_actions.parse_order_response(ctx.secure_clob.post_json(path, json=payload))


async def _approve_order_if_under_allowance(
    client: AsyncSecureClient, signed_order: SignedOrder
) -> bool:
    ctx = client._ctx  # pyright: ignore[reportPrivateUsage]
    metadata = await ctx.order_metadata.resolve_market(ctx, token_id=signed_order.token_id)
    spender = resolve_exchange_address(ctx.environment_config, metadata.neg_risk)
    current = await fetch_current_order_allowance(
        ctx, side=signed_order.side, token_id=signed_order.token_id, spender=spender
    )
    required = signed_order.maker_amount
    if current >= required:
        return False

    if signed_order.side == "BUY":
        handle = await client.approve_erc20(
            token_address=ctx.environment_config.collateral_token,
            spender_address=str(spender),
            amount="max",
        )
    else:
        handle = await client.approve_erc1155_for_all(
            token_address=ctx.environment_config.conditional_tokens,
            operator_address=str(spender),
        )
    await handle.wait()
    await _refresh_balance_allowance(client, signed_order)
    return True


def _approve_order_if_under_allowance_sync(client: SecureClient, signed_order: SignedOrder) -> bool:
    ctx = client._ctx  # pyright: ignore[reportPrivateUsage]
    metadata = ctx.order_metadata.resolve_market(ctx, token_id=signed_order.token_id)
    spender = resolve_exchange_address(ctx.environment_config, metadata.neg_risk)
    current = fetch_current_order_allowance_sync(
        ctx, side=signed_order.side, token_id=signed_order.token_id, spender=spender
    )
    required = signed_order.maker_amount
    if current >= required:
        return False

    if signed_order.side == "BUY":
        handle = client.approve_erc20(
            token_address=ctx.environment_config.collateral_token,
            spender_address=str(spender),
            amount="max",
        )
    else:
        handle = client.approve_erc1155_for_all(
            token_address=ctx.environment_config.conditional_tokens,
            operator_address=str(spender),
        )
    handle.wait()
    _refresh_balance_allowance_sync(client, signed_order)
    return True


async def _refresh_balance_allowance(client: AsyncSecureClient, signed_order: SignedOrder) -> None:
    ctx = client._ctx  # pyright: ignore[reportPrivateUsage]
    asset_type, token_id = _refresh_target(signed_order)
    signature_type = signature_type_for(ctx.wallet_type)
    update_path, update_params = _account_actions.build_update_balance_allowance_request(
        asset_type=asset_type,
        token_id=token_id,
        signature_type=signature_type,
    )
    # /balance-allowance/update is a side-effect endpoint; body is not consumed.
    await ctx.secure_clob.get_bytes(update_path, params=update_params)
    fetch_path, fetch_params = _account_actions.build_balance_allowance_request(
        asset_type=asset_type,
        token_id=token_id,
        signature_type=signature_type,
    )
    _account_actions.parse_balance_allowance(
        await ctx.secure_clob.get_json(fetch_path, params=fetch_params)
    )


def _refresh_balance_allowance_sync(client: SecureClient, signed_order: SignedOrder) -> None:
    ctx = client._ctx  # pyright: ignore[reportPrivateUsage]
    asset_type, token_id = _refresh_target(signed_order)
    signature_type = signature_type_for(ctx.wallet_type)
    update_path, update_params = _account_actions.build_update_balance_allowance_request(
        asset_type=asset_type,
        token_id=token_id,
        signature_type=signature_type,
    )
    ctx.secure_clob.get_bytes(update_path, params=update_params)
    fetch_path, fetch_params = _account_actions.build_balance_allowance_request(
        asset_type=asset_type,
        token_id=token_id,
        signature_type=signature_type,
    )
    _account_actions.parse_balance_allowance(
        ctx.secure_clob.get_json(fetch_path, params=fetch_params)
    )


def _refresh_target(signed_order: SignedOrder) -> tuple[AssetType, str | None]:
    if signed_order.side == "BUY":
        return "COLLATERAL", None
    return "CONDITIONAL", signed_order.token_id


__all__ = [
    "is_balance_or_allowance_rejection",
    "post_order_with_allowance_recovery",
    "post_order_with_allowance_recovery_sync",
]
