import asyncio

import httpx
import pytest
import respx

from polymarket import AsyncPublicClient, CryptoMarketConfig, PublicClient
from polymarket._internal.actions.gamma import get_crypto_market_configs_spec
from polymarket.errors import UnexpectedResponseError

CATALOG = [
    {"id": "btc-15m", "asset": "btc", "duration": "15m", "twapEnabled": False},
    {
        "id": "btc-15m-twap-60",
        "asset": "btc",
        "duration": "15m",
        "twapEnabled": True,
        "twapLookbackSeconds": 60,
    },
]


@respx.mock
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_catalog_client_preserves_optional_averaging_configuration(mode: str) -> None:
    route = respx.get("https://gamma-api.polymarket.com/crypto-market-configs").mock(
        return_value=httpx.Response(200, json=CATALOG)
    )
    if mode == "sync":
        with PublicClient() as client:
            configs = client.get_crypto_market_configs()
    else:

        async def run() -> tuple[CryptoMarketConfig, ...]:
            async with AsyncPublicClient() as client:
                return await client.get_crypto_market_configs()

        configs = asyncio.run(run())
    assert len(configs) == 2
    assert configs[0].id == "btc-15m"
    assert configs[0].asset == "btc"
    assert configs[0].duration == "15m"
    assert configs[0].twap_enabled is False
    assert configs[0].twap_lookback_seconds is None
    assert configs[1].twap_enabled is True
    assert configs[1].twap_lookback_seconds == 60
    assert route.call_count == 1


def test_catalog_empty_response() -> None:
    assert get_crypto_market_configs_spec().parse([]) == ()


@pytest.mark.parametrize("payload", [{"data": CATALOG}, None, ["invalid"], [{"id": "btc"}]])
def test_catalog_rejects_invalid_envelopes_and_entries(payload: object) -> None:
    with pytest.raises(UnexpectedResponseError):
        get_crypto_market_configs_spec().parse(payload)
