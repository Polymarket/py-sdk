from __future__ import annotations

import httpx

from polymarket._internal.actions.relayer.calls import TransactionCall
from polymarket._internal.actions.relayer.gasless import (
    build_signed_deposit_wallet_payload,
    build_signed_deposit_wallet_payload_sync,
    build_signed_payload_for_wallet_type,
    build_signed_payload_for_wallet_type_sync,
    submit_gasless_with_retry,
    submit_gasless_with_retry_sync,
)
from polymarket._internal.actions.relayer.submit import onchain_nonce_from_submit_error
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.wallet import WalletType
from polymarket.errors import RequestRejectedError, UserInputError
from polymarket.models.clob.relayer import RelayerExecuteResponse
from polymarket.models.collateral_return import CollateralReturnPlanResponse
from polymarket.transactions import GaslessTransactionHandle, SyncGaslessTransactionHandle
from polymarket.types import EvmAddress

# Planning and submit re-validation both recompute wallet state server-side
# and can take well beyond the transport's standard timeout.
_REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)

_PLAN_PATH = "/v1/collateral-return/plan"
_SUBMIT_PATH = "/v1/collateral-return/submit"
_METADATA = "Collateral return"

_MISSING_API_KEY_MESSAGE = (
    "Collateral return execution requires a Builder API Key or Relayer API Key. "
    "Pass api_key= when constructing the client."
)


async def plan_collateral_return(ctx: AsyncSecureClientContext) -> CollateralReturnPlanResponse:
    _require_supported_wallet_type(ctx.wallet_type)
    data = await ctx.combos.post_json(
        _PLAN_PATH, json={"wallet": str(ctx.wallet)}, timeout=_REQUEST_TIMEOUT
    )
    return CollateralReturnPlanResponse.parse_response(data)


def plan_collateral_return_sync(ctx: SyncSecureClientContext) -> CollateralReturnPlanResponse:
    _require_supported_wallet_type(ctx.wallet_type)
    data = ctx.combos.post_json(
        _PLAN_PATH, json={"wallet": str(ctx.wallet)}, timeout=_REQUEST_TIMEOUT
    )
    return CollateralReturnPlanResponse.parse_response(data)


async def execute_collateral_return_plan(
    ctx: AsyncSecureClientContext, *, plan: CollateralReturnPlanResponse
) -> GaslessTransactionHandle:
    if ctx.api_key is None:
        raise UserInputError(_MISSING_API_KEY_MESSAGE)
    _require_supported_wallet_type(ctx.wallet_type)
    _require_plan_matches_client(plan, wallet=ctx.wallet, chain_id=ctx.environment.chain_id)

    call = TransactionCall(to=plan.router_call.to, data=plan.router_call.data, value=0)
    return await submit_gasless_with_retry(
        ctx, submit=lambda: _submit_plan(ctx, plan_hash=plan.plan_hash, call=call)
    )


def execute_collateral_return_plan_sync(
    ctx: SyncSecureClientContext, *, plan: CollateralReturnPlanResponse
) -> SyncGaslessTransactionHandle:
    if ctx.api_key is None:
        raise UserInputError(_MISSING_API_KEY_MESSAGE)
    _require_supported_wallet_type(ctx.wallet_type)
    _require_plan_matches_client(plan, wallet=ctx.wallet, chain_id=ctx.environment.chain_id)

    call = TransactionCall(to=plan.router_call.to, data=plan.router_call.data, value=0)
    return submit_gasless_with_retry_sync(
        ctx, submit=lambda: _submit_plan_sync(ctx, plan_hash=plan.plan_hash, call=call)
    )


def _require_supported_wallet_type(wallet_type: WalletType) -> None:
    if wallet_type == "EOA":
        raise UserInputError(
            "Collateral return supports Deposit Wallet, Safe-backed, and proxy-backed "
            "accounts. EOA wallets are not supported."
        )


def _require_plan_matches_client(
    plan: CollateralReturnPlanResponse, *, wallet: EvmAddress, chain_id: int
) -> None:
    if str(plan.wallet).lower() != str(wallet).lower():
        raise UserInputError(
            f"Plan wallet {plan.wallet} does not match the authenticated wallet {wallet}"
        )
    if plan.chain_id != chain_id:
        raise UserInputError(
            f"Plan chain id {plan.chain_id} does not match the client chain id {chain_id}"
        )


async def _submit_plan(
    ctx: AsyncSecureClientContext, *, plan_hash: str, call: TransactionCall
) -> RelayerExecuteResponse:
    envelope = await build_signed_payload_for_wallet_type(ctx, calls=[call], metadata=_METADATA)
    try:
        data = await ctx.combos.post_json(
            _SUBMIT_PATH,
            json={"plan_hash": plan_hash, "envelope": envelope},
            timeout=_REQUEST_TIMEOUT,
        )
    except RequestRejectedError as error:
        nonce = onchain_nonce_from_submit_error(error)
        if nonce is None or ctx.wallet_type != "DEPOSIT_WALLET":
            raise
        envelope = await build_signed_deposit_wallet_payload(
            ctx, calls=[call], metadata=_METADATA, nonce=nonce
        )
        data = await ctx.combos.post_json(
            _SUBMIT_PATH,
            json={"plan_hash": plan_hash, "envelope": envelope},
            timeout=_REQUEST_TIMEOUT,
        )
    return RelayerExecuteResponse.parse_response(data)


def _submit_plan_sync(
    ctx: SyncSecureClientContext, *, plan_hash: str, call: TransactionCall
) -> RelayerExecuteResponse:
    envelope = build_signed_payload_for_wallet_type_sync(ctx, calls=[call], metadata=_METADATA)
    try:
        data = ctx.combos.post_json(
            _SUBMIT_PATH,
            json={"plan_hash": plan_hash, "envelope": envelope},
            timeout=_REQUEST_TIMEOUT,
        )
    except RequestRejectedError as error:
        nonce = onchain_nonce_from_submit_error(error)
        if nonce is None or ctx.wallet_type != "DEPOSIT_WALLET":
            raise
        envelope = build_signed_deposit_wallet_payload_sync(
            ctx, calls=[call], metadata=_METADATA, nonce=nonce
        )
        data = ctx.combos.post_json(
            _SUBMIT_PATH,
            json={"plan_hash": plan_hash, "envelope": envelope},
            timeout=_REQUEST_TIMEOUT,
        )
    return RelayerExecuteResponse.parse_response(data)


__all__ = [
    "execute_collateral_return_plan",
    "execute_collateral_return_plan_sync",
    "plan_collateral_return",
    "plan_collateral_return_sync",
]
