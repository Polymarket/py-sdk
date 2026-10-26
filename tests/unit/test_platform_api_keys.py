"""SDK boundaries only: synthetic gateway/proxy responses, never production credentials."""

# pyright: reportPrivateUsage=false
import asyncio
import json
import logging
from typing import Any, cast

import httpx
import pytest
import respx
from _gateway_auth_helpers import (
    CHALLENGE,
    GATEWAY,
    LEGACY,
    PRIVATE_KEY,
    SIGNER,
    credentials,
    response,
)
from respx.models import Call

from polymarket import (
    AsyncPublicClient,
    AsyncSecureClient,
    BearerCredentials,
    BuilderApiKey,
    PlatformApiKey,
    PublicClient,
    RelayerApiKey,
    RemotePlatformApiKey,
    SecureClient,
)
from polymarket.errors import RequestRejectedError, UserInputError
from polymarket.models.clob.orders import SignedOrder
from polymarket.models.types import TokenId
from polymarket.types import EvmAddress, HexString

PROXY = "https://integrator.example/custom/challenge-exact?route=auth"
PLATFORM_SECRET = "pm_sk_synthetic_server_only"
PLATFORM = PlatformApiKey(key=PLATFORM_SECRET)
BUILDER = BuilderApiKey(
    key="synthetic-builder-key", secret="c3ludGhldGlj", passphrase="synthetic-builder-passphrase"
)


def request_at(route: respx.Route, index: int = 0) -> httpx.Request:
    return cast(Call, route.calls[index]).request


@pytest.mark.parametrize("async_client", [False, True])
@pytest.mark.parametrize("secure", [False, True])
def test_remote_endpoint_is_exact_and_receives_only_challenge_input(
    async_client: bool, secure: bool
) -> None:
    before, after = credentials(), credentials(tag="refreshed", refresh="synthetic-rotated-refresh")
    adapter = RemotePlatformApiKey(url=PROXY)
    changed: list[BearerCredentials] = []
    with respx.mock as router:
        proxy = router.post(PROXY).respond(
            201, json=CHALLENGE, headers={"cache-control": "no-store"}
        )
        login = router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(before))
        refresh = router.post(GATEWAY + "/v1/auth/refresh").respond(200, json=response(after))
        logout = router.post(GATEWAY + "/v1/auth/logout").respond(204)
        keys = router.get(GATEWAY + "/auth/api-keys").mock(
            side_effect=[
                httpx.Response(401, json={"code": "expired_access_token"}),
                httpx.Response(200, json={"apiKeys": ["synthetic-key"]}),
            ]
        )

        async def run() -> None:
            if secure:
                async with await AsyncSecureClient.create(
                    private_key=PRIVATE_KEY,
                    wallet=SIGNER.address,
                    api_key=adapter,
                    verification_token="synthetic-verification",
                    on_credentials_changed=changed.append,
                ) as client:
                    assert await client.fetch_api_keys() == ("synthetic-key",)
                    assert client.credentials == after
                    public = await client.end_authentication()
                    try:
                        assert (
                            await public.login(
                                signer=SIGNER,
                                wallet=SIGNER.address,
                                verification_token="synthetic-verification",
                            )
                            == before
                        )
                    finally:
                        await public.close()
            else:
                async with AsyncPublicClient(api_key=adapter) as public:
                    assert (
                        await public.login(
                            signer=SIGNER,
                            wallet=SIGNER.address,
                            verification_token="synthetic-verification",
                        )
                        == before
                    )

        if async_client:
            asyncio.run(run())
        elif secure:
            with SecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                api_key=adapter,
                verification_token="synthetic-verification",
                on_credentials_changed=changed.append,
            ) as client:
                assert client.fetch_api_keys() == ("synthetic-key",)
                assert client.credentials == after
                with client.end_authentication() as public:
                    assert (
                        public.login(
                            signer=SIGNER,
                            wallet=SIGNER.address,
                            verification_token="synthetic-verification",
                        )
                        == before
                    )
        else:
            with PublicClient(api_key=adapter) as public:
                assert (
                    public.login(
                        signer=SIGNER,
                        wallet=SIGNER.address,
                        verification_token="synthetic-verification",
                    )
                    == before
                )
        assert proxy.call_count == login.call_count == (2 if secure else 1)
        for index in range(proxy.call_count):
            request = request_at(proxy, index)
            assert str(request.url) == PROXY
            assert json.loads(request.content) == {
                "signer": SIGNER.address,
                "wallet": SIGNER.address,
                "verification_token": "synthetic-verification",
            }
            assert "X-API-Key" not in request.headers
            for forbidden in (
                "signature",
                before.access_token,
                before.refresh_token,
                after.access_token,
                after.refresh_token,
                PLATFORM_SECRET,
            ):
                assert forbidden.encode() not in request.content
        assert "X-API-Key" not in request_at(login).headers
        assert set(json.loads(request_at(login).content)) == {"ownership"}
        if secure:
            assert refresh.call_count == logout.call_count == 1 and keys.call_count == 2
            assert changed == [after]
            assert request_at(logout).headers["Authorization"] == "Bearer " + after.access_token
            assert request_at(logout).content == b""
            assert "X-API-Key" not in request_at(refresh).headers
            assert "X-API-Key" not in request_at(logout).headers


