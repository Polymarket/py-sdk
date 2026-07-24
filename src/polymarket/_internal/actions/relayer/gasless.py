from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import assert_never

from polymarket._internal.actions.relayer.calls import (
    TransactionCall,
    encode_proxy_call,
    encode_safe_multisend_call,
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
    RelayerEnvelope,
    is_retryable_submit_error,
    submit_gasless,
    submit_gasless_sync,
)
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket.errors import UserInputError
from polymarket.models.clob.relayer import (
    RelayerExecuteResponse,
    RelayerTransactionType,
)
from polymarket.transactions import GaslessTransactionHandle, SyncGaslessTransactionHandle
from polymarket.types import EvmAddress, HexString

_DEPOSIT_WALLET_DEADLINE_S = 600
_ZERO_ADDRESS: EvmAddress = EvmAddress("0x0000000000000000000000000000000000000000")
_PROXY_RELAYER_FEE = "0"
_PROXY_GAS_PRICE = "0"
_PROXY_DEFAULT_GAS_LIMIT = "200000"
_SAFE_OPERATION_CALL = 0
_SAFE_OPERATION_DELEGATECALL = 1
_METADATA_MAX_LENGTH = 500


async def prepare_gasless_transaction(
    ctx: AsyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str = "",
) -> GaslessTransactionHandle:
    if ctx.api_key is None:
        raise UserInputError(
            "Gasless transactions require a Builder API Key or Relayer API Key. "
            "Pass api_key= when constructing the client."
        )
    if ctx.wallet_type == "EOA":
        raise UserInputError(
            "EOA wallets do not use the relayer in this SDK version. "
            "Direct EOA broadcasting is planned but not yet supported."
        )
    if not calls:
        raise UserInputError("prepare_gasless_transaction requires at least one call")
    if len(metadata) > _METADATA_MAX_LENGTH:
        raise UserInputError(f"metadata must be at most {_METADATA_MAX_LENGTH} characters")

    return await submit_gasless_with_retry(
        ctx, submit=lambda: _submit_for_wallet_type(ctx, calls=calls, metadata=metadata)
    )


async def submit_gasless_with_retry(
    ctx: AsyncSecureClientContext,
    *,
    submit: Callable[[], Awaitable[RelayerExecuteResponse]],
) -> GaslessTransactionHandle:
    """Run a gasless submit, retrying transient relayer rejections."""
    env = ctx.environment
    poll_delay_s = env.relayer_poll_frequency_ms / 1000
    for attempt in range(GASLESS_SUBMIT_RETRY_ATTEMPTS + 1):
        try:
            response = await submit()
        except Exception as error:
            if attempt == GASLESS_SUBMIT_RETRY_ATTEMPTS or not is_retryable_submit_error(error):
                raise
            await asyncio.sleep(poll_delay_s)
        else:
            return GaslessTransactionHandle(
                transaction_id=response.transaction_id,
                transaction_hash=response.transaction_hash,
                _relayer=ctx.relayer,
                _max_polls=env.relayer_max_polls,
                _poll_delay_s=poll_delay_s,
            )
    raise AssertionError("unreachable")


