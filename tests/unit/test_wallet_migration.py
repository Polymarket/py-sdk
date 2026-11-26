"""Wallet migration, leftover sweep and cancel flows against controlled responses."""

# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import json
import time
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from _bearer import fake_access_token
from eth_account import Account
from eth_account.messages import SignableMessage, encode_defunct
from eth_utils.crypto import keccak

from polymarket import AsyncSecureClient, BearerCredentials, SecureClient
from polymarket._internal.actions import wallet_migration
from polymarket._internal.actions.identity import UPGRADE_PATH
from polymarket._internal.environment import PRODUCTION_CONFIG, with_environment_config
from polymarket._internal.wallet import (
    derive_beacon_deposit_wallet_address,
    derive_proxy_wallet_address,
    derive_safe_wallet_address,
)
from polymarket.environments import PRODUCTION, Environment
from polymarket.errors import TimeoutError, UnexpectedResponseError
from polymarket.models.wallet_migration import (
    WalletLeftovers,
    WalletMigration,
    WalletMigrationNextAction,
    WalletMigrationState,
    WalletMigrationSweep,
)

PRIVATE_KEY = "0x" + "44" * 32
SIGNER = Account.from_key(PRIVATE_KEY).address
DERIVATION = PRODUCTION_CONFIG.wallet_derivation
DEPOSIT_WALLET = derive_beacon_deposit_wallet_address(SIGNER, DERIVATION)
SAFE_WALLET = derive_safe_wallet_address(SIGNER, DERIVATION)
PROXY_WALLET = derive_proxy_wallet_address(SIGNER, DERIVATION)
UNKNOWN_WALLET = "0x00000000000000000000000000000000000000bb"
AUTH = PRODUCTION_CONFIG.predictions_url
DIGEST = "0x" + "ab" * 32
SAFE_FACTORY = DERIVATION.safe_factory
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
POLL_WAIT = f"wait {PRODUCTION_CONFIG.relayer_poll_frequency_ms / 1000}"

MIGRATION_WITH_A_LOST_ANSWER = [
    "/v1/wallets/migration/start",
    "/v1/wallets/migration/execute",
    "/v1/wallets/migration/start",
    POLL_WAIT,
    "/v1/wallets/migration/execute",
    UPGRADE_PATH,
]
LEFTOVER_SWEEP = [
    "/v1/wallets/migration/sweep/start",
    "/v1/wallets/migration/sweep/execute",
    POLL_WAIT,
    "/v1/wallets/migration/sweep/execute",
    "/v1/wallets/migration/leftovers",
]
LEFTOVERS_AFTER_THE_SWEEP: dict[str, Any] = {
    "hasLeftovers": False,
    "legacyWallet": SAFE_WALLET,
    "depositWallet": DEPOSIT_WALLET,
    "manifest": [],
    "cashUsd": 0,
    "amountUsd": 0,
    "amountComplete": True,
    "blockers": [],
    "lastSweep": {"state": "COMPLETED", "sweepSubmitted": True},
    "sweepAvailable": False,
}
CANCELLED_MIGRATION: dict[str, Any] = {
    "state": "REQUIRED",
    "depositWallet": DEPOSIT_WALLET,
    "tradingPaused": False,
    "cancelable": False,
    "manifest": None,
    "nextAction": {"type": "start"},
}


def _token(wallet: str | None) -> str:
    return fake_access_token(
        sub=SIGNER, wallet=wallet, clob_api_key="trading-key", exp=int(time.time()) + 900
    )


def _saved(wallet: str | None) -> BearerCredentials:
    return BearerCredentials(access_token=_token(wallet), refresh_token="refresh")


def _client(saved: BearerCredentials, environment: Environment = PRODUCTION) -> SecureClient:
    return SecureClient._create(
        private_key=PRIVATE_KEY,
        credentials=saved,
        environment=environment,
        validate_credentials=False,
        wallet_setup=False,
    )


async def _async_client(saved: BearerCredentials) -> AsyncSecureClient:
    return await AsyncSecureClient._create(
        private_key=PRIVATE_KEY,
        credentials=saved,
        validate_credentials=False,
        wallet_setup=False,
    )


def _step(state: str, action: str, **extra: Any) -> dict[str, Any]:
    return {
        "state": state,
        "depositWallet": DEPOSIT_WALLET,
        "nextAction": {"type": action},
        **extra,
    }


