from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar, cast
from uuid import uuid4

from eth_utils.address import to_checksum_address
from pydantic import Field, StrictBool, field_validator

from polymarket._internal.actions.relayer.calls import (
    authorize_session_signer_call,
    revoke_session_signer_call,
)
from polymarket._internal.actions.relayer.gasless import (
    SignedDepositWalletBatch,
    build_signed_deposit_wallet_batch,
    build_signed_deposit_wallet_batch_sync,
)
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket.auth import BuilderApiKey
from polymarket.errors import (
    RateLimitError,
    RequestRejectedError,
    TimeoutError,
    TransactionFailedError,
    TransportError,
    UnexpectedResponseError,
    UserInputError,
)
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
_REVOCATIONS_PATH = "/v1/session-signers/revocations"
_SESSION_KEYS_PATH = "/v1/user/session-signers"
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_TRANSACTION_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_SESSION_KEY_SUBMISSION_MAX_RETRIES = 2
_SESSION_KEY_LIFETIME_SECONDS = 4_315 * 60 * 60

_SecureContext = AsyncSecureClientContext | SyncSecureClientContext
_ResponseT = TypeVar("_ResponseT")


class _AuthorizeSessionSignerStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    REGISTRY_PENDING = "REGISTRY_PENDING"
    REGISTERED = "REGISTERED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"


class _RevokeSessionSignerStatus(StrEnum):
    PENDING = "PENDING"
    FENCED = "FENCED"
    SWEPT = "SWEPT"
    CHAIN_SUBMITTED = "CHAIN_SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class _AuthorizeSessionKeyResponse(BaseModel):
    status: _AuthorizeSessionSignerStatus
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


class _SessionKeyResponse(BaseModel):
    address: EvmAddress
    scopes: tuple[str, ...]
    valid_until: datetime

    @field_validator("address", mode="before")
    @classmethod
    def _normalize_address(cls, value: object) -> EvmAddress:
        return _normalize_response_address(value)

    @field_validator("scopes", mode="before")
    @classmethod
    def _validate_scopes(cls, value: object) -> object:
        if not isinstance(value, list) or not value:
            raise ValueError("session key scopes must be a non-empty array")
        scopes = cast(list[object], value)
        if any(not isinstance(scope, str) or not scope for scope in scopes):
            raise ValueError("session key scopes must contain non-empty strings")
        return scopes

    @field_validator("valid_until", mode="before")
    @classmethod
    def _normalize_valid_until(cls, value: object) -> datetime:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("session key expiry must be non-negative Unix seconds")
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OSError, OverflowError, ValueError) as error:
            raise ValueError("session key expiry is outside the supported range") from error