@pytest.mark.parametrize("async_client", [False, True])
def test_server_key_uses_gateway_and_shared_lifecycle(async_client: bool) -> None:
    before, after = credentials(), credentials(tag="refresh")
    with respx.mock as router:
        challenge = router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        login = router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(before))
        refresh = router.post(GATEWAY + "/v1/auth/refresh").respond(200, json=response(after))
        keys = router.get(GATEWAY + "/auth/api-keys").mock(
            side_effect=[
                httpx.Response(401, json={"code": "expired_access_token"}),
                httpx.Response(200, json={"apiKeys": []}),
            ]
        )
        logout = router.post(GATEWAY + "/v1/auth/logout").respond(204)

        async def run() -> None:
            async with await AsyncSecureClient.create(
                private_key=PRIVATE_KEY, wallet=SIGNER.address, api_key=PLATFORM
            ) as client:
                await client.fetch_api_keys()
                assert client.credentials == after
                public = await client.end_authentication()
                await public.close()

        if async_client:
            asyncio.run(run())
        else:
            with SecureClient.create(
                private_key=PRIVATE_KEY, wallet=SIGNER.address, api_key=PLATFORM
            ) as client:
                client.fetch_api_keys()
                assert client.credentials == after
                client.end_authentication().close()
        for route in (challenge, login, keys):
            assert request_at(route).headers["X-API-Key"] == PLATFORM_SECRET
        for route in (refresh, logout):
            assert "X-API-Key" not in request_at(route).headers
        assert refresh.call_count == 1
        assert PLATFORM_SECRET not in repr(PLATFORM) + repr(after)


