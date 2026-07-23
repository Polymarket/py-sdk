from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_CEILING
from typing import cast

import httpx

from polymarket._internal.actions.relayer.calls import (
    TransactionCall,
    decode_erc20_allowance_result,
    decode_erc1155_is_approved_for_all_result,
    erc20_allowance_call,
    erc1155_is_approved_for_all_call,
)
from polymarket._internal.actions.relayer.gasless import (
    build_signed_payload_for_wallet_type,
    build_signed_payload_for_wallet_type_sync,
)
from polymarket._internal.actions.relayer.submit import (
    GASLESS_SUBMIT_RETRY_ATTEMPTS,
    is_retryable_submit_error,
)
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.wallet import WalletType
from polymarket.environments import Environment
from polymarket.errors import (
    CollateralReturnPlanRejectedError,
    MissingTradingApprovalsError,
    RequestRejectedError,
    UserInputError,
)
from polymarket.models.clob.relayer import RelayerExecuteResponse
from polymarket.models.collateral_return import CollateralReturnPlan
from polymarket.transactions import GaslessTransactionHandle, SyncGaslessTransactionHandle
from polymarket.types import EvmAddress

# Planning can take minutes for heavy wallets; only the plan request gets the
# long read timeout, submit uses the transport default.
_PLAN_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=2.0)

_PLAN_PATH = "/v1/collateral-return/plan"
_SUBMIT_PATH = "/v1/collateral-return/submit"
_METADATA = "Collateral return"

_MISSING_API_KEY_MESSAGE = (
    "Collateral return execution requires a Builder API Key or Relayer API Key. "
    "Pass api_key= when constructing the client."
)


async def plan_collateral_return(ctx: AsyncSecureClientContext) -> CollateralReturnPlan:
    _require_supported_wallet_type(ctx.wallet_type)
    data = await ctx.combos.post_json(
        _PLAN_PATH, json={"wallet": str(ctx.wallet)}, timeout=_PLAN_TIMEOUT
    )
    return CollateralReturnPlan.parse_response(data)


def plan_collateral_return_sync(ctx: SyncSecureClientContext) -> CollateralReturnPlan:
    _require_supported_wallet_type(ctx.wallet_type)
    data = ctx.combos.post_json(_PLAN_PATH, json={"wallet": str(ctx.wallet)}, timeout=_PLAN_TIMEOUT)
    return CollateralReturnPlan.parse_response(data)


async def execute_collateral_return_plan(
    ctx: AsyncSecureClientContext, *, plan: CollateralReturnPlan
) -> GaslessTransactionHandle:
    if ctx.api_key is None:
        raise UserInputError(_MISSING_API_KEY_MESSAGE)
    _require_supported_wallet_type(ctx.wallet_type)
    _require_plan_matches_client(plan, wallet=ctx.wallet, chain_id=ctx.environment.chain_id)
    _require_executable_plan(plan)

    checks = _build_approval_checks(plan, wallet=ctx.wallet, environment=ctx.environment)
    if checks:
        results = await ctx.rpc.eth_call_batch(
            [(str(check.call.to), check.call.data) for check in checks]
        )
        _require_approvals(checks, results)

    call = TransactionCall(to=plan.router_call.to, data=plan.router_call.data, value=0)
    env = ctx.environment
    retry_delay_s = env.relayer_poll_frequency_ms / 1000
    last_error: BaseException | None = None
    for attempt in range(GASLESS_SUBMIT_RETRY_ATTEMPTS + 1):
        try:
            response = await _submit_plan(ctx, plan_hash=plan.plan_hash, call=call)
            return GaslessTransactionHandle(
                transaction_id=response.transaction_id,
                transaction_hash=response.transaction_hash,
                _relayer=ctx.relayer,
                _max_polls=env.relayer_max_polls,
                _poll_delay_s=env.relayer_poll_frequency_ms / 1000,
            )
        except Exception as error:
            last_error = error
            if attempt == GASLESS_SUBMIT_RETRY_ATTEMPTS or not is_retryable_submit_error(error):
                raise
            await asyncio.sleep(retry_delay_s)
    assert last_error is not None
    raise last_error


