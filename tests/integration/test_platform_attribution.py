"""Application attribution with a Platform API Key against the live service.

Side effects: the session tests open sessions for the Deposit Wallet signer and
revoke them. The challenge test only requests a sign-in challenge.
"""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import pytest
from eth_account import Account

from polymarket import (
    AsyncSecureClient,
    BuilderApiKey,
    Environment,
    PlatformApiKey,
    PublicClient,
)
from polymarket._internal.actions import identity
from polymarket._internal.actions.identity import parse_access_token_claims
from polymarket._internal.environment import get_environment_config
from polymarket.clients._transport import SyncTransport


@dataclass(frozen=True)
class _Sent:
    method: str
    path: str
    platform_key: str | None
    builder_key: str | None
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
                builder_key=request.headers.get("POLY_BUILDER_API_KEY"),
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
    builder_api_key: BuilderApiKey,
    platform_api_key: PlatformApiKey,
    integration_environment: Environment,
    sent_requests: list[_Sent],
) -> None:
    async def run() -> str | None:
        client = await AsyncSecureClient.create(
            private_key=deposit_wallet_private_key,
            wallet=deposit_wallet_address,
            api_key=builder_api_key,
            platform_api_key=platform_api_key,
            environment=integration_environment,
        )
        claims = parse_access_token_claims(client.credentials.access_token)
        await client.list_open_orders().first_page()
        await client.refresh_credentials()
        async with await client.end_authentication() as public:
            await public.list_tags(page_size=1).first_page()
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
    # Builder signing still accompanies the key on account requests.
    assert all(
        sent.platform_key == platform_api_key.key
        and sent.builder_key == builder_api_key.key
        and sent.bearer
        for sent in orders
    )
    # The client returned after the session ends keeps attributing requests.
    assert key_for("/v1/tags") == {platform_api_key.key}
    # The session is bound to the application identity of the key.
    assert isinstance(client_id, str)


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


@pytest.mark.integration
@pytest.mark.metered
def test_a_challenge_served_with_the_key_signs_in_a_client_without_it(
    deposit_wallet_private_key: str,
    deposit_wallet_address: str,
    platform_api_key: PlatformApiKey,
    integration_environment: Environment,
) -> None:
    signer = identity.signer_from_private_key(deposit_wallet_private_key)
    with PublicClient(
        environment=integration_environment, platform_api_key=platform_api_key
    ) as backend:
        served = backend.create_platform_challenge(
            signer=signer.address, wallet=deposit_wallet_address
        )

    # The untrusted client signs the served challenge and signs in without the key.
    config = get_environment_config(integration_environment)
    challenge = identity.parse_ownership_challenge(served)
    signature = identity.sign_ownership_challenge(signer, challenge, chain_id=config.chain_id)
    untrusted = SyncTransport(base_url=config.predictions_url)
    try:
        issued = identity.parse_issued_tokens(
            untrusted.post_json(
                identity.LOGIN_PATH,
                json=identity.build_login_request(
                    challenge_id=challenge.challenge_id, signature=signature
                ),
            )
        )
        try:
            assert identity.issued_for(issued, signer=signer.address, wallet=deposit_wallet_address)
            assert parse_access_token_claims(issued.access_token).client_id is not None
        finally:
            identity.revoke_session_sync(untrusted, issued.access_token)
    finally:
        untrusted.close()
