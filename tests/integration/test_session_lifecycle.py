"""Session lifecycle against the live authentication service.

Side effects: each test opens its own sessions and revokes them when it ends.
The migration test creates or derives the signer's API credentials at a
dedicated nonce and exchanges them; they are never revoked.
"""

import asyncio
import time

import httpx
import pytest
from eth_account.signers.local import LocalAccount

from polymarket import (
    ApiKeyCreds,
    AsyncSecureClient,
    BearerCredentials,
    Environment,
    RequestRejectedError,
)
from polymarket._internal.actions import identity
from polymarket._internal.environment import get_environment_config

# API credentials the migration test sets up for itself, apart from other keys of the signer.
_MIGRATION_NONCE = 3


@pytest.mark.integration
@pytest.mark.metered
def test_restored_session_reports_renewals_and_shares_explicit_ones(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    integration_environment: Environment,
) -> None:
    async def run() -> tuple[BearerCredentials, list[BearerCredentials], BearerCredentials]:
        initial = await AsyncSecureClient.create(
            private_key=deposit_wallet_private_key,
            wallet=deposit_wallet_address,
            environment=integration_environment,
        )
        saved = initial.credentials
        changes: list[BearerCredentials] = []

        # The async client also accepts a coroutine listener.
        async def store(credentials: BearerCredentials) -> None:
            changes.append(credentials)

        restored = await AsyncSecureClient.create(
            private_key=deposit_wallet_private_key,
            wallet=deposit_wallet_address,
            credentials=saved,
            environment=integration_environment,
            on_credentials_changed=store,
        )
        try:
            first, second = await asyncio.gather(
                restored.refresh_credentials(), restored.refresh_credentials()
            )
            assert first == second
            await restored.list_open_orders().first_page()
            return saved, changes, restored.credentials
        finally:
            await asyncio.gather(
                restored.end_authentication(),
                initial.end_authentication(),
                return_exceptions=True,
            )

    saved, changes, current = asyncio.run(run())

    # One renewal while restoring and one shared by both explicit calls.
    assert len(changes) == 2
    assert changes[-1] == current
    # Renewal keeps the refresh token.
    assert current.refresh_token == saved.refresh_token


@pytest.mark.integration
@pytest.mark.metered
def test_saved_api_credentials_migrate_without_a_wallet_signature(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    integration_environment: Environment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = _obtain_api_credentials(
        integration_environment, identity.signer_from_private_key(deposit_wallet_private_key)
    )

    def refuse_to_sign(*_: object, **__: object) -> str:
        raise AssertionError("migration must not ask the wallet to sign")

    monkeypatch.setattr(identity, "sign_ownership_challenge", refuse_to_sign)

    async def run() -> None:
        client = await AsyncSecureClient.create(
            private_key=deposit_wallet_private_key,
            wallet=deposit_wallet_address,
            credentials=saved,
            environment=integration_environment,
        )
        try:
            await client.list_open_orders().first_page()
        finally:
            await client.end_authentication()

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.metered
def test_ended_session_no_longer_restores_a_client(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    integration_environment: Environment,
) -> None:
    async def run() -> None:
        client = await AsyncSecureClient.create(
            private_key=deposit_wallet_private_key,
            wallet=deposit_wallet_address,
            environment=integration_environment,
        )
        saved = client.credentials
        await client.end_authentication()

        with pytest.raises(RequestRejectedError) as rejection:
            await AsyncSecureClient.create(
                private_key=deposit_wallet_private_key,
                wallet=deposit_wallet_address,
                credentials=saved,
                environment=integration_environment,
            )

        # The rejection keeps no credentials in its message or chained cause.
        error = rejection.value
        assert saved.access_token not in str(error)
        assert saved.refresh_token not in str(error)
        assert error.__cause__ is None

    asyncio.run(run())


def _obtain_api_credentials(environment: Environment, signer: LocalAccount) -> ApiKeyCreds:
    """Obtain API credentials for ``signer`` directly from the trading service.

    The SDK no longer manages these credentials, so the migration test sets them up itself.
    """
    config = get_environment_config(environment)
    timestamp = str(int(time.time()))
    signature = signer.sign_typed_data(
        full_message={
            "domain": {"name": "ClobAuthDomain", "version": "1", "chainId": config.chain_id},
            "primaryType": "ClobAuth",
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "ClobAuth": [
                    {"name": "address", "type": "address"},
                    {"name": "timestamp", "type": "string"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "message", "type": "string"},
                ],
            },
            "message": {
                "address": signer.address,
                "timestamp": timestamp,
                "nonce": _MIGRATION_NONCE,
                "message": "This message attests that I control the given wallet",
            },
        }
    ).signature
    headers = {
        "POLY_ADDRESS": signer.address,
        "POLY_SIGNATURE": "0x" + signature.hex(),
        "POLY_TIMESTAMP": timestamp,
        "POLY_NONCE": str(_MIGRATION_NONCE),
    }
    with httpx.Client(base_url=config.clob_url, timeout=30) as http:
        response = http.post("/auth/api-key", headers=headers)
        if not response.is_success:
            response = http.get("/auth/derive-api-key", headers=headers)
    assert response.is_success
    body = response.json()
    return ApiKeyCreds(key=body["apiKey"], secret=body["secret"], passphrase=body["passphrase"])