def execute_collateral_return_plan_sync(
    ctx: SyncSecureClientContext, *, plan: CollateralReturnPlan
) -> SyncGaslessTransactionHandle:
    if ctx.api_key is None:
        raise UserInputError(_MISSING_API_KEY_MESSAGE)
    _require_supported_wallet_type(ctx.wallet_type)
    _require_plan_matches_client(plan, wallet=ctx.wallet, chain_id=ctx.environment.chain_id)
    _require_executable_plan(plan)

    checks = _build_approval_checks(plan, wallet=ctx.wallet, environment=ctx.environment)
    if checks:
        results = ctx.rpc.eth_call_batch(
            [(str(check.call.to), check.call.data) for check in checks]
        )
        _require_approvals(checks, results)

    call = TransactionCall(to=plan.router_call.to, data=plan.router_call.data, value=0)
    env = ctx.environment
    retry_delay_s = env.relayer_poll_frequency_ms / 1000
    last_error: BaseException | None = None
    for attempt in range(GASLESS_SUBMIT_RETRY_ATTEMPTS + 1):
        try:
            response = _submit_plan_sync(ctx, plan_hash=plan.plan_hash, call=call)
            return SyncGaslessTransactionHandle(
                transaction_id=response.transaction_id,
                transaction_hash=response.transaction_hash,
                _relayer=ctx.relayer,
                _max_polls=env.relayer_max_polls,
                _poll_delay_s=env.relayer_poll_frequency_ms / 1000,
            )
        except Exception as error:
            last_error = error
            if attempt == GASLESS_SUBMIT_RETRY_ATTEMPTS or not is_retryable_submit_error(error):
                raise
            time.sleep(retry_delay_s)
    assert last_error is not None
    raise last_error


def _require_supported_wallet_type(wallet_type: WalletType) -> None:
    if wallet_type == "EOA":
        raise UserInputError(
            "Collateral return supports Deposit Wallet, Safe-backed, and proxy-backed "
            "accounts. EOA wallets are not supported."
        )


def _require_plan_matches_client(
    plan: CollateralReturnPlan, *, wallet: EvmAddress, chain_id: int
) -> None:
    if str(plan.wallet).lower() != str(wallet).lower():
        raise UserInputError(
            f"Plan wallet {plan.wallet} does not match the authenticated wallet {wallet}"
        )
    if plan.chain_id != chain_id:
        raise UserInputError(
            f"Plan chain id {plan.chain_id} does not match the client chain id {chain_id}"
        )


def _require_executable_plan(plan: CollateralReturnPlan) -> None:
    if not plan.operations:
        raise UserInputError(
            "Plan contains no operations; there is no collateral to return. "
            "Request a fresh plan once the wallet holds returnable positions."
        )


@dataclass(frozen=True, slots=True)
class _ApprovalCheck:
    description: str
    call: TransactionCall
    is_satisfied: Callable[[str], bool]


def _build_approval_checks(
    plan: CollateralReturnPlan, *, wallet: EvmAddress, environment: Environment
) -> list[_ApprovalCheck]:
    checks: list[_ApprovalCheck] = []
    if plan.required_positions:
        checks.append(
            _ApprovalCheck(
                description="position operator approval",
                call=erc1155_is_approved_for_all_call(
                    token_address=cast(EvmAddress, environment.position_manager),
                    owner=wallet,
                    operator=cast(EvmAddress, environment.protocol_v2_router),
                ),
                is_satisfied=decode_erc1155_is_approved_for_all_result,
            )
        )
    required_collateral_units = int(
        plan.required_collateral.scaleb(6).to_integral_value(rounding=ROUND_CEILING)
    )
    if required_collateral_units > 0:
        checks.append(
            _ApprovalCheck(
                description="collateral allowance",
                call=erc20_allowance_call(
                    token_address=cast(EvmAddress, environment.collateral_token),
                    owner=wallet,
                    spender=cast(EvmAddress, environment.protocol_v2_router),
                ),
                is_satisfied=lambda data: (
                    decode_erc20_allowance_result(data) >= required_collateral_units
                ),
            )
        )
    return checks


def _require_approvals(checks: list[_ApprovalCheck], results: list[str]) -> None:
    for check, result in zip(checks, results, strict=True):
        if not check.is_satisfied(result):
            raise MissingTradingApprovalsError(
                f"The wallet is missing the {check.description} required to execute "
                "this plan. Run setup_trading_approvals() and retry."
            )


async def _submit_plan(
    ctx: AsyncSecureClientContext, *, plan_hash: str, call: TransactionCall
) -> RelayerExecuteResponse:
    envelope = await build_signed_payload_for_wallet_type(ctx, calls=[call], metadata=_METADATA)
    try:
        data = await ctx.combos.post_json(
            _SUBMIT_PATH, json={"plan_hash": plan_hash, "envelope": envelope}
        )
    except RequestRejectedError as error:
        if error.status == 409:
            raise CollateralReturnPlanRejectedError(str(error)) from error
        raise
    return RelayerExecuteResponse.parse_response(data)


def _submit_plan_sync(
    ctx: SyncSecureClientContext, *, plan_hash: str, call: TransactionCall
) -> RelayerExecuteResponse:
    envelope = build_signed_payload_for_wallet_type_sync(ctx, calls=[call], metadata=_METADATA)
    try:
        data = ctx.combos.post_json(
            _SUBMIT_PATH, json={"plan_hash": plan_hash, "envelope": envelope}
        )
    except RequestRejectedError as error:
        if error.status == 409:
            raise CollateralReturnPlanRejectedError(str(error)) from error
        raise
    return RelayerExecuteResponse.parse_response(data)


__all__ = [
    "execute_collateral_return_plan",
    "execute_collateral_return_plan_sync",
    "plan_collateral_return",
    "plan_collateral_return_sync",
]
