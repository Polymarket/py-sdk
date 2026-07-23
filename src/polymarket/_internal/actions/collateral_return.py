from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never, cast

import httpx

from polymarket._internal.actions.relayer.calls import (
    TransactionCall,
    decode_erc20_allowance_result,
    decode_erc1155_is_approved_for_all_result,
    encode_proxy_call,
    erc20_allowance_call,
    erc1155_is_approved_for_all_call,
)
from polymarket._internal.actions.relayer.gasless import (
    build_deposit_wallet_payload,
    build_proxy_payload,
    build_safe_payload,
)
from polymarket._internal.actions.relayer.nonce import (
    fetch_execute_params,
    fetch_execute_params_sync,
    fetch_relay_payload,
    fetch_relay_payload_sync,
)
from polymarket._internal.actions.relayer.signing.deposit_wallet import (
    sign_deposit_wallet_batch,
)
from polymarket._internal.actions.relayer.signing.proxy import (
    build_proxy_transaction_hash,
    sign_proxy_message,
)
from polymarket._internal.actions.relayer.signing.safe import sign_safe_transaction
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
from polymarket.models.clob.relayer import RelayerExecuteResponse, RelayerTransactionType
from polymarket.models.collateral_return import CollateralReturnPlan
from polymarket.transactions import GaslessTransactionHandle, SyncGaslessTransactionHandle
from polymarket.types import EvmAddress

COLLATERAL_RETURN_TIMEOUT = httpx.Timeout(connect=5.0, read=900.0, write=10.0, pool=2.0)

_PLAN_PATH = "/v1/collateral-return/plan"
_SUBMIT_PATH = "/v1/collateral-return/submit"
_METADATA = "Collateral return"
_DEPOSIT_WALLET_DEADLINE_S = 600
_PROXY_RELAYER_FEE = "0"
_PROXY_GAS_PRICE = "0"
_PROXY_DEFAULT_GAS_LIMIT = "200000"
_SAFE_OPERATION_CALL = 0

_MISSING_API_KEY_MESSAGE = (
    "Collateral return execution requires a Builder API Key or Relayer API Key. "
    "Pass api_key= when constructing the client."
)
_MISSING_APPROVALS_MESSAGE = (
    "The wallet is missing trading approvals required to execute this plan. "
    "Run setup_trading_approvals() and retry."
)


async def plan_collateral_return(ctx: AsyncSecureClientContext) -> CollateralReturnPlan:
    _require_supported_wallet_type(ctx.wallet_type)
    data = await ctx.collateral_return.post_json(_PLAN_PATH, json={"wallet": str(ctx.wallet)})
    return CollateralReturnPlan.parse_response(data)


def plan_collateral_return_sync(ctx: SyncSecureClientContext) -> CollateralReturnPlan:
    _require_supported_wallet_type(ctx.wallet_type)
    data = ctx.collateral_return.post_json(_PLAN_PATH, json={"wallet": str(ctx.wallet)})
    return CollateralReturnPlan.parse_response(data)


async def execute_collateral_return_plan(
    ctx: AsyncSecureClientContext, *, plan: CollateralReturnPlan
) -> GaslessTransactionHandle:
    if ctx.api_key is None:
        raise UserInputError(_MISSING_API_KEY_MESSAGE)
    _require_supported_wallet_type(ctx.wallet_type)
    _require_plan_wallet(plan, wallet=ctx.wallet)

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
            if isinstance(error, RequestRejectedError) and error.status == 409:
                raise CollateralReturnPlanRejectedError(str(error)) from error
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
    _require_plan_wallet(plan, wallet=ctx.wallet)

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
            if isinstance(error, RequestRejectedError) and error.status == 409:
                raise CollateralReturnPlanRejectedError(str(error)) from error
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


def _require_plan_wallet(plan: CollateralReturnPlan, *, wallet: EvmAddress) -> None:
    if str(plan.wallet).lower() != str(wallet).lower():
        raise UserInputError(
            f"Plan wallet {plan.wallet} does not match the authenticated wallet {wallet}"
        )


