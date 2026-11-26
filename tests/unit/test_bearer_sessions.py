"""Client creation, renewal and logout against controlled authentication responses."""

# pyright: reportPrivateUsage=false
import asyncio
import threading
import time
from typing import Any

import httpx
import pytest
import respx
from _bearer import fake_access_token
from eth_account import Account

from polymarket import (
    AsyncSecureClient,
    BearerCredentials,
    PublicClient,
    SecureClient,
)
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket.errors import RequestRejectedError, UnexpectedResponseError, UserInputError

PRIVATE_KEY = "0x" + "44" * 32
SIGNER = Account.from_key(PRIVATE_KEY).address
OTHER_WALLET = "0x00000000000000000000000000000000000000aa"
AUTH = PRODUCTION_CONFIG.predictions_url


def _token(*, wallet: str | None = SIGNER, lifetime: int = 900) -> str:
    return fake_access_token(
        sub=SIGNER, wallet=wallet, clob_api_key="trading-key", exp=int(time.time()) + lifetime
    )


def _issued(access_token: str, refresh_token: str = "refresh") -> dict[str, Any]:
    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "tokenType": "Bearer",
        "expiresIn": 900,
        "refreshExpiresIn": 604800,
    }


def _granted(access_token: str) -> dict[str, Any]:
    """Answer a wallet bind: a new access token without a refresh token."""
    return {"accessToken": access_token, "tokenType": "Bearer", "expiresIn": 900}


def _challenge() -> dict[str, Any]:
    return {
        "challengeId": "2f1c8a1e-6f3b-4c1e-9d2a-3b4c5d6e7f80",
        "expiresAt": "2026-11-10T12:00:00Z",
        "typedData": {
            "domain": {"name": "ClobAuthDomain", "version": "1", "chainId": 137},
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
            "primaryType": "ClobAuth",
            "message": {
                "address": SIGNER,
                "timestamp": "1700000000",
                "nonce": "0",
                "message": "This message attests that I control the given wallet",
            },
        },
    }


def _route(
    router: respx.MockRouter, method: str, url: str, *responses: httpx.Response
) -> list[httpx.Request]:
    """Serve ``responses`` in order, repeating the last, and record each request."""
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses[min(len(requests), len(responses)) - 1]

    router.route(method=method, url=url).mock(side_effect=respond)
    return requests


def _ok(payload: object) -> httpx.Response:
    return httpx.Response(200, json=payload)


def test_login_rejects_a_session_issued_for_another_wallet() -> None:
    with respx.mock(assert_all_called=True) as router:
        _route(router, "POST", f"{AUTH}/v1/auth/challenge", _ok(_challenge()))
        _route(router, "POST", f"{AUTH}/v1/auth/login", _ok(_issued(_token(wallet=OTHER_WALLET))))

        with PublicClient() as client, pytest.raises(UnexpectedResponseError):
            client.login(private_key=PRIVATE_KEY, wallet=SIGNER)


def test_saved_session_for_another_wallet_is_rejected_before_any_request() -> None:
    saved = BearerCredentials(access_token=_token(), refresh_token="saved-refresh")
    with (
        respx.mock(assert_all_called=False) as router,
        pytest.raises(UserInputError, match="bound to wallet"),
    ):
        SecureClient.create(private_key=PRIVATE_KEY, wallet=OTHER_WALLET, credentials=saved)

    assert not router.calls


def test_failed_creation_ends_the_new_session_without_reporting_it() -> None:
    issued_elsewhere = _token(wallet=OTHER_WALLET)
    changes: list[BearerCredentials] = []
    with respx.mock(assert_all_called=True) as router:
        _route(router, "POST", f"{AUTH}/v1/auth/challenge", _ok(_challenge()))
        _route(router, "POST", f"{AUTH}/v1/auth/login", _ok(_issued(issued_elsewhere)))
        logout = _route(router, "POST", f"{AUTH}/v1/auth/logout", httpx.Response(204))

        with pytest.raises(UnexpectedResponseError, match="does not match"):
            SecureClient.create(
                private_key=PRIVATE_KEY, wallet=SIGNER, on_credentials_changed=changes.append
            )

    assert logout[0].headers["Authorization"] == f"Bearer {issued_elsewhere}"
    assert changes == []


