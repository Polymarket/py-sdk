from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from eth_utils.address import to_checksum_address
from pydantic import Field, field_validator

from polymarket._internal.actions.relayer.calls import authorize_session_signer_call
from polymarket._internal.actions.relayer.gasless import (
    SignedDepositWalletBatch,
    build_signed_deposit_wallet_batch,
    build_signed_deposit_wallet_batch_sync,
)
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.wallet import is_deposit_wallet_owner
from polymarket.errors import UserInputError
from polymarket.models.base import BaseModel
from polymarket.models.clob.relayer import TransactionOutcome
from polymarket.session_keys import (
    AuthorizedSessionKey,
    AuthorizeSessionKeyResult,
    SessionKeyKnownScope,
    SessionKeyScope,
)
from polymarket.transactions import GaslessTransactionHandle, SyncGaslessTransactionHandle
from polymarket.types import EvmAddress, TransactionHash

_AUTHORIZATIONS_PATH = "/v1/session-signers/authorizations"
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_TRANSACTION_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")

_SecureContext = AsyncSecureClientContext | SyncSecureClientContext


class _AuthorizeSessionKeyResponse(BaseModel):
    operation_id: str = Field(validation_alias="operationId", min_length=1)
    status: str = Field(min_length=1)
    transaction_hash: TransactionHash | None = Field(
        default=None, validation_alias="transactionHash"
    )
    transaction_id: str = Field(validation_alias="transactionId", min_length=1)

    @field_validator("transaction_hash", mode="before")
    @classmethod
    def _validate_transaction_hash(cls, value: object) -> object:
        if value in (None, ""):
            return None
        if not isinstance(value, str) or _TRANSACTION_HASH_RE.fullmatch(value) is None:
            raise ValueError("invalid transaction hash")
        return value


@dataclass(frozen=True, slots=True)
class _ParsedAuthorizeSessionKeyRequest:
    address: EvmAddress
    scopes: tuple[SessionKeyScope, ...]
    valid_until: datetime
    valid_until_epoch: int
    idempotency_key: str


async def authorize_session_key(
    ctx: AsyncSecureClientContext,
    *,
    address: str,
    scopes: Sequence[SessionKeyScope],
    valid_until: datetime,
    idempotency_key: str | None,
) -> AuthorizeSessionKeyResult:
    _assert_owner_deposit_wallet(ctx)
    _require_api_key(ctx)
    request = _parse_authorize_session_key_request(
        ctx,
        address=address,
        scopes=scopes,
        valid_until=valid_until,
        idempotency_key=idempotency_key,
    )
    call = authorize_session_signer_call(
        wallet_address=ctx.wallet,
        session_signer=request.address,
        valid_until=request.valid_until_epoch,
    )
    batch = await build_signed_deposit_wallet_batch(ctx, calls=[call])
    response = _AuthorizeSessionKeyResponse.parse_response(
        await ctx.relayer.post_json(
            _AUTHORIZATIONS_PATH,
            json=_build_authorization_payload(ctx, request=request, batch=batch),
            headers={"Idempotency-Key": request.idempotency_key},
        )
    )

    # TODO(TRA-354): Session-key listing is still pending; poll it for authoritative
    # readiness once available.
    transaction = await GaslessTransactionHandle(
        transaction_id=response.transaction_id,
        transaction_hash=response.transaction_hash,
        _relayer=ctx.relayer,
        _max_polls=ctx.environment_config.relayer_max_polls,
        _poll_delay_s=ctx.environment_config.relayer_poll_frequency_ms / 1000,
    ).wait()
    return _build_authorization_result(request=request, response=response, transaction=transaction)


def authorize_session_key_sync(
    ctx: SyncSecureClientContext,
    *,
    address: str,
    scopes: Sequence[SessionKeyScope],
    valid_until: datetime,
    idempotency_key: str | None,
) -> AuthorizeSessionKeyResult:
    _assert_owner_deposit_wallet(ctx)
    _require_api_key(ctx)
    request = _parse_authorize_session_key_request(
        ctx,
        address=address,
        scopes=scopes,
        valid_until=valid_until,
        idempotency_key=idempotency_key,
    )
    call = authorize_session_signer_call(
        wallet_address=ctx.wallet,
        session_signer=request.address,
        valid_until=request.valid_until_epoch,
    )
    batch = build_signed_deposit_wallet_batch_sync(ctx, calls=[call])
    response = _AuthorizeSessionKeyResponse.parse_response(
        ctx.relayer.post_json(
            _AUTHORIZATIONS_PATH,
            json=_build_authorization_payload(ctx, request=request, batch=batch),
            headers={"Idempotency-Key": request.idempotency_key},
        )
    )

    # TODO(TRA-354): Session-key listing is still pending; poll it for authoritative
    # readiness once available.
    transaction = SyncGaslessTransactionHandle(
        transaction_id=response.transaction_id,
        transaction_hash=response.transaction_hash,
        _relayer=ctx.relayer,
        _max_polls=ctx.environment_config.relayer_max_polls,
        _poll_delay_s=ctx.environment_config.relayer_poll_frequency_ms / 1000,
    ).wait()
    return _build_authorization_result(request=request, response=response, transaction=transaction)