class _FetchSessionKeysResponse(BaseModel):
    signers: tuple[_SessionKeyResponse, ...]
    wallet: EvmAddress

    @field_validator("signers", mode="before")
    @classmethod
    def _validate_signers(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("session keys must be an array")
        return cast(list[object], value)

    @field_validator("wallet", mode="before")
    @classmethod
    def _normalize_wallet(cls, value: object) -> EvmAddress:
        return _normalize_response_address(value)


class _RevokeSessionKeyResponse(BaseModel):
    status: _RevokeSessionSignerStatus
    fenced: StrictBool
    transaction_id: str = Field(validation_alias="transactionId", min_length=1)


@dataclass(frozen=True, slots=True)
class _ParsedAuthorizeSessionKeyRequest:
    address: EvmAddress
    scopes: tuple[SessionKeyScope, ...]
    valid_until: datetime
    valid_until_epoch: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class _ParsedRevokeSessionKeyRequest:
    address: EvmAddress
    idempotency_key: str


async def fetch_session_keys(
    ctx: AsyncSecureClientContext,
) -> tuple[AuthorizedSessionKey, ...]:
    _assert_owner_deposit_wallet(ctx)
    response = _FetchSessionKeysResponse.parse_response(
        await ctx.secure_clob.get_json(_SESSION_KEYS_PATH)
    )
    return _build_session_keys(ctx, response=response)


def fetch_session_keys_sync(
    ctx: SyncSecureClientContext,
) -> tuple[AuthorizedSessionKey, ...]:
    _assert_owner_deposit_wallet(ctx)
    response = _FetchSessionKeysResponse.parse_response(
        ctx.secure_clob.get_json(_SESSION_KEYS_PATH)
    )
    return _build_session_keys(ctx, response=response)


async def authorize_session_key(
    ctx: AsyncSecureClientContext,
    *,
    address: str,
    scopes: Sequence[SessionKeyScope],
    idempotency_key: str | None,
) -> AuthorizeSessionKeyResult:
    _assert_owner_deposit_wallet(ctx)
    _require_builder_api_key(ctx)
    request = _parse_authorize_session_key_request(
        address=address,
        scopes=scopes,
        idempotency_key=idempotency_key,
    )
    call = authorize_session_signer_call(
        wallet_address=ctx.wallet,
        session_signer=request.address,
        valid_until=request.valid_until_epoch,
    )
    batch = await build_signed_deposit_wallet_batch(ctx, calls=[call])
    payload = _build_authorization_payload(ctx, request=request, batch=batch)
    response = await _post_session_key_operation(
        ctx,
        path=_AUTHORIZATIONS_PATH,
        payload=payload,
        idempotency_key=request.idempotency_key,
        parse=_AuthorizeSessionKeyResponse.parse_response,
    )
    _assert_authorization_accepted(response.status)

    transaction = await GaslessTransactionHandle(
        transaction_id=response.transaction_id,
        transaction_hash=response.transaction_hash,
        _relayer=ctx.relayer,
        _max_polls=ctx.environment_config.relayer_max_polls,
        _poll_delay_s=ctx.environment_config.relayer_poll_frequency_ms / 1000,
    ).wait()
    session_key = await _wait_for_authorized_session_key(ctx, expected=request)
    return _build_authorization_result(
        session_key=session_key,
        transaction=transaction,
    )


def authorize_session_key_sync(
    ctx: SyncSecureClientContext,
    *,
    address: str,
    scopes: Sequence[SessionKeyScope],
    idempotency_key: str | None,
) -> AuthorizeSessionKeyResult:
    _assert_owner_deposit_wallet(ctx)
    _require_builder_api_key(ctx)
    request = _parse_authorize_session_key_request(
        address=address,
        scopes=scopes,
        idempotency_key=idempotency_key,
    )
    call = authorize_session_signer_call(
        wallet_address=ctx.wallet,
        session_signer=request.address,
        valid_until=request.valid_until_epoch,
    )
    batch = build_signed_deposit_wallet_batch_sync(ctx, calls=[call])
    payload = _build_authorization_payload(ctx, request=request, batch=batch)
    response = _post_session_key_operation_sync(
        ctx,
        path=_AUTHORIZATIONS_PATH,
        payload=payload,
        idempotency_key=request.idempotency_key,
        parse=_AuthorizeSessionKeyResponse.parse_response,
    )
    _assert_authorization_accepted(response.status)

    transaction = SyncGaslessTransactionHandle(
        transaction_id=response.transaction_id,
        transaction_hash=response.transaction_hash,
        _relayer=ctx.relayer,
        _max_polls=ctx.environment_config.relayer_max_polls,
        _poll_delay_s=ctx.environment_config.relayer_poll_frequency_ms / 1000,
    ).wait()
    session_key = _wait_for_authorized_session_key_sync(ctx, expected=request)
    return _build_authorization_result(
        session_key=session_key,
        transaction=transaction,
    )


async def revoke_session_key(
    ctx: AsyncSecureClientContext,
    *,
    address: str,
    idempotency_key: str | None,
) -> TransactionOutcome:
    _assert_owner_deposit_wallet(ctx)
    _require_gasless_api_key(ctx)
    request = _parse_revoke_session_key_request(
        address=address,
        idempotency_key=idempotency_key,
    )
    call = revoke_session_signer_call(
        wallet_address=ctx.wallet,
        session_signer=request.address,
    )
    batch = await build_signed_deposit_wallet_batch(ctx, calls=[call])
    payload = _build_revocation_payload(ctx, request=request, batch=batch)
    response = await _post_session_key_operation(
        ctx,
        path=_REVOCATIONS_PATH,
        payload=payload,
        idempotency_key=request.idempotency_key,
        parse=_RevokeSessionKeyResponse.parse_response,
    )
    _assert_revocation_accepted(response.status)
    return await GaslessTransactionHandle(
        transaction_id=response.transaction_id,
        transaction_hash=None,
        _relayer=ctx.relayer,
        _max_polls=ctx.environment_config.relayer_max_polls,
        _poll_delay_s=ctx.environment_config.relayer_poll_frequency_ms / 1000,
    ).wait()


def revoke_session_key_sync(
    ctx: SyncSecureClientContext,
    *,
    address: str,
    idempotency_key: str | None,
) -> TransactionOutcome:
    _assert_owner_deposit_wallet(ctx)
    _require_gasless_api_key(ctx)
    request = _parse_revoke_session_key_request(
        address=address,
        idempotency_key=idempotency_key,
    )
    call = revoke_session_signer_call(
        wallet_address=ctx.wallet,
        session_signer=request.address,
    )
    batch = build_signed_deposit_wallet_batch_sync(ctx, calls=[call])
    payload = _build_revocation_payload(ctx, request=request, batch=batch)
    response = _post_session_key_operation_sync(
        ctx,
        path=_REVOCATIONS_PATH,
        payload=payload,
        idempotency_key=request.idempotency_key,
        parse=_RevokeSessionKeyResponse.parse_response,
    )
    _assert_revocation_accepted(response.status)
    return SyncGaslessTransactionHandle(
        transaction_id=response.transaction_id,
        transaction_hash=None,
        _relayer=ctx.relayer,
        _max_polls=ctx.environment_config.relayer_max_polls,
        _poll_delay_s=ctx.environment_config.relayer_poll_frequency_ms / 1000,
    ).wait()


def _parse_authorize_session_key_request(
    *,
    address: object,
    scopes: object,
    idempotency_key: object,
) -> _ParsedAuthorizeSessionKeyRequest:
    session_address = _parse_session_address(address)
    normalized_scopes = _parse_scopes(scopes)
    valid_until = datetime.fromtimestamp(
        int(time.time()) + _SESSION_KEY_LIFETIME_SECONDS,
        tz=UTC,
    )
    return _ParsedAuthorizeSessionKeyRequest(
        address=session_address,
        scopes=normalized_scopes,
        valid_until=valid_until,
        valid_until_epoch=int(valid_until.timestamp()),
        idempotency_key=_parse_idempotency_key(idempotency_key),
    )


def _parse_revoke_session_key_request(
    *,
    address: object,
    idempotency_key: object,
) -> _ParsedRevokeSessionKeyRequest:
    return _ParsedRevokeSessionKeyRequest(
        address=_parse_session_address(address),
        idempotency_key=_parse_idempotency_key(idempotency_key),
    )


def _parse_session_address(address: object) -> EvmAddress:
    if not isinstance(address, str) or _EVM_ADDRESS_RE.fullmatch(address) is None:
        raise UserInputError("Session key address must be a valid EVM address.")
    try:
        normalized = to_checksum_address(address)
    except (TypeError, ValueError) as error:
        raise UserInputError("Session key address must be a valid EVM address.") from error
    if normalized.lower() == _ZERO_ADDRESS:
        raise UserInputError("Session key address must not be the zero address.")
    return EvmAddress(normalized)


def _normalize_response_address(value: object) -> EvmAddress:
    if not isinstance(value, str) or _EVM_ADDRESS_RE.fullmatch(value) is None:
        raise ValueError("invalid EVM address")
    try:
        return EvmAddress(to_checksum_address(value))
    except (TypeError, ValueError) as error:
        raise ValueError("invalid EVM address") from error


def _parse_scopes(scopes: object) -> tuple[SessionKeyScope, ...]:
    if isinstance(scopes, str | bytes) or not isinstance(scopes, Sequence):
        raise UserInputError("Session key scopes must be a non-empty sequence.")
    if not scopes:
        raise UserInputError("Session key scopes must be a non-empty sequence.")
    normalized: list[SessionKeyScope] = []
    for scope in cast(Sequence[object], scopes):
        if not isinstance(scope, str) or not scope:
            raise UserInputError("Session key scopes must contain non-empty strings.")
        try:
            normalized_scope: SessionKeyScope = SessionKeyKnownScope(scope)
        except ValueError:
            normalized_scope = scope
        normalized.append(normalized_scope)

    if SessionKeyKnownScope.ALL in normalized and any(
        scope != SessionKeyKnownScope.ALL for scope in normalized
    ):
        raise UserInputError("Session key scope ALL cannot be combined with another scope.")
    return tuple(normalized)


def _parse_idempotency_key(idempotency_key: object) -> str:
    if idempotency_key is None:
        return str(uuid4())
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise UserInputError("idempotency_key must be a non-empty string.")
    return idempotency_key.strip()


def _assert_owner_deposit_wallet(ctx: _SecureContext) -> None:
    if ctx.wallet_type != "DEPOSIT_WALLET":
        raise UserInputError("Session keys can only be managed for a Deposit Wallet.")
    if ctx.signer_type != "OWNER":
        raise UserInputError("Session keys can only be managed by the Deposit Wallet owner.")


def _require_builder_api_key(ctx: _SecureContext) -> None:
    if not isinstance(ctx.api_key, BuilderApiKey):
        raise UserInputError("Session-key authorization requires builder API-key authentication.")


def _require_gasless_api_key(ctx: _SecureContext) -> None:
    if ctx.api_key is None:
        raise UserInputError(
            "Session-key revocation requires API-key authentication that supports "
            "gasless transactions."
        )


def _assert_authorization_accepted(status: _AuthorizeSessionSignerStatus) -> None:
    if status in {
        _AuthorizeSessionSignerStatus.FAILED,
        _AuthorizeSessionSignerStatus.SUPERSEDED,
        _AuthorizeSessionSignerStatus.REPAIR_REQUIRED,
    }:
        raise TransactionFailedError(f"Session-key authorization reached terminal status {status}")


def _assert_revocation_accepted(status: _RevokeSessionSignerStatus) -> None:
    if status is _RevokeSessionSignerStatus.FAILED:
        raise TransactionFailedError(f"Session-key revocation reached terminal status {status}")


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


def _build_revocation_payload(
    ctx: _SecureContext,
    *,
    request: _ParsedRevokeSessionKeyRequest,
    batch: SignedDepositWalletBatch,
) -> dict[str, object]:
    return {
        "deadline": batch.deadline,
        "nonce": batch.nonce,
        "sessionSignerAddress": str(request.address),
        "signature": batch.signature,
        "walletAddress": str(ctx.wallet),
    }


async def _post_session_key_operation(
    ctx: AsyncSecureClientContext,
    *,
    path: str,
    payload: dict[str, object],
    idempotency_key: str,
    parse: Callable[[object], _ResponseT],
) -> _ResponseT:
    headers = {"Idempotency-Key": idempotency_key}
    for attempt in range(_SESSION_KEY_SUBMISSION_MAX_RETRIES + 1):
        try:
            data = await ctx.relayer.post_json(path, json=payload, headers=headers)
        except (RateLimitError, RequestRejectedError, TransportError) as error:
            if (
                attempt == _SESSION_KEY_SUBMISSION_MAX_RETRIES
                or not _is_retryable_session_key_submission(error)
            ):
                raise
            await asyncio.sleep(_session_key_retry_delay_s(ctx, error=error))
        else:
            return parse(data)
    raise AssertionError("unreachable")


def _post_session_key_operation_sync(
    ctx: SyncSecureClientContext,
    *,
    path: str,
    payload: dict[str, object],
    idempotency_key: str,
    parse: Callable[[object], _ResponseT],
) -> _ResponseT:
    headers = {"Idempotency-Key": idempotency_key}
    for attempt in range(_SESSION_KEY_SUBMISSION_MAX_RETRIES + 1):
        try:
            data = ctx.relayer.post_json(path, json=payload, headers=headers)
        except (RateLimitError, RequestRejectedError, TransportError) as error:
            if (
                attempt == _SESSION_KEY_SUBMISSION_MAX_RETRIES
                or not _is_retryable_session_key_submission(error)
            ):
                raise
            time.sleep(_session_key_retry_delay_s(ctx, error=error))
        else:
            return parse(data)
    raise AssertionError("unreachable")


def _is_retryable_session_key_submission(error: BaseException) -> bool:
    return isinstance(error, (RateLimitError, TransportError)) or (
        isinstance(error, RequestRejectedError) and 500 <= error.status < 600
    )


def _session_key_retry_delay_s(
    ctx: _SecureContext,
    *,
    error: RateLimitError | RequestRejectedError | TransportError,
) -> float:
    if isinstance(error, (RateLimitError, RequestRejectedError)) and error.retry_after is not None:
        return max(error.retry_after, 0)
    return ctx.environment_config.relayer_poll_frequency_ms / 1000


def _build_session_keys(
    ctx: _SecureContext,
    *,
    response: _FetchSessionKeysResponse,
) -> tuple[AuthorizedSessionKey, ...]:
    if response.wallet.lower() != str(ctx.wallet).lower():
        raise UnexpectedResponseError(
            f"Session-key response wallet {response.wallet} does not match authenticated "
            f"wallet {ctx.wallet}"
        )
    return tuple(
        AuthorizedSessionKey(
            address=signer.address,
            scopes=tuple(_normalize_response_scope(scope) for scope in signer.scopes),
            valid_until=signer.valid_until,
        )
        for signer in response.signers
    )


def _normalize_response_scope(scope: str) -> SessionKeyScope:
    try:
        return SessionKeyKnownScope(scope)
    except ValueError:
        return scope


async def _wait_for_authorized_session_key(
    ctx: AsyncSecureClientContext,
    *,
    expected: _ParsedAuthorizeSessionKeyRequest,
) -> AuthorizedSessionKey:
    for attempt in range(ctx.environment_config.relayer_max_polls):
        for session_key in await _fetch_session_keys_for_readiness(ctx):
            if _is_expected_session_key(session_key, expected=expected):
                return session_key
        if attempt + 1 < ctx.environment_config.relayer_max_polls:
            await asyncio.sleep(ctx.environment_config.relayer_poll_frequency_ms / 1000)
    raise TimeoutError(f"Timed out waiting for session key {expected.address} to become active")


def _wait_for_authorized_session_key_sync(
    ctx: SyncSecureClientContext,
    *,
    expected: _ParsedAuthorizeSessionKeyRequest,
) -> AuthorizedSessionKey:
    for attempt in range(ctx.environment_config.relayer_max_polls):
        for session_key in _fetch_session_keys_for_readiness_sync(ctx):
            if _is_expected_session_key(session_key, expected=expected):
                return session_key
        if attempt + 1 < ctx.environment_config.relayer_max_polls:
            time.sleep(ctx.environment_config.relayer_poll_frequency_ms / 1000)
    raise TimeoutError(f"Timed out waiting for session key {expected.address} to become active")


async def _fetch_session_keys_for_readiness(
    ctx: AsyncSecureClientContext,
) -> tuple[AuthorizedSessionKey, ...]:
    try:
        return await fetch_session_keys(ctx)
    except (RateLimitError, TransportError):
        return ()
    except RequestRejectedError as error:
        if error.status != 404 and not 500 <= error.status < 600:
            raise
        return ()


def _fetch_session_keys_for_readiness_sync(
    ctx: SyncSecureClientContext,
) -> tuple[AuthorizedSessionKey, ...]:
    try:
        return fetch_session_keys_sync(ctx)
    except (RateLimitError, TransportError):
        return ()
    except RequestRejectedError as error:
        if error.status != 404 and not 500 <= error.status < 600:
            raise
        return ()


def _is_expected_session_key(
    session_key: AuthorizedSessionKey,
    *,
    expected: _ParsedAuthorizeSessionKeyRequest,
) -> bool:
    actual_scopes = tuple(str(scope) for scope in session_key.scopes)
    expected_scopes = tuple(str(scope) for scope in expected.scopes)
    return (
        session_key.address.lower() == expected.address.lower()
        and session_key.valid_until == expected.valid_until
        and set(actual_scopes) == set(expected_scopes)
    )


def _build_authorization_result(
    *,
    session_key: AuthorizedSessionKey,
    transaction: TransactionOutcome,
) -> AuthorizeSessionKeyResult:
    return AuthorizeSessionKeyResult(
        session_key=session_key,
        transaction=transaction,
    )


__all__ = [
    "authorize_session_key",
    "authorize_session_key_sync",
    "fetch_session_keys",
    "fetch_session_keys_sync",
    "revoke_session_key",
    "revoke_session_key_sync",
]