def test_expired_access_token_is_renewed_and_the_request_replayed_once() -> None:
    saved = BearerCredentials(access_token=_token(), refresh_token="refresh")
    renewed = _token()
    expired = httpx.Response(401, json={"error": "expired", "code": "expired_access_token"})
    with respx.mock(assert_all_called=True) as router:
        _route(router, "POST", f"{AUTH}/v1/auth/refresh", _ok(_issued(renewed)))
        status = _route(
            router,
            "GET",
            f"{AUTH}/v1/me/trading-status",
            expired,
            _ok({"closed_only": False}),
        )

        with SecureClient._create(
            private_key=PRIVATE_KEY, credentials=saved, validate_credentials=False
        ) as client:
            assert client.get_closed_only_mode() is False

    headers = [request.headers["Authorization"] for request in status]
    assert headers == [f"Bearer {saved.access_token}", f"Bearer {renewed}"]


def test_a_second_expired_token_rejection_is_not_replayed() -> None:
    saved = BearerCredentials(access_token=_token(), refresh_token="refresh")
    expired = httpx.Response(401, json={"error": "expired", "code": "expired_access_token"})
    with respx.mock(assert_all_called=True) as router:
        _route(router, "POST", f"{AUTH}/v1/auth/refresh", _ok(_issued(_token())))
        status = _route(router, "GET", f"{AUTH}/v1/me/trading-status", expired)

        with (
            SecureClient._create(
                private_key=PRIVATE_KEY, credentials=saved, validate_credentials=False
            ) as client,
            pytest.raises(RequestRejectedError) as error,
        ):
            client.get_closed_only_mode()

    assert error.value.code == "expired_access_token"
    assert len(status) == 2


def test_closing_the_original_client_after_an_upgrade_keeps_the_upgraded_session() -> None:
    saved = BearerCredentials(access_token=_token(wallet=None), refresh_token="refresh")
    with respx.mock(assert_all_called=True) as router:
        _route(router, "POST", f"{AUTH}/v1/auth/bind", _ok(_granted(_token())))
        _route(router, "GET", f"{AUTH}/v1/me/trading-status", _ok({"closed_only": False}))
        _route(router, "POST", f"{AUTH}/v1/auth/refresh", _ok(_issued(_token())))

        with SecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=saved,
            validate_credentials=False,
            wallet_setup=False,
        ) as onboarding:
            client = onboarding.upgrade_credentials(wallet=SIGNER)

        with client:
            assert client.get_closed_only_mode() is False
            client.refresh_credentials()
        with pytest.raises(RuntimeError, match="upgrade_credentials"):
            _ = onboarding.credentials


def test_closing_the_original_async_client_after_an_upgrade_keeps_the_upgraded_session() -> None:
    saved = BearerCredentials(access_token=_token(wallet=None), refresh_token="refresh")

    async def run() -> None:
        async with await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=saved,
            validate_credentials=False,
            wallet_setup=False,
        ) as onboarding:
            client = await onboarding.upgrade_credentials(wallet=SIGNER)

        async with client:
            assert await client.get_closed_only_mode() is False
            await client.refresh_credentials()
        with pytest.raises(RuntimeError, match="upgrade_credentials"):
            _ = onboarding.credentials

    with respx.mock(assert_all_called=True) as router:
        _route(router, "POST", f"{AUTH}/v1/auth/bind", _ok(_granted(_token())))
        _route(router, "GET", f"{AUTH}/v1/me/trading-status", _ok({"closed_only": False}))
        _route(router, "POST", f"{AUTH}/v1/auth/refresh", _ok(_issued(_token())))
        asyncio.run(run())


def test_upgrading_a_bound_session_rebinds_it_to_another_wallet() -> None:
    saved = BearerCredentials(access_token=_token(wallet=OTHER_WALLET), refresh_token="refresh")
    bound = _token(wallet=SIGNER)
    with respx.mock(assert_all_called=True) as router:
        binds = _route(router, "POST", f"{AUTH}/v1/auth/bind", _ok(_granted(bound)))

        with SecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=saved,
            validate_credentials=False,
            wallet_setup=False,
        ) as onboarding:
            client = onboarding.upgrade_credentials(wallet=SIGNER)

        with client:
            assert client.credentials == BearerCredentials(
                access_token=bound, refresh_token="refresh"
            )

    assert len(binds) == 1


def test_upgrading_a_bound_async_session_rebinds_it_to_another_wallet() -> None:
    saved = BearerCredentials(access_token=_token(wallet=OTHER_WALLET), refresh_token="refresh")
    bound = _token(wallet=SIGNER)

    async def run() -> None:
        async with await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=saved,
            validate_credentials=False,
            wallet_setup=False,
        ) as onboarding:
            client = await onboarding.upgrade_credentials(wallet=SIGNER)

        async with client:
            assert client.credentials == BearerCredentials(
                access_token=bound, refresh_token="refresh"
            )

    with respx.mock(assert_all_called=True) as router:
        binds = _route(router, "POST", f"{AUTH}/v1/auth/bind", _ok(_granted(bound)))
        asyncio.run(run())

    assert len(binds) == 1


