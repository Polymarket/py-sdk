"""Application attribution with a Platform API Key against the live service.

Side effects: the session tests open their own sessions and revoke them. The
challenge test only requests a sign-in challenge.
"""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import pytest
from eth_account import Account

from polymarket import (
    AsyncSecureClient,
    Environment,
    PlatformApiKey,
    PublicClient,
    UserInputError,
)
from polymarket._internal.actions.identity import parse_access_token_claims


@dataclass(frozen=True)
class _Sent:
    method: str
    path: str
    platform_key: str | None
    bearer: bool


@pytest.fixture
def sent_requests(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[_Sent]]:
    """Observe the requests the SDK sends without changing them."""
    sent: list[_Sent] = []
    send = httpx.AsyncClient.send

    async def observe(
        self: httpx.AsyncClient, request: httpx.Request, **kwargs: object
    ) -> httpx.Response:
        sent.append(
            _Sent(
                method=request.method,
                path=request.url.path,
                platform_key=request.headers.get("X-API-Key"),
                bearer=request.headers.get("Authorization", "").startswith("Bearer "),
            )
        )
        return await send(self, request, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.AsyncClient, "send", observe)
    yield sent


@pytest.mark.integration
@pytest.mark.metered
def test_platform_key_attributes_sign_in_and_requests_but_not_session_upkeep(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    platform_api_key: PlatformApiKey,
    integration_environment: Environment,
    sent_requests: list[_Sent],
) -> None:
    async def run() -> str | None:
        client = await AsyncSecureClient.create(
            private_key=deposit_wallet_private_key,
            wallet=deposit_wallet_address,
            platform_api_key=platform_api_key,
            environment=integration_environment,
        )
        claims = parse_access_token_claims(client.credentials.access_token)
        await client.list_open_orders().first_page()
        await client.refresh_credentials()
        await client.end_authentication()
        return claims.client_id

    client_id = asyncio.run(run())

    def key_for(path: str) -> set[str | None]:
        return {sent.platform_key for sent in sent_requests if sent.path == path}

    assert key_for("/v1/auth/challenge") == {platform_api_key.key}
    assert key_for("/v1/auth/login") == {platform_api_key.key}
    assert key_for("/v1/auth/refresh") == {None}
    assert key_for("/v1/auth/logout") == {None}
    orders = [sent for sent in sent_requests if sent.path == "/v1/me/orders"]
    assert orders
    assert all(sent.platform_key == platform_api_key.key and sent.bearer for sent in orders)
    # The session is bound to the application identity of the key.
    assert isinstance(client_id, str)


@pytest.mark.integration
@pytest.mark.metered
def test_platform_key_alone_does_not_authorize_wallet_deployment(
    platform_api_key: PlatformApiKey,
    integration_environment: Environment,
    sent_requests: list[_Sent],
) -> None:
    # A new signer has no Deposit Wallet, so creating its client would deploy one.
    private_key = Account.create().key.hex()

    async def run() -> None:
        with pytest.raises(UserInputError, match="api_key"):
            await AsyncSecureClient.create(
                private_key=private_key,
                platform_api_key=platform_api_key,
                environment=integration_environment,
            )

    asyncio.run(run())

    assert not [sent for sent in sent_requests if sent.path == "/v1/wallets/transactions"]


@pytest.mark.integration
def test_platform_challenge_is_an_ownership_attestation_for_the_signer(
    deposit_wallet_private_key: str,
    platform_api_key: PlatformApiKey,
    integration_environment: Environment,
) -> None:
    signer = Account.from_key(deposit_wallet_private_key).address

    with PublicClient(
        environment=integration_environment, platform_api_key=platform_api_key
    ) as client:
        challenge = client.create_platform_challenge(signer=signer)

    typed_data = challenge["typedData"]
    assert typed_data["primaryType"] == "ClobAuth"
    assert typed_data["message"]["address"].lower() == signer.lower()