def _record_waits(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    """Record each poll wait of the sync and the async flow in ``events``."""
    real_sleep = asyncio.sleep

    def wait(seconds: float) -> None:
        events.append(f"wait {seconds}")

    async def async_wait(seconds: float) -> None:
        events.append(f"wait {seconds}")
        await real_sleep(0)

    monkeypatch.setattr(wallet_migration.time, "sleep", wait)
    monkeypatch.setattr(wallet_migration.asyncio, "sleep", async_wait)


def _route_a_migration_with_a_lost_answer(
    router: respx.MockRouter, events: list[str], bound: str
) -> list[dict[str, Any]]:
    """Route a migration that loses the answer to its signed request.

    Returns:
        The bodies of the execute requests, in order.
    """
    starts = [
        _step("REQUIRES_FUNDS_TRANSFERS", "sign", sweep={"digest": DIGEST, "shape": "proxy"}),
        _step("REQUIRES_FUNDS_TRANSFERS", "execute", sweepSubmitted=True),
    ]
    # The answer to the signed request is lost, so the flow asks the start request again.
    answers = [httpx.Response(502), httpx.Response(200, json=_step("COMPLETED", "none"))]
    executes: list[dict[str, Any]] = []

    def start(request: httpx.Request) -> httpx.Response:
        events.append(request.url.path)
        return httpx.Response(200, json=starts.pop(0))

    def execute(request: httpx.Request) -> httpx.Response:
        events.append(request.url.path)
        executes.append(json.loads(request.content))
        return answers.pop(0)

    def bind(request: httpx.Request) -> httpx.Response:
        events.append(request.url.path)
        return httpx.Response(
            200, json={"accessToken": bound, "tokenType": "Bearer", "expiresIn": 900}
        )

    router.post(f"{AUTH}/v1/wallets/migration/start").mock(side_effect=start)
    router.post(f"{AUTH}/v1/wallets/migration/execute").mock(side_effect=execute)
    router.post(f"{AUTH}{UPGRADE_PATH}").mock(side_effect=bind)
    return executes


def _route_a_leftover_sweep(router: respx.MockRouter, events: list[str]) -> list[dict[str, Any]]:
    """Route a leftover sweep that signs once and then polls once.

    Returns:
        The bodies of the execute requests, in order.
    """
    answers = [
        _step("REQUIRES_FUNDS_TRANSFERS", "execute", sweepSubmitted=True),
        _step("COMPLETED", "none", sweepSubmitted=True),
    ]
    executes: list[dict[str, Any]] = []

    def start(request: httpx.Request) -> httpx.Response:
        events.append(request.url.path)
        sweep = {"digest": DIGEST, "shape": "safe"}
        return httpx.Response(200, json=_step("REQUIRES_FUNDS_TRANSFERS", "sign", sweep=sweep))

    def execute(request: httpx.Request) -> httpx.Response:
        events.append(request.url.path)
        executes.append(json.loads(request.content))
        return httpx.Response(200, json=answers.pop(0))

    def leftovers(request: httpx.Request) -> httpx.Response:
        events.append(request.url.path)
        return httpx.Response(200, json=LEFTOVERS_AFTER_THE_SWEEP)

    router.post(f"{AUTH}/v1/wallets/migration/sweep/start").mock(side_effect=start)
    router.post(f"{AUTH}/v1/wallets/migration/sweep/execute").mock(side_effect=execute)
    router.get(f"{AUTH}/v1/wallets/migration/leftovers").mock(side_effect=leftovers)
    return executes


def _route_a_cancel(router: respx.MockRouter, bodies: list[object]) -> None:
    def cancel(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=CANCELLED_MIGRATION)

    router.post(f"{AUTH}/v1/wallets/migration/cancel").mock(side_effect=cancel)


def _assert_signed_once_then_polled(executes: list[dict[str, Any]]) -> None:
    signature = executes[0]["signature"]
    assert executes == [{"signature": signature, "digest": DIGEST}, {}]
    recovered = Account.recover_message(encode_defunct(hexstr=DIGEST), signature=signature)
    assert recovered == SIGNER


def _assert_leftovers_after_the_sweep(leftovers: WalletLeftovers) -> None:
    assert leftovers.has_leftovers is False
    assert leftovers.last_sweep is not None
    assert leftovers.last_sweep.state == WalletMigrationState.COMPLETED


def _assert_cancelled(migration: WalletMigration) -> None:
    assert migration.state == WalletMigrationState.REQUIRED
    assert migration.deposit_wallet == DEPOSIT_WALLET
    assert migration.manifest == []
    assert migration.next_action is WalletMigrationNextAction.START


def test_migrating_signs_the_sweep_recovers_a_lost_answer_and_binds_the_deposit_wallet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _record_waits(monkeypatch, events)
    bound = _token(DEPOSIT_WALLET)
    with respx.mock(assert_all_called=True) as router:
        executes = _route_a_migration_with_a_lost_answer(router, events, bound)

        with _client(_saved(None)) as client:
            migrated = client.migrate_wallet()

        with migrated:
            assert migrated.wallet == DEPOSIT_WALLET
            assert migrated.credentials.access_token == bound

    assert events == MIGRATION_WITH_A_LOST_ANSWER
    _assert_signed_once_then_polled(executes)


def test_an_async_migration_signs_the_sweep_recovers_a_lost_answer_and_binds_the_deposit_wallet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _record_waits(monkeypatch, events)
    bound = _token(DEPOSIT_WALLET)

    async def run() -> None:
        async with await _async_client(_saved(None)) as client:
            migrated = await client.migrate_wallet()

        async with migrated:
            assert migrated.wallet == DEPOSIT_WALLET
            assert migrated.credentials.access_token == bound

    with respx.mock(assert_all_called=True) as router:
        executes = _route_a_migration_with_a_lost_answer(router, events, bound)
        asyncio.run(run())

    assert events == MIGRATION_WITH_A_LOST_ANSWER
    _assert_signed_once_then_polled(executes)


def test_a_migration_that_is_not_required_binds_the_current_deposit_wallet() -> None:
    saved = _saved(DEPOSIT_WALLET)
    with respx.mock(assert_all_called=True) as router:
        # The router has no bind route, so a bind request fails the migration.
        router.post(f"{AUTH}/v1/wallets/migration/start").respond(
            200, json=_step("NOT_REQUIRED", "none")
        )

        with _client(saved) as client:
            migrated = client.migrate_wallet()

        with migrated:
            assert migrated.wallet == DEPOSIT_WALLET
            assert migrated.wallet_type == "DEPOSIT_WALLET"
            assert migrated.credentials == saved


@pytest.mark.parametrize(
    "destination",
    [
        pytest.param(SAFE_WALLET, id="safe"),
        pytest.param(PROXY_WALLET, id="proxy"),
        pytest.param(SIGNER, id="signer"),
        pytest.param(UNKNOWN_WALLET, id="unknown"),
    ],
)
def test_a_migration_to_a_wallet_that_is_not_a_deposit_wallet_is_refused_before_the_bind(
    destination: str,
) -> None:
    saved = _saved(SAFE_WALLET)
    with respx.mock(assert_all_called=True) as router:
        # The router has no bind route, so a bind request fails with another error.
        router.post(f"{AUTH}/v1/wallets/migration/start").respond(
            200, json=_step("COMPLETED", "none", depositWallet=destination)
        )

        with _client(saved) as client:
            with pytest.raises(UnexpectedResponseError, match="not a Deposit Wallet of the signer"):
                client.migrate_wallet()
            assert client.credentials == saved


def test_an_async_migration_to_an_unknown_wallet_is_refused_before_the_bind() -> None:
    saved = _saved(SAFE_WALLET)

    async def run() -> None:
        async with await _async_client(saved) as client:
            with pytest.raises(UnexpectedResponseError, match="not a Deposit Wallet of the signer"):
                await client.migrate_wallet()
            assert client.credentials == saved

    with respx.mock(assert_all_called=True) as router:
        router.post(f"{AUTH}/v1/wallets/migration/start").respond(
            200, json=_step("COMPLETED", "none", depositWallet=UNKNOWN_WALLET)
        )
        asyncio.run(run())


def test_a_resumed_migration_waits_before_its_poll_and_stops_at_the_poll_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(wallet_migration.time, "sleep", sleeps.append)
    confirming = _step("REQUIRES_FUNDS_TRANSFERS", "execute", sweepSubmitted=True)
    environment = with_environment_config(
        PRODUCTION, config=dataclasses.replace(PRODUCTION_CONFIG, relayer_max_polls=1)
    )
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{AUTH}/v1/wallets/migration/start").respond(200, json=confirming)
        waits_before_execute: list[int] = []

        def execute(_: httpx.Request) -> httpx.Response:
            waits_before_execute.append(len(sleeps))
            return httpx.Response(200, json=confirming)

        router.post(f"{AUTH}/v1/wallets/migration/execute").mock(side_effect=execute)

        with _client(_saved(None), environment) as client, pytest.raises(TimeoutError):
            client.migrate_wallet()

    # One poll, after one wait, and no poll after the limit.
    assert waits_before_execute == [1]
    assert sleeps == [PRODUCTION_CONFIG.relayer_poll_frequency_ms / 1000]


def test_sweeping_leftovers_signs_the_sweep_and_reads_the_leftovers_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _record_waits(monkeypatch, events)
    saved = _saved(DEPOSIT_WALLET)
    with respx.mock(assert_all_called=True) as router:
        executes = _route_a_leftover_sweep(router, events)

        with _client(saved) as client:
            leftovers = client.sweep_wallet_leftovers()
            assert client.credentials == saved

    assert events == LEFTOVER_SWEEP
    _assert_signed_once_then_polled(executes)
    _assert_leftovers_after_the_sweep(leftovers)


def test_an_async_leftover_sweep_signs_the_sweep_and_reads_the_leftovers_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _record_waits(monkeypatch, events)
    saved = _saved(DEPOSIT_WALLET)

    async def run() -> WalletLeftovers:
        async with await _async_client(saved) as client:
            leftovers = await client.sweep_wallet_leftovers()
            assert client.credentials == saved
            return leftovers

    with respx.mock(assert_all_called=True) as router:
        executes = _route_a_leftover_sweep(router, events)
        leftovers = asyncio.run(run())

    assert events == LEFTOVER_SWEEP
    _assert_signed_once_then_polled(executes)
    _assert_leftovers_after_the_sweep(leftovers)


def test_cancelling_a_migration_sends_an_empty_body_and_returns_the_migration() -> None:
    bodies: list[object] = []
    with respx.mock(assert_all_called=True) as router:
        _route_a_cancel(router, bodies)

        with _client(_saved(SAFE_WALLET)) as client:
            migration = client.cancel_wallet_migration()

    assert bodies == [{}]
    _assert_cancelled(migration)


def test_cancelling_an_async_migration_sends_an_empty_body_and_returns_the_migration() -> None:
    bodies: list[object] = []

    async def run() -> WalletMigration:
        async with await _async_client(_saved(SAFE_WALLET)) as client:
            return await client.cancel_wallet_migration()

    with respx.mock(assert_all_called=True) as router:
        _route_a_cancel(router, bodies)
        migration = asyncio.run(run())

    assert bodies == [{}]
    _assert_cancelled(migration)


@pytest.mark.parametrize(
    ("wire", "amount"),
    [
        pytest.param(0.1, Decimal("0.1"), id="fraction"),
        pytest.param(12, Decimal("12"), id="integer"),
        pytest.param("1234.56", Decimal("1234.56"), id="string"),
    ],
)
def test_leftover_amounts_parse_to_exact_decimals(wire: object, amount: Decimal) -> None:
    leftovers = WalletLeftovers.parse_response(
        {**LEFTOVERS_AFTER_THE_SWEEP, "cashUsd": wire, "positionsValueUsd": wire, "amountUsd": wire}
    )

    assert leftovers.cash_usd == amount
    assert leftovers.positions_value_usd == amount
    assert leftovers.amount_usd == amount


def test_a_leftover_amount_that_is_a_boolean_is_refused() -> None:
    with pytest.raises(UnexpectedResponseError):
        WalletLeftovers.parse_response({**LEFTOVERS_AFTER_THE_SWEEP, "cashUsd": True})


def _safe_deployment(payment: str) -> WalletMigrationSweep:
    return WalletMigrationSweep.parse_response(
        {
            "digest": DIGEST,
            "shape": "safe-create",
            "typedData": {
                "primaryType": "CreateProxy",
                "domain": {
                    "name": "Polymarket Contract Proxy Factory",
                    "chainId": 137,
                    "verifyingContract": SAFE_FACTORY,
                },
                "types": {
                    "CreateProxy": [
                        {"name": "paymentToken", "type": "address"},
                        {"name": "payment", "type": "uint256"},
                        {"name": "paymentReceiver", "type": "address"},
                    ]
                },
                "message": {
                    "paymentToken": ZERO_ADDRESS,
                    "payment": payment,
                    "paymentReceiver": ZERO_ADDRESS,
                },
            },
        }
    )


def _sign(sweep: WalletMigrationSweep) -> str:
    return wallet_migration.sign_sweep(
        Account.from_key(PRIVATE_KEY), sweep, chain_id=137, safe_factory=SAFE_FACTORY
    )


def _factory_digest_without_payment() -> SignableMessage:
    """Build the digest that the Safe factory recovers its signer from, with no payment."""
    domain_separator = keccak(
        keccak(text="EIP712Domain(string name,uint256 chainId,address verifyingContract)")
        + keccak(text="Polymarket Contract Proxy Factory")
        + (137).to_bytes(32, "big")
        + bytes.fromhex(SAFE_FACTORY[2:]).rjust(32, b"\0")
    )
    struct_hash = keccak(
        keccak(text="CreateProxy(address paymentToken,uint256 payment,address paymentReceiver)")
        + bytes(96)
    )
    return SignableMessage(b"\x01", domain_separator, struct_hash)


def test_a_safe_deployment_signature_recovers_to_the_signer_at_the_factory() -> None:
    signature = _sign(_safe_deployment(payment="0"))

    assert Account.recover_message(_factory_digest_without_payment(), signature=signature) == SIGNER


def test_a_safe_deployment_with_a_payment_is_not_signed() -> None:
    with pytest.raises(UnexpectedResponseError):
        _sign(_safe_deployment(payment="1"))


def test_a_step_with_no_next_action_in_an_unfinished_state_does_not_finish_the_flow() -> None:
    step = wallet_migration.parse_step(_step("SWEEP_PENDING", "none"), "wallet migration")

    with pytest.raises(UnexpectedResponseError):
        wallet_migration.next_move(step, "wallet migration")
