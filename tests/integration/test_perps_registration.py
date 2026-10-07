"""Read-only Perps registration lookup using the public client."""

import pytest

from polymarket import AsyncPublicClient


@pytest.mark.integration
@pytest.mark.anyio
async def test_fetch_perps_registration(public_client: AsyncPublicClient) -> None:
    registered = await public_client.fetch_perps_registration(
        address="0x0000000000000000000000000000000000000000"
    )
    assert isinstance(registered, bool)