def _parse_authorize_session_key_request(
    ctx: _SecureContext,
    *,
    address: object,
    scopes: object,
    valid_until: object,
    idempotency_key: object,
) -> _ParsedAuthorizeSessionKeyRequest:
    session_address = _parse_session_address(address, wallet=ctx.wallet)
    normalized_scopes = _parse_scopes(scopes)
    normalized_expiry = _parse_valid_until(valid_until)
    return _ParsedAuthorizeSessionKeyRequest(
        address=session_address,
        scopes=normalized_scopes,
        valid_until=normalized_expiry,
        valid_until_epoch=int(normalized_expiry.timestamp()),
        idempotency_key=_parse_idempotency_key(idempotency_key),
    )


def _parse_session_address(address: object, *, wallet: EvmAddress) -> EvmAddress:
    if not isinstance(address, str) or _EVM_ADDRESS_RE.fullmatch(address) is None:
        raise UserInputError("Session key address must be a valid EVM address.")
    try:
        normalized = to_checksum_address(address)
    except (TypeError, ValueError) as error:
        raise UserInputError("Session key address must be a valid EVM address.") from error
    if normalized.lower() == _ZERO_ADDRESS:
        raise UserInputError("Session key address must not be the zero address.")
    if normalized.lower() == str(wallet).lower():
        raise UserInputError("Session key address must differ from the Deposit Wallet.")
    return EvmAddress(normalized)


def _parse_scopes(scopes: object) -> tuple[SessionKeyScope, ...]:
    if isinstance(scopes, str | bytes) or not isinstance(scopes, Sequence):
        raise UserInputError("Session key scopes must be a non-empty sequence.")
    if not scopes:
        raise UserInputError("Session key scopes must be a non-empty sequence.")
    scope_values: dict[str, None] = {}
    for scope in cast(Sequence[object], scopes):
        if not isinstance(scope, str) or not scope:
            raise UserInputError("Session key scopes must contain non-empty strings.")
        scope_values.setdefault(scope, None)

    known_values = {scope.value for scope in SessionKeyKnownScope}
    normalized: list[SessionKeyScope] = [
        scope for scope in SessionKeyKnownScope if scope.value in scope_values
    ]
    normalized.extend(scope for scope in scope_values if scope not in known_values)
    if SessionKeyKnownScope.ALL in normalized and len(normalized) > 1:
        raise UserInputError("Session key scope ALL cannot be combined with another scope.")
    return tuple(normalized)


def _parse_valid_until(valid_until: object) -> datetime:
    if not isinstance(valid_until, datetime):
        raise UserInputError("Session key expiry must be a timezone-aware datetime.")
    if valid_until.tzinfo is None or valid_until.utcoffset() is None:
        raise UserInputError("Session key expiry must be a timezone-aware datetime.")
    normalized = valid_until.astimezone(UTC).replace(microsecond=0)
    if int(normalized.timestamp()) <= int(time.time()):
        raise UserInputError("Session key expiry must be in the future.")
    return normalized


def _parse_idempotency_key(idempotency_key: object) -> str:
    if idempotency_key is None:
        return str(uuid4())
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise UserInputError("idempotency_key must be a non-empty string.")
    return idempotency_key.strip()


def _assert_owner_deposit_wallet(ctx: _SecureContext) -> None:
    if ctx.wallet_type != "DEPOSIT_WALLET":
        raise UserInputError("Session keys can only be authorized for a Deposit Wallet.")
    if not is_deposit_wallet_owner(
        signer=ctx.signer.address,
        wallet=str(ctx.wallet),
        wallet_type=ctx.wallet_type,
        config=ctx.environment_config.wallet_derivation,
    ):
        raise UserInputError("Session keys can only be authorized by the Deposit Wallet owner.")


def _require_api_key(ctx: _SecureContext) -> None:
    if ctx.api_key is None:
        raise UserInputError(
            "Session-key authorization requires a Builder API Key or Relayer API Key. "
            "Pass api_key= when constructing the client."
        )


def _build_authorization_payload(
    ctx: _SecureContext,
    *,
    request: _ParsedAuthorizeSessionKeyRequest,
    batch: SignedDepositWalletBatch,
) -> dict[str, object]:
    return {
        "deadline": batch.deadline,
        "nonce": batch.nonce,
        "scopes": [str(scope) for scope in request.scopes],
        "sessionSignerAddress": str(request.address),
        "signature": batch.signature,
        "validUntil": str(request.valid_until_epoch),
        "walletAddress": str(ctx.wallet),
    }


def _build_authorization_result(
    *,
    request: _ParsedAuthorizeSessionKeyRequest,
    response: _AuthorizeSessionKeyResponse,
    transaction: TransactionOutcome,
) -> AuthorizeSessionKeyResult:
    return AuthorizeSessionKeyResult(
        operation_id=response.operation_id,
        session_key=AuthorizedSessionKey(
            address=request.address,
            scopes=request.scopes,
            valid_until=request.valid_until,
        ),
        transaction=transaction,
    )


__all__ = ["authorize_session_key", "authorize_session_key_sync"]