@pytest.mark.parametrize("async_client", [False, True])
def test_migration_uses_server_key_but_remote_adapter_refuses_unattributed_migration(
    async_client: bool,
) -> None:
    pair = credentials()
    with respx.mock as router:
        migration = router.post(GATEWAY + "/v1/auth/migrate").respond(200, json=response(pair))

        async def run() -> None:
            async with AsyncPublicClient(api_key=PLATFORM) as public:
                assert (
                    await public.migrate_credentials(credentials=LEGACY, signer=SIGNER.address)
                    == pair
                )
            async with AsyncPublicClient(api_key=RemotePlatformApiKey(url=PROXY)) as public:
                with pytest.raises(UserInputError, match="challenge login only"):
                    await public.migrate_credentials(credentials=LEGACY, signer=SIGNER.address)
            with pytest.raises(UserInputError, match="challenge login only"):
                await AsyncSecureClient.create(
                    private_key=PRIVATE_KEY,
                    wallet=SIGNER.address,
                    api_key=RemotePlatformApiKey(url=PROXY),
                    credentials=LEGACY,
                )

        if async_client:
            asyncio.run(run())
        else:
            with PublicClient(api_key=PLATFORM) as public:
                assert public.migrate_credentials(credentials=LEGACY, signer=SIGNER.address) == pair
            with (
                PublicClient(api_key=RemotePlatformApiKey(url=PROXY)) as public,
                pytest.raises(UserInputError, match="challenge login only"),
            ):
                public.migrate_credentials(credentials=LEGACY, signer=SIGNER.address)
            with pytest.raises(UserInputError, match="challenge login only"):
                SecureClient.create(
                    private_key=PRIVATE_KEY,
                    wallet=SIGNER.address,
                    api_key=RemotePlatformApiKey(url=PROXY),
                    credentials=LEGACY,
                )
        assert migration.call_count == 1
        assert request_at(migration).headers["X-API-Key"] == PLATFORM_SECRET
        assert PLATFORM_SECRET.encode() not in request_at(migration).content
        assert LEGACY.secret.encode() not in request_at(migration).content


@pytest.mark.parametrize("async_client", [False, True])
@pytest.mark.parametrize("failure", ["login", "restore"])
def test_conflicting_platform_key_rejection_is_preserved_and_redacted(
    async_client: bool, failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    pair = credentials()
    changed: list[BearerCredentials] = []
    with respx.mock as router, caplog.at_level(logging.DEBUG):
        router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        if failure == "restore":
            router.post(GATEWAY + "/v1/auth/refresh").respond(200, json=response(pair))
        rejection = router.route(
            method="POST" if failure == "login" else "GET",
            url=GATEWAY + ("/v1/auth/login" if failure == "login" else "/v1/auth/identity"),
        ).respond(
            401, json={"code": "api_key_mismatch", "error": PLATFORM_SECRET + pair.access_token}
        )

        async def run() -> None:
            await AsyncSecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                credentials=pair if failure == "restore" else None,
                api_key=PLATFORM,
                on_credentials_changed=changed.append,
            )

        with pytest.raises(RequestRejectedError) as error:
            if async_client:
                asyncio.run(run())
            else:
                SecureClient.create(
                    private_key=PRIVATE_KEY,
                    wallet=SIGNER.address,
                    credentials=pair if failure == "restore" else None,
                    api_key=PLATFORM,
                    on_credentials_changed=changed.append,
                )
        assert error.value.code == "api_key_mismatch" and not changed
        assert request_at(rejection).headers["X-API-Key"] == PLATFORM_SECRET
        assert PLATFORM_SECRET not in str(error.value) + caplog.text
        assert pair.access_token not in str(error.value) + caplog.text


@pytest.mark.parametrize("async_client", [False, True])
def test_proxy_failure_does_not_leak_returned_secrets_or_send_a_signature(
    async_client: bool, caplog: pytest.LogCaptureFixture
) -> None:
    with respx.mock as router, caplog.at_level(logging.DEBUG):
        proxy = router.post(PROXY).respond(
            403, json={"error": PLATFORM_SECRET, "code": "caller_not_authorized"}
        )

        async def run() -> None:
            async with AsyncPublicClient(api_key=RemotePlatformApiKey(url=PROXY)) as public:
                await public.login(signer=SIGNER, wallet=SIGNER.address)

        with pytest.raises(RequestRejectedError) as error:
            if async_client:
                asyncio.run(run())
            else:
                with PublicClient(api_key=RemotePlatformApiKey(url=PROXY)) as public:
                    public.login(signer=SIGNER, wallet=SIGNER.address)
        assert error.value.code == "caller_not_authorized" and proxy.call_count == 1
        assert "signature" not in request_at(proxy).content.decode()
        assert PLATFORM_SECRET not in str(error.value) + caplog.text


