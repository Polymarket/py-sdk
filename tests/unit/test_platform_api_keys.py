"""Platform API Key placement across controlled responses."""

# pyright: reportPrivateUsage=false
import time
from typing import Any

import httpx
import pytest
import respx
from _bearer import fake_access_token
from eth_account import Account

from polymarket import (
    BearerCredentials,
    PlatformApiKey,
    PublicClient,
    RequestRejectedError,
    SecureClient,
    UserInputError,
)
from polymarket._internal.environment import PRODUCTION_CONFIG

PRIVATE_KEY = "0x" + "55" * 32
SIGNER = Account.from_key(PRIVATE_KEY).address
API = PRODUCTION_CONFIG.predictions_url
CLOB = PRODUCTION_CONFIG.clob_url
KEY = PlatformApiKey("pk_test_attribution")


def _session() -> BearerCredentials:
    token = fake_access_token(
        sub=SIGNER, wallet=SIGNER, clob_api_key="trading-key", exp=int(time.time()) + 900
    )
    return BearerCredentials(access_token=token, refresh_token="refresh")


def _record(
    router: respx.MockRouter, method: str, url: str, response: httpx.Response
) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    router.route(method=method, url=url).mock(side_effect=respond)
    return requests


def _issued() -> dict[str, Any]:
    return {
        "accessToken": _session().access_token,
        "refreshToken": "refresh",
        "tokenType": "Bearer",
        "expiresIn": 900,
        "refreshExpiresIn": 604800,
    }


def test_key_attributes_requests_but_never_reaches_session_upkeep_or_heartbeats() -> None:
    with respx.mock(assert_all_called=True) as router:
        status = _record(
            router,
            "GET",
            f"{API}/v1/me/trading-status",
            httpx.Response(200, json={"closed_only": False}),
        )
        refresh = _record(
            router, "POST", f"{API}/v1/auth/refresh", httpx.Response(200, json=_issued())
        )
        heartbeat = _record(
            router, "POST", f"{CLOB}/v1/heartbeats", httpx.Response(200, json={"heartbeat_id": "h"})
        )
        logout = _record(router, "POST", f"{API}/v1/auth/logout", httpx.Response(204))

        client = SecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=_session(),
            platform_api_key=KEY,
            validate_credentials=False,
        )
        client.get_closed_only_mode()
        client.refresh_credentials()
        client.send_order_heartbeat()
        client.end_authentication().close()

    assert status[0].headers["X-API-Key"] == KEY.key
    assert status[0].headers["Authorization"].startswith("Bearer ")
    for request in (*refresh, *heartbeat, *logout):
        assert "X-API-Key" not in request.headers


def test_rejections_that_echo_the_key_are_redacted() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{API}/v1/markets").respond(
            403, json={"error": f"key {KEY.key} is not allowed", "code": "forbidden"}
        )
        with (
            PublicClient(platform_api_key=KEY) as client,
            pytest.raises(RequestRejectedError) as error,
        ):
            client.list_markets().first_page()

    assert KEY.key not in str(error.value)
    assert error.value.code == "forbidden"


def test_challenge_rejections_do_not_echo_the_key_in_the_code() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{API}/v1/auth/challenge").respond(401, json={"code": KEY.key})
        with (
            PublicClient(platform_api_key=KEY) as client,
            pytest.raises(RequestRejectedError) as error,
        ):
            client.create_platform_challenge(signer=SIGNER)

    assert error.value.code is None
    assert KEY.key not in str(error.value)


@pytest.mark.parametrize(
    ("request_input", "message"),
    [
        ({"signer": None}, "signer"),
        ({"signer": "not-an-address"}, "signer"),
        ({"signer": SIGNER, "wallet": 42}, "wallet"),
        ({"signer": SIGNER, "verification_token": 123}, "verification_token"),
        ({"signer": SIGNER, "verification_token": ""}, "verification_token"),
    ],
)
def test_untrusted_challenge_input_is_rejected_before_any_request(
    request_input: dict[str, Any], message: str
) -> None:
    with (
        respx.mock(assert_all_called=False) as router,
        PublicClient(platform_api_key=KEY) as client,
        pytest.raises(UserInputError, match=message),
    ):
        client.create_platform_challenge(**request_input)

    assert not router.calls


def test_platform_challenges_require_a_configured_key() -> None:
    with (
        respx.mock(assert_all_called=False) as router,
        PublicClient() as client,
        pytest.raises(UserInputError, match="platform_api_key"),
    ):
        client.create_platform_challenge(signer=SIGNER)

    assert not router.calls
