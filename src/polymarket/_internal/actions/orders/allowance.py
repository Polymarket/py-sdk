from polymarket._internal.actions import account as _account_actions
from polymarket._internal.actions.orders.types import OrderDraft
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.request import QueryParamValue
from polymarket._internal.wallet import WalletType, signature_type_for
from polymarket.models.types import ClobAssetId, OrderSide
from polymarket.types import EvmAddress


async def fetch_current_allowance(
    ctx: AsyncSecureClientContext, *, draft: OrderDraft, spender: EvmAddress
) -> int:
    path, params = _balance_allowance_request_for_draft(ctx.wallet_type, draft=draft)
    balance = _account_actions.parse_balance_allowance(
        await ctx.secure_clob.get_json(path, params=params)
    )
    return _allowance_for_spender(balance.allowances, spender)


def fetch_current_allowance_sync(
    ctx: SyncSecureClientContext, *, draft: OrderDraft, spender: EvmAddress
) -> int:
    path, params = _balance_allowance_request_for_draft(ctx.wallet_type, draft=draft)
    balance = _account_actions.parse_balance_allowance(
        ctx.secure_clob.get_json(path, params=params)
    )
    return _allowance_for_spender(balance.allowances, spender)


async def fetch_current_order_allowance(
    ctx: AsyncSecureClientContext, *, side: OrderSide, asset_id: ClobAssetId, spender: EvmAddress
) -> int:
    path, params = _balance_allowance_request_for_side(
        ctx.wallet_type, side=side, asset_id=asset_id
    )
    balance = _account_actions.parse_balance_allowance(
        await ctx.secure_clob.get_json(path, params=params)
    )
    return _allowance_for_spender(balance.allowances, spender)


def fetch_current_order_allowance_sync(
    ctx: SyncSecureClientContext, *, side: OrderSide, asset_id: ClobAssetId, spender: EvmAddress
) -> int:
    path, params = _balance_allowance_request_for_side(
        ctx.wallet_type, side=side, asset_id=asset_id
    )
    balance = _account_actions.parse_balance_allowance(
        ctx.secure_clob.get_json(path, params=params)
    )
    return _allowance_for_spender(balance.allowances, spender)


def _balance_allowance_request_for_draft(
    wallet_type: WalletType, *, draft: OrderDraft
) -> tuple[str, dict[str, QueryParamValue]]:
    return _balance_allowance_request_for_side(
        wallet_type, side=draft.side, asset_id=draft.asset_id
    )


def _balance_allowance_request_for_side(
    wallet_type: WalletType, *, side: OrderSide, asset_id: ClobAssetId
) -> tuple[str, dict[str, QueryParamValue]]:
    signature_type = signature_type_for(wallet_type)
    if side == "BUY":
        return _account_actions.build_balance_allowance_request(
            asset_type="COLLATERAL", token_id=None, signature_type=signature_type
        )
    return _account_actions.build_balance_allowance_request(
        asset_type="CONDITIONAL",
        token_id=asset_id,
        signature_type=signature_type,
    )


def _allowance_for_spender(allowances: dict[str, int], spender: str) -> int:
    target = spender.lower()
    for key, value in allowances.items():
        if key.lower() == target:
            return value
    return 0


__all__ = [
    "fetch_current_allowance",
    "fetch_current_allowance_sync",
    "fetch_current_order_allowance",
    "fetch_current_order_allowance_sync",
]
