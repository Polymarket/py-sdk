"""Session lifecycle against the live authentication service.

Side effects: each test opens its own sessions and revokes them when it ends.
Saved API credentials are exchanged but never revoked.
"""

import asyncio

import pytest

from polymarket import (
    ApiKeyCreds,
    AsyncSecureClient,
    BearerCredentials,
    Environment,
    RequestRejectedError,
)
from polymarket._internal.actions import identity


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
        restored = await AsyncSecureClient.create(
            private_key=deposit_wallet_private_key,
            wallet=deposit_wallet_address,
            credentials=saved,
            environment=integration_environment,
            on_credentials_changed=changes.append,
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
    saved_api_credentials: ApiKeyCreds,
    integration_environment: Environment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse_to_sign(*_: object, **__: object) -> str:
        raise AssertionError("migration must not ask the wallet to sign")

    monkeypatch.setattr(identity, "sign_ownership_challenge", refuse_to_sign)

    async def run() -> None:
        client = await AsyncSecureClient.create(
            private_key=deposit_wallet_private_key,
            wallet=deposit_wallet_address,
            credentials=saved_api_credentials,
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

        with pytest.raises(RequestRejectedError):
            await AsyncSecureClient.create(
                private_key=deposit_wallet_private_key,
                wallet=deposit_wallet_address,
                credentials=saved,
                environment=integration_environment,
            )

    asyncio.run(run())