def test_an_overlapping_upgrade_is_rejected() -> None:
    saved = BearerCredentials(access_token=_token(wallet=OTHER_WALLET), refresh_token="refresh")
    bound = _token(wallet=SIGNER)
    started = threading.Event()
    release = threading.Event()

    def bind(_: httpx.Request) -> httpx.Response:
        started.set()
        release.wait(5)
        return _ok(_granted(bound))

    upgraded: list[SecureClient] = []
    with respx.mock(assert_all_called=True) as router:
        binds = router.post(f"{AUTH}/v1/auth/bind").mock(side_effect=bind)

        with SecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=saved,
            validate_credentials=False,
            wallet_setup=False,
        ) as onboarding:
            upgrade = threading.Thread(
                target=lambda: upgraded.append(onboarding.upgrade_credentials(wallet=SIGNER))
            )
            upgrade.start()
            try:
                assert started.wait(5)
                # The session still names OTHER_WALLET, so this call would hand it over at once.
                with pytest.raises(RuntimeError, match="already running"):
                    onboarding.upgrade_credentials(wallet=OTHER_WALLET)
            finally:
                release.set()
                upgrade.join(5)

        with upgraded[0] as client:
            assert client.credentials.access_token == bound

    assert binds.call_count == 1


def test_an_overlapping_async_upgrade_is_rejected() -> None:
    saved = BearerCredentials(access_token=_token(wallet=OTHER_WALLET), refresh_token="refresh")
    bound = _token(wallet=SIGNER)

    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def bind(_: httpx.Request) -> httpx.Response:
            started.set()
            await release.wait()
            return _ok(_granted(bound))

        binds.mock(side_effect=bind)
        async with await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=saved,
            validate_credentials=False,
            wallet_setup=False,
        ) as onboarding:
            upgrade = asyncio.create_task(onboarding.upgrade_credentials(wallet=SIGNER))
            try:
                await asyncio.wait_for(started.wait(), 5)
                # The session still names OTHER_WALLET, so this call would hand it over at once.
                with pytest.raises(RuntimeError, match="already running"):
                    await asyncio.wait_for(onboarding.upgrade_credentials(wallet=OTHER_WALLET), 5)
            finally:
                release.set()
            client = await asyncio.wait_for(upgrade, 5)

        async with client:
            assert client.credentials.access_token == bound

    with respx.mock(assert_all_called=True) as router:
        binds = router.post(f"{AUTH}/v1/auth/bind")
        asyncio.run(run())

    assert binds.call_count == 1


class _Interruption(BaseException):
    """An interruption that the session does not catch, such as ``KeyboardInterrupt``."""


def _interrupt(_: BearerCredentials) -> None:
    raise _Interruption


def test_a_handover_that_fails_after_the_bind_closes_the_original_client() -> None:
    saved = BearerCredentials(access_token=_token(wallet=OTHER_WALLET), refresh_token="refresh")
    with respx.mock(assert_all_called=True) as router:
        _route(router, "POST", f"{AUTH}/v1/auth/bind", _ok(_granted(_token(wallet=SIGNER))))

        with SecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=saved,
            validate_credentials=False,
            wallet_setup=False,
            on_credentials_changed=_interrupt,
        ) as onboarding:
            with pytest.raises(_Interruption):
                onboarding.upgrade_credentials(wallet=SIGNER)

            # The session names SIGNER now, so the client for OTHER_WALLET stops.
            with pytest.raises(RuntimeError, match="failed after the bind"):
                _ = onboarding.wallet


def test_an_async_handover_that_fails_after_the_bind_closes_the_original_client() -> None:
    saved = BearerCredentials(access_token=_token(wallet=OTHER_WALLET), refresh_token="refresh")

    async def run() -> None:
        async with await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=saved,
            validate_credentials=False,
            wallet_setup=False,
            on_credentials_changed=_interrupt,
        ) as onboarding:
            with pytest.raises(_Interruption):
                await onboarding.upgrade_credentials(wallet=SIGNER)

            # The session names SIGNER now, so the client for OTHER_WALLET stops.
            with pytest.raises(RuntimeError, match="failed after the bind"):
                _ = onboarding.wallet

    with respx.mock(assert_all_called=True) as router:
        _route(router, "POST", f"{AUTH}/v1/auth/bind", _ok(_granted(_token(wallet=SIGNER))))
        asyncio.run(run())