@pytest.mark.parametrize("async_client", [False, True])
def test_platform_attribution_preserves_legacy_authorization_and_signed_orders(
    async_client: bool,
) -> None:
    pair = credentials()
    zero = HexString("0x" + "00" * 32)
    signed = SignedOrder(
        builder=zero,
        expiration=0,
        maker=EvmAddress(SIGNER.address),
        maker_amount=1_000_000,
        metadata=zero,
        order_type="GTC",
        salt=42,
        side="BUY",
        signature=HexString("0x" + "ab" * 65),
        signature_type=0,
        signer=EvmAddress(SIGNER.address),
        taker_amount=500_000,
        timestamp=1700000000000,
        token_id=TokenId("123"),
    )
    with respx.mock as router:
        router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(pair))
        post = router.post(GATEWAY + "/order").respond(
            200,
            json={
                "success": True,
                "errorMsg": "",
                "orderID": "synthetic-order",
                "status": "live",
                "transactionsHashes": [],
                "takingAmount": "",
                "makingAmount": "",
            },
        )
        builder = router.post(
            "https://combos-rfq-gateway-builder.polymarket.com/v1/builder/rfq/requests"
        ).respond(200, json={"synthetic": True})
        relayer = router.post(GATEWAY + "/submit").respond(200, json={"synthetic": True})

        async def run() -> None:
            async with await AsyncSecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                api_key=PLATFORM,
                legacy_api_key=BUILDER,
            ) as client:
                await client.post_order(signed)
                assert client._ctx.api_key is BUILDER
                await client._ctx.builder_gateway.post_json(
                    "/v1/builder/rfq/requests", json={"synthetic": True}
                )
                await client._ctx.relayer.post_json("/submit", json={"synthetic": True})

        if async_client:
            asyncio.run(run())
        else:
            with SecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                api_key=PLATFORM,
                legacy_api_key=BUILDER,
            ) as client:
                client.post_order(signed)
                assert client._ctx.api_key is BUILDER
                client._ctx.builder_gateway.post_json(
                    "/v1/builder/rfq/requests", json={"synthetic": True}
                )
                client._ctx.relayer.post_json("/submit", json={"synthetic": True})
        order = json.loads(request_at(post).content)
        assert order["owner"] == "synthetic-key" and order["order"]["signature"] == signed.signature
        assert request_at(post).headers["X-API-Key"] == PLATFORM_SECRET
        assert request_at(builder).headers["POLY_BUILDER_API_KEY"] == BUILDER.key
        assert request_at(builder).headers["Authorization"] == "Bearer " + pair.access_token
        assert "X-API-Key" not in request_at(builder).headers
        assert request_at(relayer).headers["POLY_BUILDER_API_KEY"] == BUILDER.key
        assert request_at(relayer).headers["X-API-Key"] == PLATFORM_SECRET
        assert not any(header.startswith("poly_") for header in request_at(post).headers)


@pytest.mark.parametrize(
    "bad",
    [
        [PLATFORM, PLATFORM],
        {"key": PLATFORM_SECRET, "client_id": "polymarket-web"},
        "raw-platform-secret",
    ],
)
def test_invalid_or_conflicting_key_configuration_is_rejected(bad: object) -> None:
    with pytest.raises(UserInputError), respx.mock:
        SecureClient.create(private_key=PRIVATE_KEY, wallet=SIGNER.address, api_key=cast(Any, bad))
    with pytest.raises(UserInputError):
        PublicClient(api_key=cast(Any, bad))


def test_no_caller_client_id_override_and_legacy_key_conflicts() -> None:
    with (
        respx.mock,
        PublicClient(api_key=RemotePlatformApiKey(url=PROXY)) as public,
        pytest.raises(TypeError, match="client_id"),
    ):
        cast(Any, public).login(signer=SIGNER, client_id="polymarket-web")
    with respx.mock, pytest.raises(UserInputError, match="not both"):
        SecureClient.create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER.address,
            api_key=BUILDER,
            legacy_api_key=RelayerApiKey(key="synthetic", address=SIGNER.address),
        )


