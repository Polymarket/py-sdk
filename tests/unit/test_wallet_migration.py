"""Wallet migration flow and sweep signature against controlled responses."""

# pyright: reportPrivateUsage=false
import json
import time
from typing import Any

import httpx
import pytest
import respx
from _bearer import fake_access_token
from eth_account import Account
from eth_account.messages import SignableMessage, encode_defunct
from eth_utils.crypto import keccak

from polymarket import BearerCredentials, SecureClient
from polymarket._internal.actions import wallet_migration
from polymarket._internal.actions.identity import UPGRADE_PATH
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket.errors import UnexpectedResponseError
from polymarket.models.wallet_migration import WalletMigrationSweep

PRIVATE_KEY = "0x" + "44" * 32
SIGNER = Account.from_key(PRIVATE_KEY).address
DEPOSIT_WALLET = "0x00000000000000000000000000000000000000bb"
AUTH = PRODUCTION_CONFIG.predictions_url
DIGEST = "0x" + "ab" * 32
SAFE_FACTORY = PRODUCTION_CONFIG.wallet_derivation.safe_factory
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _token(wallet: str | None) -> str:
    return fake_access_token(
        sub=SIGNER, wallet=wallet, clob_api_key="trading-key", exp=int(time.time()) + 900
    )


def _step(state: str, action: str, **extra: Any) -> dict[str, Any]:
    return {
        "state": state,
        "depositWallet": DEPOSIT_WALLET,
        "nextAction": {"type": action},
        **extra,
    }


def test_migrating_signs_the_sweep_recovers_a_lost_answer_and_binds_the_deposit_wallet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def wait(seconds: float) -> None:
        events.append(f"wait {seconds}")

    monkeypatch.setattr(wallet_migration.time, "sleep", wait)
    bound = _token(DEPOSIT_WALLET)
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

    saved = BearerCredentials(access_token=_token(None), refresh_token="refresh")
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{AUTH}/v1/wallets/migration/start").mock(side_effect=start)
        router.post(f"{AUTH}/v1/wallets/migration/execute").mock(side_effect=execute)
        router.post(f"{AUTH}{UPGRADE_PATH}").mock(side_effect=bind)

        with SecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=saved,
            validate_credentials=False,
            wallet_setup=False,
        ) as client:
            migrated = client.migrate_wallet()

        with migrated:
            assert migrated.credentials.access_token == bound

    assert events == [
        "/v1/wallets/migration/start",
        "/v1/wallets/migration/execute",
        "/v1/wallets/migration/start",
        f"wait {PRODUCTION_CONFIG.relayer_poll_frequency_ms / 1000}",
        "/v1/wallets/migration/execute",
        UPGRADE_PATH,
    ]
    signature = executes[0]["signature"]
    assert executes == [{"signature": signature, "digest": DIGEST}, {}]
    recovered = Account.recover_message(encode_defunct(hexstr=DIGEST), signature=signature)
    assert recovered == SIGNER


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
