import asyncio
from decimal import Decimal

import httpx
import pytest
import respx

from polymarket import AsyncPublicClient, PublicClient, PublicProfile
from polymarket.errors import UnexpectedResponseError


@pytest.mark.parametrize(
    ("payload", "tier", "name", "volume"),
    [
        ({}, None, None, None),
        ({"takerTier": None, "takerTierName": None, "weightedVolume": None}, None, None, None),
        ({"takerTier": 0, "takerTierName": "Tier 0", "weightedVolume": 0}, 0, "Tier 0", Decimal(0)),
        (
            {"takerTier": 2, "takerTierName": "Tier 2", "weightedVolume": 1234.5},
            2,
            "Tier 2",
            Decimal("1234.5"),
        ),
    ],
)
def test_public_profile_preserves_taker_metadata(
    payload: dict[str, object],
    tier: int | None,
    name: str | None,
    volume: Decimal | None,
) -> None:
    profile = PublicProfile.parse_response(payload)
    assert profile.taker_tier == tier
    assert profile.taker_tier_name == name
    assert profile.weighted_volume == volume


@pytest.mark.parametrize(
    "payload", [{"takerTier": "bad"}, {"takerTierName": []}, {"weightedVolume": {}}]
)
def test_public_profile_rejects_invalid_taker_metadata(payload: dict[str, object]) -> None:
    with pytest.raises(UnexpectedResponseError):
        PublicProfile.parse_response(payload)


@respx.mock
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_public_profile_client_retains_tier_fields(mode: str) -> None:
    address = "0x" + "12" * 20
    route = respx.get(
        "https://gamma-api.polymarket.com/public-profile", params={"address": address}
    ).mock(
        return_value=httpx.Response(
            200, json={"takerTier": 1, "takerTierName": "Tier 1", "weightedVolume": 100.25}
        )
    )
    if mode == "sync":
        with PublicClient() as client:
            profile = client.get_public_profile(address)
    else:

        async def run() -> PublicProfile | None:
            async with AsyncPublicClient() as client:
                return await client.get_public_profile(address)

        profile = asyncio.run(run())
    assert route.call_count == 1
    assert profile is not None
    assert profile.taker_tier == 1
    assert profile.taker_tier_name == "Tier 1"
    assert profile.weighted_volume == Decimal("100.25")
