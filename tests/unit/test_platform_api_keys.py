"""Platform API Key placement across controlled responses."""

# pyright: reportPrivateUsage=false

import pytest
import respx
from eth_account import Account

from polymarket import (
    PlatformApiKey,
    PublicClient,
    RequestRejectedError,
)
from polymarket._internal.environment import PRODUCTION_CONFIG

PRIVATE_KEY = "0x" + "55" * 32
SIGNER = Account.from_key(PRIVATE_KEY).address
API = PRODUCTION_CONFIG.predictions_url
KEY = PlatformApiKey("pk_test_attribution")


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
            client.login(private_key=PRIVATE_KEY)

    assert error.value.code is None
    assert KEY.key not in str(error.value)
