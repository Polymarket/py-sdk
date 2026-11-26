"""Wallet migration requests, the step policy and the sweep signature."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal, cast

import httpx
from eth_account.messages import encode_defunct
from eth_account.signers.local import LocalAccount

from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.wallet import try_classify_wallet_type
from polymarket.errors import (
    RequestRejectedError,
    SigningError,
    TimeoutError,
    TransactionFailedError,
    TransportError,
    UnexpectedResponseError,
)
from polymarket.models.wallet_migration import (
    WalletLeftovers,
    WalletMigration,
    WalletMigrationNextAction,
    WalletMigrationPreview,
    WalletMigrationState,
    WalletMigrationStep,
    WalletMigrationSweep,
    WalletMigrationSweepShape,
)
from polymarket.types import EvmAddress, HexString

# An execute request waits while its transaction confirms. It can also answer
# with a step that is still in progress.
_REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)

STATUS_PATH = "/v1/wallets/migration/status"
PREVIEW_PATH = "/v1/wallets/migration/preview"
START_PATH = "/v1/wallets/migration/start"
EXECUTE_PATH = "/v1/wallets/migration/execute"
CANCEL_PATH = "/v1/wallets/migration/cancel"
LEFTOVERS_PATH = "/v1/wallets/migration/leftovers"
SWEEP_START_PATH = "/v1/wallets/migration/sweep/start"
SWEEP_EXECUTE_PATH = "/v1/wallets/migration/sweep/execute"

# A stale digest, a lost answer or a conflict sends the flow back to its start
# request. The limit stops a flow that never settles.
_MAX_RESTARTS = 3
# One attempt signs at most a Safe deployment and then the transfer. A restart can
# ask for new signatures, so the count starts again after each restart.
_MAX_SIGNATURES_PER_ATTEMPT = 2

_SAFE_FACTORY_DOMAIN_NAME = "Polymarket Contract Proxy Factory"
_DOMAIN_FIELDS = [
    {"name": "name", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]
_CREATE_PROXY_FIELDS = [
    {"name": "paymentToken", "type": "address"},
    {"name": "payment", "type": "uint256"},
    {"name": "paymentReceiver", "type": "address"},
]
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
# The only states in which a step with no next action is finished.
_FINISHED_STATES = frozenset({WalletMigrationState.COMPLETED, WalletMigrationState.NOT_REQUIRED})

Move = Literal["done", "start", "sign", "execute"]


def parse_step(data: object, flow: str) -> WalletMigrationStep:
    """Parse one step of ``flow``, a wallet migration or a leftover sweep.

    A failed step raises before the fields that continue the flow are read, so
    its reason surfaces even when those fields are invalid.

    Raises:
        TransactionFailedError: If the step has the state ``FAILED``, whatever
            its next action.
        UnexpectedResponseError: If the step is invalid.
    """
    reason = _failure_reason(data)
    if reason is not None:
        raise TransactionFailedError(f"The {flow} failed: {reason}.")
    return WalletMigrationStep.parse_response(data)


def _failure_reason(data: object) -> str | None:
    """Return the reason of a failed step, or ``None`` when the step did not fail."""
    if not isinstance(data, dict):
        return None
    payload = cast(dict[str, Any], data)
    if payload.get("state") != WalletMigrationState.FAILED:
        return None
    reason = payload.get("failedReason")
    return reason if isinstance(reason, str) and reason else "no reason given"


def next_move(step: WalletMigrationStep, flow: str) -> Move:
    """Return the move that follows ``step`` of ``flow``.

    Raises:
        UnexpectedResponseError: If ``step`` has no next action but its state
            is not final, so the flow cannot tell that the step finished.
    """
    if step.next_action is WalletMigrationNextAction.NONE:
        if step.state not in _FINISHED_STATES:
            raise UnexpectedResponseError(
                f"The {flow} has no next step, but its state {step.state} is not final."
            )
        return "done"
    if step.next_action is WalletMigrationNextAction.START:
        return "start"
    if step.next_action is WalletMigrationNextAction.SIGN:
        return "start" if step.sweep is None else "sign"
    return "execute"


def is_unsettled_execute(error: Exception) -> bool:
    """Return whether a failed execute request leaves the step unknown."""
    if isinstance(error, TransportError):
        return True
    return isinstance(error, RequestRejectedError) and error.status in (409, 502)


class _Budget:
    """Counts the restarts and the polls of one flow."""

    def __init__(self, max_polls: int, flow: str) -> None:
        self.max_polls = max_polls
        self.flow = flow
        self.restarts = 0
        self.polls = 0
        self.signatures = 0

    def restart(self) -> None:
        self.restarts += 1
        if self.restarts > _MAX_RESTARTS:
            raise TimeoutError(f"The {self.flow} did not settle after {_MAX_RESTARTS} restarts.")
        self.signatures = 0

    def sign(self) -> None:
        """Count one signed execute request of the current attempt."""
        self.signatures += 1
        if self.signatures > _MAX_SIGNATURES_PER_ATTEMPT:
            raise TimeoutError(
                f"The {self.flow} did not settle after {_MAX_SIGNATURES_PER_ATTEMPT} signatures."
            )

    def poll(self) -> None:
        """Count one poll of an execute step. A signed execute request is not a poll."""
        self.polls += 1
        if self.polls > self.max_polls:
            raise TimeoutError(f"The {self.flow} did not finish after {self.max_polls} polls.")


def safe_create_typed_data(
    typed_data: dict[str, Any] | None, *, chain_id: int, safe_factory: str
) -> dict[str, Any]:
    """Return the ``CreateProxy`` message that a ``safe-create`` sweep signs.

    The function checks every member of the server's typed data against the
    Polymarket Safe factory, with no payment, and builds the message from those
    fixed values.

    Raises:
        UnexpectedResponseError: If the typed data differs from the factory's.
    """
    invalid = UnexpectedResponseError(
        "The Safe deployment to sign does not match the Polymarket Safe factory."
    )
    if typed_data is None:
        raise invalid
    domain = typed_data.get("domain")
    types = typed_data.get("types")
    message = typed_data.get("message")
    if not isinstance(domain, dict) or not isinstance(types, dict) or not isinstance(message, dict):
        raise invalid
    domain = cast(dict[str, Any], domain)
    types = cast(dict[str, Any], types)
    message = cast(dict[str, Any], message)
    if (
        set(typed_data) != {"types", "primaryType", "domain", "message"}
        or typed_data.get("primaryType") != "CreateProxy"
        or set(domain) != {"name", "chainId", "verifyingContract"}
        or domain["name"] != _SAFE_FACTORY_DOMAIN_NAME
        or not _same_int(domain["chainId"], chain_id)
        or not _same_address(domain["verifyingContract"], safe_factory)
        or set(types) - {"EIP712Domain"} != {"CreateProxy"}
        or types["CreateProxy"] != _CREATE_PROXY_FIELDS
        or types.get("EIP712Domain", _DOMAIN_FIELDS) != _DOMAIN_FIELDS
        or set(message) != {"paymentToken", "payment", "paymentReceiver"}
        or not _same_address(message["paymentToken"], _ZERO_ADDRESS)
        or not _same_int(message["payment"], 0)
        or not _same_address(message["paymentReceiver"], _ZERO_ADDRESS)
    ):
        raise invalid
    return {
        "types": {"EIP712Domain": _DOMAIN_FIELDS, "CreateProxy": _CREATE_PROXY_FIELDS},
        "primaryType": "CreateProxy",
        "domain": {
            "name": _SAFE_FACTORY_DOMAIN_NAME,
            "chainId": chain_id,
            "verifyingContract": safe_factory,
        },
        "message": {
            "paymentToken": _ZERO_ADDRESS,
            "payment": 0,
            "paymentReceiver": _ZERO_ADDRESS,
        },
    }


def _same_int(value: object, expected: int) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == expected
    if isinstance(value, str):
        try:
            return int(value, 0) == expected
        except ValueError:
            return False
    return False


def _same_address(value: object, expected: str) -> bool:
    return isinstance(value, str) and value.lower() == expected.lower()


def sign_sweep(
    signer: LocalAccount, sweep: WalletMigrationSweep, *, chain_id: int, safe_factory: str
) -> HexString:
    """Sign ``sweep`` the way its shape requires."""
    if sweep.shape is WalletMigrationSweepShape.SAFE_CREATE:
        full_message = safe_create_typed_data(
            sweep.typed_data, chain_id=chain_id, safe_factory=safe_factory
        )
        try:
            signed = signer.sign_typed_data(full_message=full_message)
        except Exception as error:
            raise SigningError(f"Failed to sign the sweep: {error}") from error
    else:
        # Both shapes sign the raw digest as a personal message.
        try:
            signed = signer.sign_message(encode_defunct(hexstr=sweep.digest))
        except Exception as error:
            raise SigningError(f"Failed to sign the sweep: {error}") from error
    return cast(HexString, "0x" + signed.signature.hex())


def _sign(
    ctx: SyncSecureClientContext | AsyncSecureClientContext, sweep: WalletMigrationSweep
) -> HexString:
    return sign_sweep(
        ctx.signer,
        sweep,
        chain_id=ctx.environment_config.chain_id,
        safe_factory=ctx.environment_config.wallet_derivation.safe_factory,
    )


def run_steps_sync(
    ctx: SyncSecureClientContext, start_path: str, execute_path: str, *, flow: str
) -> WalletMigrationStep:
    """Run ``flow``, a wallet migration or a leftover sweep, to its last step.

    ``flow`` names the flow in error messages.
    """
    config = ctx.environment_config
    budget = _Budget(config.relayer_max_polls, flow)

    def start() -> WalletMigrationStep:
        data = ctx.predictions.post_json(start_path, json={}, timeout=_REQUEST_TIMEOUT)
        return parse_step(data, flow)

    def execute(body: dict[str, str]) -> WalletMigrationStep:
        try:
            data = ctx.predictions.post_json(execute_path, json=body, timeout=_REQUEST_TIMEOUT)
        except (TransportError, RequestRejectedError) as error:
            if not is_unsettled_execute(error):
                raise
            budget.restart()
            return start()
        return parse_step(data, flow)

    step = start()
    while True:
        move = next_move(step, flow)
        if move == "done":
            return step
        if move == "start":
            budget.restart()
            step = start()
        elif move == "sign":
            sweep = cast(WalletMigrationSweep, step.sweep)
            budget.sign()
            step = execute({"signature": _sign(ctx, sweep), "digest": sweep.digest})
        else:
            budget.poll()
            time.sleep(config.relayer_poll_frequency_ms / 1000)
            step = execute({})


async def run_steps(
    ctx: AsyncSecureClientContext, start_path: str, execute_path: str, *, flow: str
) -> WalletMigrationStep:
    """Run ``flow``, a wallet migration or a leftover sweep, to its last step.

    ``flow`` names the flow in error messages.
    """
    config = ctx.environment_config
    budget = _Budget(config.relayer_max_polls, flow)

    async def start() -> WalletMigrationStep:
        data = await ctx.predictions.post_json(start_path, json={}, timeout=_REQUEST_TIMEOUT)
        return parse_step(data, flow)

    async def execute(body: dict[str, str]) -> WalletMigrationStep:
        try:
            data = await ctx.predictions.post_json(
                execute_path, json=body, timeout=_REQUEST_TIMEOUT
            )
        except (TransportError, RequestRejectedError) as error:
            if not is_unsettled_execute(error):
                raise
            budget.restart()
            return await start()
        return parse_step(data, flow)

    step = await start()
    while True:
        move = next_move(step, flow)
        if move == "done":
            return step
        if move == "start":
            budget.restart()
            step = await start()
        elif move == "sign":
            sweep = cast(WalletMigrationSweep, step.sweep)
            budget.sign()
            step = await execute({"signature": _sign(ctx, sweep), "digest": sweep.digest})
        else:
            budget.poll()
            await asyncio.sleep(config.relayer_poll_frequency_ms / 1000)
            step = await execute({})


def deposit_wallet_to_bind(
    ctx: SyncSecureClientContext | AsyncSecureClientContext, step: WalletMigrationStep
) -> EvmAddress:
    """Return the Deposit Wallet that the finished migration ``step`` binds to the session.

    Raises:
        UnexpectedResponseError: If ``step`` names no wallet, or names a wallet
            that is not a Deposit Wallet of the signer.
    """
    if step.deposit_wallet is None:
        raise UnexpectedResponseError("The finished wallet migration names no Deposit Wallet.")
    # The bind accepts a Safe, a proxy wallet or an unknown address, so it does
    # not stop a wrong destination.
    wallet_type = try_classify_wallet_type(
        signer=ctx.signer.address,
        wallet=step.deposit_wallet,
        config=ctx.environment_config.wallet_derivation,
    )
    if wallet_type != "DEPOSIT_WALLET":
        raise UnexpectedResponseError(
            "The finished wallet migration names a wallet that is not a Deposit Wallet "
            "of the signer."
        )
    return step.deposit_wallet


def fetch_wallet_migration_sync(ctx: SyncSecureClientContext) -> WalletMigration:
    return WalletMigration.parse_response(ctx.predictions.get_json(STATUS_PATH))


async def fetch_wallet_migration(ctx: AsyncSecureClientContext) -> WalletMigration:
    return WalletMigration.parse_response(await ctx.predictions.get_json(STATUS_PATH))


def preview_wallet_migration_sync(ctx: SyncSecureClientContext) -> WalletMigrationPreview:
    return WalletMigrationPreview.parse_response(ctx.predictions.get_json(PREVIEW_PATH))


async def preview_wallet_migration(ctx: AsyncSecureClientContext) -> WalletMigrationPreview:
    return WalletMigrationPreview.parse_response(await ctx.predictions.get_json(PREVIEW_PATH))


def cancel_wallet_migration_sync(ctx: SyncSecureClientContext) -> WalletMigration:
    return WalletMigration.parse_response(ctx.predictions.post_json(CANCEL_PATH, json={}))


async def cancel_wallet_migration(ctx: AsyncSecureClientContext) -> WalletMigration:
    return WalletMigration.parse_response(await ctx.predictions.post_json(CANCEL_PATH, json={}))


def fetch_wallet_leftovers_sync(ctx: SyncSecureClientContext) -> WalletLeftovers:
    return WalletLeftovers.parse_response(ctx.predictions.get_json(LEFTOVERS_PATH))


async def fetch_wallet_leftovers(ctx: AsyncSecureClientContext) -> WalletLeftovers:
    return WalletLeftovers.parse_response(await ctx.predictions.get_json(LEFTOVERS_PATH))


__all__ = [
    "CANCEL_PATH",
    "EXECUTE_PATH",
    "LEFTOVERS_PATH",
    "PREVIEW_PATH",
    "START_PATH",
    "STATUS_PATH",
    "SWEEP_EXECUTE_PATH",
    "SWEEP_START_PATH",
    "cancel_wallet_migration",
    "cancel_wallet_migration_sync",
    "deposit_wallet_to_bind",
    "fetch_wallet_leftovers",
    "fetch_wallet_leftovers_sync",
    "fetch_wallet_migration",
    "fetch_wallet_migration_sync",
    "is_unsettled_execute",
    "next_move",
    "parse_step",
    "preview_wallet_migration",
    "preview_wallet_migration_sync",
    "run_steps",
    "run_steps_sync",
    "safe_create_typed_data",
    "sign_sweep",
]