@pytest.mark.parametrize(
    "url",
    [
        "/api/auth/challenge",
        "https://user:secret@proxy.example/challenge",
        "file:///secret",
        "https://proxy.example/challenge#fragment",
    ],
)
def test_proxy_url_validation_is_redacted(url: str) -> None:
    with pytest.raises(UserInputError) as error:
        RemotePlatformApiKey(url=url)
    assert url not in str(error.value)


@pytest.mark.parametrize("async_client", [False, True])
def test_expired_platform_restore_validates_refreshed_binding_before_callback(
    async_client: bool,
) -> None:
    import time

    before = credentials(expiry=time.time() - 1)
    restored, renewed = credentials(tag="restored"), credentials(tag="renewed")
    changed: list[BearerCredentials] = []
    with respx.mock as router:
        refresh = router.post(GATEWAY + "/v1/auth/refresh").mock(
            side_effect=[
                httpx.Response(200, json=response(restored)),
                httpx.Response(200, json=response(renewed)),
            ]
        )
        identity = router.get(GATEWAY + "/v1/auth/identity").respond(
            200, json={"signer": SIGNER.address, "clientId": "synthetic-client"}
        )
        keys = router.get(GATEWAY + "/auth/api-keys").mock(
            side_effect=[
                httpx.Response(401, json={"code": "expired_access_token"}),
                httpx.Response(200, json={"apiKeys": []}),
            ]
        )

        async def run() -> None:
            async with await AsyncSecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                credentials=before,
                api_key=PLATFORM,
                on_credentials_changed=changed.append,
            ) as client:
                assert client.credentials == restored and changed == [restored]
                await client.fetch_api_keys()
                assert client.credentials == renewed

        if async_client:
            asyncio.run(run())
        else:
            with SecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                credentials=before,
                api_key=PLATFORM,
                on_credentials_changed=changed.append,
            ) as client:
                assert client.credentials == restored and changed == [restored]
                client.fetch_api_keys()
                assert client.credentials == renewed
        assert identity.call_count == 1 and refresh.call_count == keys.call_count == 2
        assert request_at(identity).headers["Authorization"] == "Bearer " + restored.access_token
        assert request_at(identity).headers["X-API-Key"] == PLATFORM_SECRET
        assert changed == [restored, renewed]
        assert "X-API-Key" not in request_at(refresh).headers


@pytest.mark.parametrize("async_client", [False, True])
def test_platform_adapter_retains_explicit_relayer_key(async_client: bool) -> None:
    pair = credentials()
    legacy = RelayerApiKey(key="synthetic-relayer", address=SIGNER.address)
    with respx.mock as router:
        router.post(GATEWAY + "/v1/auth/challenge").respond(201, json=CHALLENGE)
        router.post(GATEWAY + "/v1/auth/login").respond(200, json=response(pair))
        submit = router.post(GATEWAY + "/submit").respond(200, json={"synthetic": True})

        async def run() -> None:
            async with await AsyncSecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                api_key=PLATFORM,
                legacy_api_key=legacy,
            ) as client:
                await client._ctx.relayer.post_json("/submit", json={"synthetic": True})

        if async_client:
            asyncio.run(run())
        else:
            with SecureClient.create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER.address,
                api_key=PLATFORM,
                legacy_api_key=legacy,
            ) as client:
                client._ctx.relayer.post_json("/submit", json={"synthetic": True})
        assert request_at(submit).headers["X-API-Key"] == PLATFORM_SECRET
        assert request_at(submit).headers["RELAYER_API_KEY"] == legacy.key
        assert request_at(submit).headers["RELAYER_API_KEY_ADDRESS"] == legacy.address
        assert request_at(submit).headers["Authorization"] == "Bearer " + pair.access_token
