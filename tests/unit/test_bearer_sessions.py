"""Client creation, renewal and logout against controlled authentication responses."""

# pyright: reportPrivateUsage=false
import asyncio
import json
import time
from typing import Any

import httpx
import pytest
import respx
from _bearer import bearer_credentials_for, fake_access_token
from eth_account import Account
from eth_account.messages import encode_typed_data

from polymarket import (
    ApiKeyCreds,
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
CLOB = PRODUCTION_CONFIG.clob_url


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


def _body(request: httpx.Request) -> Any:
    return json.loads(request.content)


def test_sign_in_signs_the_ownership_challenge() -> None:
    issued = _token()
    with respx.mock(assert_all_called=True) as router:
        challenge = _route(router, "POST", f"{AUTH}/v1/auth/challenge", _ok(_challenge()))
        login = _route(router, "POST", f"{AUTH}/v1/auth/login", _ok(_issued(issued)))

        with SecureClient.create(private_key=PRIVATE_KEY, wallet=SIGNER) as client:
            assert client.credentials.access_token == issued

    assert _body(challenge[0]) == {"signer": SIGNER, "wallet": SIGNER}
    ownership = _body(login[0])["ownership"]
    assert ownership["challenge_id"] == _challenge()["challengeId"]
    message = _challenge()["typedData"]
    message["message"]["nonce"] = 0
    recovered = Account.recover_message(
        encode_typed_data(full_message=message), signature=ownership["signature"]
    )
    assert recovered == SIGNER


def test_saved_api_credentials_are_exchanged_without_a_wallet_signature() -> None:
    saved = ApiKeyCreds(key="api-key", passphrase="passphrase", secret="c2VjcmV0LXZhbHVl")
    changes: list[BearerCredentials] = []
    with respx.mock(assert_all_called=True) as router:
        migrate = _route(router, "POST", f"{AUTH}/v1/auth/migrate", _ok(_issued(_token())))

        with SecureClient.create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER,
            credentials=saved,
            on_credentials_changed=changes.append,
        ) as client:
            assert client.credentials.refresh_token == "refresh"

    body = _body(migrate[0])
    assert body["clob_api_key"] == "api-key"
    assert body["wallet"] == SIGNER
    assert saved.secret not in migrate[0].content.decode()
    assert changes == []


def test_restored_session_is_renewed_before_use_and_reported() -> None:
    saved = BearerCredentials(access_token=_token(), refresh_token="saved-refresh")
    renewed = _token()
    changes: list[BearerCredentials] = []
    with respx.mock(assert_all_called=True) as router:
        refresh = _route(
            router, "POST", f"{AUTH}/v1/auth/refresh", _ok(_issued(renewed, "saved-refresh"))
        )

        with SecureClient.create(
            private_key=PRIVATE_KEY, credentials=saved, on_credentials_changed=changes.append
        ) as client:
            assert client.wallet == SIGNER
            assert client.credentials.access_token == renewed

    assert _body(refresh[0]) == {"refresh_token": "saved-refresh"}
    assert changes == [BearerCredentials(access_token=renewed, refresh_token="saved-refresh")]


def test_saved_session_without_a_wallet_is_bound_without_a_signature() -> None:
    saved = BearerCredentials(access_token=_token(wallet=None), refresh_token="saved-refresh")
    bound = _token()
    with respx.mock(assert_all_called=True) as router:
        _route(
            router,
            "POST",
            f"{AUTH}/v1/auth/refresh",
            _ok(_issued(_token(wallet=None), "saved-refresh")),
        )
        upgrade = _route(
            router,
            "POST",
            f"{AUTH}/v1/auth/upgrade",
            _ok({"accessToken": bound, "tokenType": "Bearer", "expiresIn": 900}),
        )

        with SecureClient.create(
            private_key=PRIVATE_KEY, wallet=SIGNER, credentials=saved
        ) as client:
            assert client.credentials == BearerCredentials(
                access_token=bound, refresh_token="saved-refresh"
            )

    assert _body(upgrade[0]) == {"wallet": SIGNER}


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
            f"{CLOB}/auth/ban-status/closed-only",
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
        status = _route(router, "GET", f"{CLOB}/auth/ban-status/closed-only", expired)

        with (
            SecureClient._create(
                private_key=PRIVATE_KEY, credentials=saved, validate_credentials=False
            ) as client,
            pytest.raises(RequestRejectedError) as error,
        ):
            client.get_closed_only_mode()

    assert error.value.code == "expired_access_token"
    assert len(status) == 2


def test_authentication_rejections_do_not_echo_credentials() -> None:
    saved = ApiKeyCreds(key="api-key", passphrase="leaked-passphrase", secret="c2VjcmV0")
    with respx.mock(assert_all_called=True) as router:
        _route(
            router,
            "POST",
            f"{AUTH}/v1/auth/migrate",
            httpx.Response(
                401,
                json={"error": "bad passphrase leaked-passphrase", "code": "invalid_credentials"},
            ),
        )

        with PublicClient() as client, pytest.raises(RequestRejectedError) as error:
            client.migrate_credentials(credentials=saved, signer_address=SIGNER)

    assert error.value.status == 401
    assert error.value.code == "invalid_credentials"
    assert "leaked-passphrase" not in str(error.value)
    assert error.value.__cause__ is None


def test_end_authentication_revokes_the_session_and_closes_the_client() -> None:
    saved = bearer_credentials_for(PRIVATE_KEY, wallet=SIGNER)
    with respx.mock(assert_all_called=True) as router:
        logout = _route(router, "POST", f"{AUTH}/v1/auth/logout", httpx.Response(204))
        client = SecureClient._create(
            private_key=PRIVATE_KEY, credentials=saved, validate_credentials=False
        )

        public = client.end_authentication()
        public.close()

    assert logout[0].headers["Authorization"] == f"Bearer {saved.access_token}"
    assert logout[0].content == b""
    with pytest.raises(RuntimeError, match="ended authentication"):
        _ = client.wallet


def test_async_restored_session_is_renewed_and_explicit_renewals_are_shared() -> None:
    saved = BearerCredentials(access_token=_token(), refresh_token="saved-refresh")
    changes: list[BearerCredentials] = []

    async def run() -> tuple[BearerCredentials, BearerCredentials, int]:
        with respx.mock(assert_all_called=True) as router:
            refresh = _route(
                router,
                "POST",
                f"{AUTH}/v1/auth/refresh",
                _ok(_issued(_token(), "saved-refresh")),
                _ok(_issued(_token(), "saved-refresh")),
            )
            async with await AsyncSecureClient.create(
                private_key=PRIVATE_KEY, credentials=saved, on_credentials_changed=changes.append
            ) as client:
                first, second = await asyncio.gather(
                    client.refresh_credentials(), client.refresh_credentials()
                )
            return first, second, len(refresh)

    first, second, calls = asyncio.run(run())

    assert first == second
    # One renewal when restoring and one shared by both explicit calls.
    assert calls == 2
    assert changes[-1] == first