async def _submit_for_wallet_type(
    ctx: AsyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerExecuteResponse:
    payload = await build_signed_payload_for_wallet_type(ctx, calls=calls, metadata=metadata)
    return await submit_gasless(ctx.relayer, payload=payload)


async def build_signed_payload_for_wallet_type(
    ctx: AsyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerEnvelope:
    """Fetch a fresh nonce, sign, and build the relayer payload for the wallet type."""
    wallet_type = ctx.wallet_type
    if wallet_type == "DEPOSIT_WALLET":
        return await build_signed_deposit_wallet_payload(ctx, calls=calls, metadata=metadata)
    if wallet_type == "POLY_PROXY":
        return await build_signed_proxy_payload(ctx, calls=calls, metadata=metadata)
    if wallet_type == "GNOSIS_SAFE":
        return await build_signed_safe_payload(ctx, calls=calls, metadata=metadata)
    if wallet_type == "EOA":
        raise UserInputError("EOA wallets are not supported by the relayer in this SDK version")
    assert_never(wallet_type)


async def build_signed_deposit_wallet_payload(
    ctx: AsyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerEnvelope:
    params = await fetch_execute_params(
        ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.WALLET
    )
    deadline = str(int(time.time()) + _DEPOSIT_WALLET_DEADLINE_S)
    signature = sign_deposit_wallet_batch(
        ctx.signer,
        wallet=ctx.wallet,
        calls=calls,
        nonce=params.nonce,
        deadline=deadline,
        chain_id=ctx.environment.chain_id,
    )
    return build_deposit_wallet_payload(
        signer_address=ctx.signer.address,
        deposit_wallet_factory=ctx.environment.wallet_derivation.deposit_wallet_factory,
        wallet=ctx.wallet,
        calls=calls,
        nonce=params.nonce,
        deadline=deadline,
        signature=signature,
        metadata=metadata,
    )


def build_deposit_wallet_payload(
    *,
    signer_address: str,
    deposit_wallet_factory: str,
    wallet: EvmAddress,
    calls: list[TransactionCall],
    nonce: str,
    deadline: str,
    signature: str,
    metadata: str,
) -> RelayerEnvelope:
    return RelayerEnvelope(
        {
            "type": RelayerTransactionType.WALLET.value,
            "from": signer_address,
            "to": deposit_wallet_factory,
            "nonce": nonce,
            "signature": signature,
            "metadata": metadata,
            "depositWalletParams": {
                "depositWallet": str(wallet),
                "deadline": deadline,
                "calls": [
                    {"target": str(c.to), "value": str(c.value), "data": c.data} for c in calls
                ],
            },
        }
    )


async def build_signed_proxy_payload(
    ctx: AsyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerEnvelope:
    params = await fetch_relay_payload(
        ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.PROXY
    )
    to = ctx.environment.wallet_derivation.proxy_factory
    data = encode_proxy_call(calls)
    relay = EvmAddress(params.address)
    gas_limit = await _estimate_proxy_gas_limit(
        ctx, from_address=ctx.signer.address, to=to, data=data
    )
    hash_ = build_proxy_transaction_hash(
        from_address=EvmAddress(ctx.signer.address),
        to=EvmAddress(to),
        data=data,
        relayer_fee=_PROXY_RELAYER_FEE,
        gas_price=_PROXY_GAS_PRICE,
        gas_limit=gas_limit,
        nonce=params.nonce,
        relay_hub=EvmAddress(ctx.environment.relay_hub),
        relay=relay,
    )
    signature = sign_proxy_message(ctx.signer, hash_)
    return build_proxy_payload(
        signer_address=ctx.signer.address,
        proxy_factory=to,
        wallet=ctx.wallet,
        data=data,
        nonce=params.nonce,
        signature=signature,
        gas_limit=gas_limit,
        relay=relay,
        relay_hub=ctx.environment.relay_hub,
        metadata=metadata,
    )


def build_proxy_payload(
    *,
    signer_address: str,
    proxy_factory: str,
    wallet: EvmAddress,
    data: HexString,
    nonce: str,
    signature: str,
    gas_limit: str,
    relay: EvmAddress,
    relay_hub: str,
    metadata: str,
) -> RelayerEnvelope:
    return RelayerEnvelope(
        {
            "type": RelayerTransactionType.PROXY.value,
            "from": signer_address,
            "to": proxy_factory,
            "proxyWallet": str(wallet),
            "data": data,
            "nonce": nonce,
            "signature": signature,
            "metadata": metadata,
            "signatureParams": {
                "gasLimit": gas_limit,
                "gasPrice": _PROXY_GAS_PRICE,
                "relay": str(relay),
                "relayHub": relay_hub,
                "relayerFee": _PROXY_RELAYER_FEE,
            },
        }
    )


async def _estimate_proxy_gas_limit(
    ctx: AsyncSecureClientContext,
    *,
    from_address: str,
    to: str,
    data: str,
) -> str:
    try:
        estimated = await ctx.rpc.eth_estimate_gas({"from": from_address, "to": to, "data": data})
    except Exception:
        return _PROXY_DEFAULT_GAS_LIMIT
    return str(estimated)


async def build_signed_safe_payload(
    ctx: AsyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerEnvelope:
    params = await fetch_execute_params(
        ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.SAFE
    )
    target, data, value, operation = _resolve_safe_call(ctx.environment.safe_multisend, calls)
    signature = sign_safe_transaction(
        ctx.signer,
        safe_address=ctx.wallet,
        to=target,
        data=data,
        value=value,
        operation=operation,
        nonce=params.nonce,
        chain_id=ctx.environment.chain_id,
    )
    return build_safe_payload(
        signer_address=ctx.signer.address,
        wallet=ctx.wallet,
        target=target,
        data=data,
        value=value,
        operation=operation,
        nonce=params.nonce,
        signature=signature,
        metadata=metadata,
    )


def _resolve_safe_call(
    safe_multisend: str, calls: list[TransactionCall]
) -> tuple[EvmAddress, HexString, int, int]:
    if len(calls) == 1:
        return calls[0].to, calls[0].data, calls[0].value, _SAFE_OPERATION_CALL
    return (
        EvmAddress(safe_multisend),
        encode_safe_multisend_call(calls),
        0,
        _SAFE_OPERATION_DELEGATECALL,
    )


def build_safe_payload(
    *,
    signer_address: str,
    wallet: EvmAddress,
    target: EvmAddress,
    data: HexString,
    value: int,
    operation: int,
    nonce: str,
    signature: str,
    metadata: str,
) -> RelayerEnvelope:
    payload: dict[str, object] = {
        "type": RelayerTransactionType.SAFE.value,
        "from": signer_address,
        "to": str(target),
        "proxyWallet": str(wallet),
        "data": data,
        "nonce": nonce,
        "signature": signature,
        "metadata": metadata,
        "signatureParams": {
            "baseGas": "0",
            "gasPrice": "0",
            "gasToken": str(_ZERO_ADDRESS),
            "operation": str(operation),
            "refundReceiver": str(_ZERO_ADDRESS),
            "safeTxnGas": "0",
        },
    }
    if value > 0:
        payload["value"] = str(value)
    return RelayerEnvelope(payload)


async def submit_deposit_wallet_create(
    ctx: AsyncSecureClientContext,
    *,
    metadata: str = "",
) -> GaslessTransactionHandle:
    if ctx.api_key is None:
        raise UserInputError(
            "Gasless transactions require a Builder API Key or Relayer API Key. "
            "Pass api_key= when constructing the client."
        )
    if len(metadata) > _METADATA_MAX_LENGTH:
        raise UserInputError(f"metadata must be at most {_METADATA_MAX_LENGTH} characters")
    payload = RelayerEnvelope(
        {
            "type": RelayerTransactionType.WALLET_CREATE.value,
            "from": ctx.signer.address,
            "to": ctx.environment.wallet_derivation.deposit_wallet_factory,
            "metadata": metadata,
        }
    )
    response = await submit_gasless(ctx.relayer, payload=payload)
    env = ctx.environment
    return GaslessTransactionHandle(
        transaction_id=response.transaction_id,
        transaction_hash=response.transaction_hash,
        _relayer=ctx.relayer,
        _max_polls=env.relayer_max_polls,
        _poll_delay_s=env.relayer_poll_frequency_ms / 1000,
    )


def prepare_gasless_transaction_sync(
    ctx: SyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str = "",
) -> SyncGaslessTransactionHandle:
    if ctx.api_key is None:
        raise UserInputError(
            "Gasless transactions require a Builder API Key or Relayer API Key. "
            "Pass api_key= when constructing the client."
        )
    if ctx.wallet_type == "EOA":
        raise UserInputError(
            "EOA wallets do not use the relayer in this SDK version. "
            "Direct EOA broadcasting is planned but not yet supported."
        )
    if not calls:
        raise UserInputError("prepare_gasless_transaction requires at least one call")
    if len(metadata) > _METADATA_MAX_LENGTH:
        raise UserInputError(f"metadata must be at most {_METADATA_MAX_LENGTH} characters")

    return submit_gasless_with_retry_sync(
        ctx, submit=lambda: _submit_for_wallet_type_sync(ctx, calls=calls, metadata=metadata)
    )


def submit_gasless_with_retry_sync(
    ctx: SyncSecureClientContext,
    *,
    submit: Callable[[], RelayerExecuteResponse],
) -> SyncGaslessTransactionHandle:
    """Run a gasless submit, retrying transient relayer rejections."""
    env = ctx.environment
    poll_delay_s = env.relayer_poll_frequency_ms / 1000
    for attempt in range(GASLESS_SUBMIT_RETRY_ATTEMPTS + 1):
        try:
            response = submit()
        except Exception as error:
            if attempt == GASLESS_SUBMIT_RETRY_ATTEMPTS or not is_retryable_submit_error(error):
                raise
            time.sleep(poll_delay_s)
        else:
            return SyncGaslessTransactionHandle(
                transaction_id=response.transaction_id,
                transaction_hash=response.transaction_hash,
                _relayer=ctx.relayer,
                _max_polls=env.relayer_max_polls,
                _poll_delay_s=poll_delay_s,
            )
    raise AssertionError("unreachable")


def _submit_for_wallet_type_sync(
    ctx: SyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerExecuteResponse:
    payload = build_signed_payload_for_wallet_type_sync(ctx, calls=calls, metadata=metadata)
    return submit_gasless_sync(ctx.relayer, payload=payload)


def build_signed_payload_for_wallet_type_sync(
    ctx: SyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerEnvelope:
    """Fetch a fresh nonce, sign, and build the relayer payload for the wallet type."""
    wallet_type = ctx.wallet_type
    if wallet_type == "DEPOSIT_WALLET":
        return build_signed_deposit_wallet_payload_sync(ctx, calls=calls, metadata=metadata)
    if wallet_type == "POLY_PROXY":
        return build_signed_proxy_payload_sync(ctx, calls=calls, metadata=metadata)
    if wallet_type == "GNOSIS_SAFE":
        return build_signed_safe_payload_sync(ctx, calls=calls, metadata=metadata)
    if wallet_type == "EOA":
        raise UserInputError("EOA wallets are not supported by the relayer in this SDK version")
    assert_never(wallet_type)


def build_signed_deposit_wallet_payload_sync(
    ctx: SyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerEnvelope:
    params = fetch_execute_params_sync(
        ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.WALLET
    )
    deadline = str(int(time.time()) + _DEPOSIT_WALLET_DEADLINE_S)
    signature = sign_deposit_wallet_batch(
        ctx.signer,
        wallet=ctx.wallet,
        calls=calls,
        nonce=params.nonce,
        deadline=deadline,
        chain_id=ctx.environment.chain_id,
    )
    return build_deposit_wallet_payload(
        signer_address=ctx.signer.address,
        deposit_wallet_factory=ctx.environment.wallet_derivation.deposit_wallet_factory,
        wallet=ctx.wallet,
        calls=calls,
        nonce=params.nonce,
        deadline=deadline,
        signature=signature,
        metadata=metadata,
    )


def build_signed_proxy_payload_sync(
    ctx: SyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerEnvelope:
    params = fetch_relay_payload_sync(
        ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.PROXY
    )
    to = ctx.environment.wallet_derivation.proxy_factory
    data = encode_proxy_call(calls)
    relay = EvmAddress(params.address)
    gas_limit = _estimate_proxy_gas_limit_sync(
        ctx, from_address=ctx.signer.address, to=to, data=data
    )
    hash_ = build_proxy_transaction_hash(
        from_address=EvmAddress(ctx.signer.address),
        to=EvmAddress(to),
        data=data,
        relayer_fee=_PROXY_RELAYER_FEE,
        gas_price=_PROXY_GAS_PRICE,
        gas_limit=gas_limit,
        nonce=params.nonce,
        relay_hub=EvmAddress(ctx.environment.relay_hub),
        relay=relay,
    )
    signature = sign_proxy_message(ctx.signer, hash_)
    return build_proxy_payload(
        signer_address=ctx.signer.address,
        proxy_factory=to,
        wallet=ctx.wallet,
        data=data,
        nonce=params.nonce,
        signature=signature,
        gas_limit=gas_limit,
        relay=relay,
        relay_hub=ctx.environment.relay_hub,
        metadata=metadata,
    )


def _estimate_proxy_gas_limit_sync(
    ctx: SyncSecureClientContext,
    *,
    from_address: str,
    to: str,
    data: str,
) -> str:
    try:
        estimated = ctx.rpc.eth_estimate_gas({"from": from_address, "to": to, "data": data})
    except Exception:
        return _PROXY_DEFAULT_GAS_LIMIT
    return str(estimated)


def build_signed_safe_payload_sync(
    ctx: SyncSecureClientContext,
    *,
    calls: list[TransactionCall],
    metadata: str,
) -> RelayerEnvelope:
    params = fetch_execute_params_sync(
        ctx.relayer, address=ctx.signer.address, type=RelayerTransactionType.SAFE
    )
    target, data, value, operation = _resolve_safe_call(ctx.environment.safe_multisend, calls)
    signature = sign_safe_transaction(
        ctx.signer,
        safe_address=ctx.wallet,
        to=target,
        data=data,
        value=value,
        operation=operation,
        nonce=params.nonce,
        chain_id=ctx.environment.chain_id,
    )
    return build_safe_payload(
        signer_address=ctx.signer.address,
        wallet=ctx.wallet,
        target=target,
        data=data,
        value=value,
        operation=operation,
        nonce=params.nonce,
        signature=signature,
        metadata=metadata,
    )


def submit_deposit_wallet_create_sync(
    ctx: SyncSecureClientContext,
    *,
    metadata: str = "",
) -> SyncGaslessTransactionHandle:
    if ctx.api_key is None:
        raise UserInputError(
            "Gasless transactions require a Builder API Key or Relayer API Key. "
            "Pass api_key= when constructing the client."
        )
    if len(metadata) > _METADATA_MAX_LENGTH:
        raise UserInputError(f"metadata must be at most {_METADATA_MAX_LENGTH} characters")
    payload = RelayerEnvelope(
        {
            "type": RelayerTransactionType.WALLET_CREATE.value,
            "from": ctx.signer.address,
            "to": ctx.environment.wallet_derivation.deposit_wallet_factory,
            "metadata": metadata,
        }
    )
    response = submit_gasless_sync(ctx.relayer, payload=payload)
    env = ctx.environment
    return SyncGaslessTransactionHandle(
        transaction_id=response.transaction_id,
        transaction_hash=response.transaction_hash,
        _relayer=ctx.relayer,
        _max_polls=env.relayer_max_polls,
        _poll_delay_s=env.relayer_poll_frequency_ms / 1000,
    )


__all__ = [
    "build_deposit_wallet_payload",
    "build_proxy_payload",
    "build_safe_payload",
    "build_signed_deposit_wallet_payload",
    "build_signed_deposit_wallet_payload_sync",
    "build_signed_payload_for_wallet_type",
    "build_signed_payload_for_wallet_type_sync",
    "build_signed_proxy_payload",
    "build_signed_proxy_payload_sync",
    "build_signed_safe_payload",
    "build_signed_safe_payload_sync",
    "prepare_gasless_transaction",
    "prepare_gasless_transaction_sync",
    "submit_deposit_wallet_create",
    "submit_deposit_wallet_create_sync",
    "submit_gasless_with_retry",
    "submit_gasless_with_retry_sync",
]