@dataclass(frozen=True, slots=True)
class _ApprovalCheck:
    call: TransactionCall
    is_satisfied: Callable[[str], bool]


def _build_approval_checks(
    plan: CollateralReturnPlan, *, wallet: EvmAddress, environment: Environment
) -> list[_ApprovalCheck]:
    checks: list[_ApprovalCheck] = []
    if plan.required_positions:
        checks.append(
            _ApprovalCheck(
                call=erc1155_is_approved_for_all_call(
                    token_address=cast(EvmAddress, environment.position_manager),
                    owner=wallet,
                    operator=cast(EvmAddress, environment.protocol_v2_router),
                ),
                is_satisfied=decode_erc1155_is_approved_for_all_result,
            )
        )
    required_collateral_units = int(plan.required_collateral.scaleb(6))
    if required_collateral_units > 0:
        checks.append(
            _ApprovalCheck(
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
            raise MissingTradingApprovalsError(_MISSING_APPROVALS_MESSAGE)


async def _submit_plan(
    ctx: AsyncSecureClientContext, *, plan_hash: str, call: TransactionCall
) -> RelayerExecuteResponse:
    envelope = await _build_envelope(ctx, call=call)
    data = await ctx.collateral_return.post_json(
        _SUBMIT_PATH, json={"plan_hash": plan_hash, "envelope": envelope}
    )
    return RelayerExecuteResponse.parse_response(data)


def _submit_plan_sync(
    ctx: SyncSecureClientContext, *, plan_hash: str, call: TransactionCall
) -> RelayerExecuteResponse:
    envelope = _build_envelope_sync(ctx, call=call)
    data = ctx.collateral_return.post_json(
        _SUBMIT_PATH, json={"plan_hash": plan_hash, "envelope": envelope}
    )
    return RelayerExecuteResponse.parse_response(data)


async def _build_envelope(
    ctx: AsyncSecureClientContext, *, call: TransactionCall
) -> dict[str, object]:
    wallet_type = ctx.wallet_type
    if wallet_type == "DEPOSIT_WALLET":
        params = await fetch_execute_params(
            ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.WALLET
        )
        return _build_deposit_wallet_envelope(ctx, call=call, nonce=params.nonce)
    if wallet_type == "GNOSIS_SAFE":
        params = await fetch_execute_params(
            ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.SAFE
        )
        return _build_safe_envelope(ctx, call=call, nonce=params.nonce)
    if wallet_type == "POLY_PROXY":
        params = await fetch_relay_payload(
            ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.PROXY
        )
        gas_limit = await _estimate_proxy_gas_limit(ctx, call=call)
        return _build_proxy_envelope(
            ctx,
            call=call,
            nonce=params.nonce,
            relay=EvmAddress(params.address),
            gas_limit=gas_limit,
        )
    if wallet_type == "EOA":
        raise UserInputError("EOA wallets are not supported by collateral return")
    assert_never(wallet_type)


def _build_envelope_sync(
    ctx: SyncSecureClientContext, *, call: TransactionCall
) -> dict[str, object]:
    wallet_type = ctx.wallet_type
    if wallet_type == "DEPOSIT_WALLET":
        params = fetch_execute_params_sync(
            ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.WALLET
        )
        return _build_deposit_wallet_envelope(ctx, call=call, nonce=params.nonce)
    if wallet_type == "GNOSIS_SAFE":
        params = fetch_execute_params_sync(
            ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.SAFE
        )
        return _build_safe_envelope(ctx, call=call, nonce=params.nonce)
    if wallet_type == "POLY_PROXY":
        params = fetch_relay_payload_sync(
            ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.PROXY
        )
        gas_limit = _estimate_proxy_gas_limit_sync(ctx, call=call)
        return _build_proxy_envelope(
            ctx,
            call=call,
            nonce=params.nonce,
            relay=EvmAddress(params.address),
            gas_limit=gas_limit,
        )
    if wallet_type == "EOA":
        raise UserInputError("EOA wallets are not supported by collateral return")
    assert_never(wallet_type)


def _build_deposit_wallet_envelope(
    ctx: AsyncSecureClientContext | SyncSecureClientContext,
    *,
    call: TransactionCall,
    nonce: str,
) -> dict[str, object]:
    deadline = str(int(time.time()) + _DEPOSIT_WALLET_DEADLINE_S)
    signature = sign_deposit_wallet_batch(
        ctx.signer,
        wallet=ctx.wallet,
        calls=[call],
        nonce=nonce,
        deadline=deadline,
        chain_id=ctx.environment.chain_id,
    )
    return build_deposit_wallet_payload(
        signer_address=ctx.signer.address,
        deposit_wallet_factory=ctx.environment.wallet_derivation.deposit_wallet_factory,
        wallet=ctx.wallet,
        calls=[call],
        nonce=nonce,
        deadline=deadline,
        signature=signature,
        metadata=_METADATA,
    )


def _build_safe_envelope(
    ctx: AsyncSecureClientContext | SyncSecureClientContext,
    *,
    call: TransactionCall,
    nonce: str,
) -> dict[str, object]:
    signature = sign_safe_transaction(
        ctx.signer,
        safe_address=ctx.wallet,
        to=call.to,
        data=call.data,
        value=call.value,
        operation=_SAFE_OPERATION_CALL,
        nonce=nonce,
        chain_id=ctx.environment.chain_id,
    )
    return build_safe_payload(
        signer_address=ctx.signer.address,
        wallet=ctx.wallet,
        target=call.to,
        data=call.data,
        value=call.value,
        operation=_SAFE_OPERATION_CALL,
        nonce=nonce,
        signature=signature,
        metadata=_METADATA,
    )


def _build_proxy_envelope(
    ctx: AsyncSecureClientContext | SyncSecureClientContext,
    *,
    call: TransactionCall,
    nonce: str,
    relay: EvmAddress,
    gas_limit: str,
) -> dict[str, object]:
    to = ctx.environment.wallet_derivation.proxy_factory
    data = encode_proxy_call([call])
    hash_ = build_proxy_transaction_hash(
        from_address=EvmAddress(ctx.signer.address),
        to=EvmAddress(to),
        data=data,
        relayer_fee=_PROXY_RELAYER_FEE,
        gas_price=_PROXY_GAS_PRICE,
        gas_limit=gas_limit,
        nonce=nonce,
        relay_hub=EvmAddress(ctx.environment.relay_hub),
        relay=relay,
    )
    signature = sign_proxy_message(ctx.signer, hash_)
    return build_proxy_payload(
        signer_address=ctx.signer.address,
        proxy_factory=to,
        wallet=ctx.wallet,
        data=data,
        nonce=nonce,
        signature=signature,
        gas_limit=gas_limit,
        relay=relay,
        relay_hub=ctx.environment.relay_hub,
        metadata=_METADATA,
    )


async def _estimate_proxy_gas_limit(ctx: AsyncSecureClientContext, *, call: TransactionCall) -> str:
    to = ctx.environment.wallet_derivation.proxy_factory
    data = encode_proxy_call([call])
    try:
        estimated = await ctx.rpc.eth_estimate_gas(
            {"from": ctx.signer.address, "to": to, "data": data}
        )
    except Exception:
        return _PROXY_DEFAULT_GAS_LIMIT
    return str(estimated)


def _estimate_proxy_gas_limit_sync(ctx: SyncSecureClientContext, *, call: TransactionCall) -> str:
    to = ctx.environment.wallet_derivation.proxy_factory
    data = encode_proxy_call([call])
    try:
        estimated = ctx.rpc.eth_estimate_gas({"from": ctx.signer.address, "to": to, "data": data})
    except Exception:
        return _PROXY_DEFAULT_GAS_LIMIT
    return str(estimated)


__all__ = [
    "COLLATERAL_RETURN_TIMEOUT",
    "execute_collateral_return_plan",
    "execute_collateral_return_plan_sync",
    "plan_collateral_return",
    "plan_collateral_return_sync",
]
