"""Platform API Key placement across controlled responses."""

# pyright: reportPrivateUsage=false
import time
from typing import Any

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


def test_order_heartbeats_never_carry_the_key() -> None:
    # Live tests cover sign-in and account requests; heartbeats are not sent live.
    with respx.mock(assert_all_called=True) as router:
        heartbeat = router.post(f"{CLOB}/v1/heartbeats").respond(json={"heartbeat_id": "h"})
        with SecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=_session(),
            platform_api_key=KEY,
            validate_credentials=False,
        ) as client:
            client.send_order_heartbeat()

    assert "X-API-Key" not in heartbeat.calls.last.request.headers


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
