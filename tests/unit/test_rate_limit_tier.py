# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from decimal import Decimal
from typing import assert_type

import httpx
import pytest

from polymarket import (
    ApiKeyCreds,
    AsyncSecureClient,
    RateLimitTier,
    RateLimitTierDetails,
    SecureClient,
)
from polymarket._internal.hmac import build_hmac_signature
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import RequestRejectedError, UnexpectedResponseError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
PATH = "/v1/user/rate-limit-tier"


@pytest.fixture
def tier_payload() -> dict[str, object]:
    # Public contract example: Polymarket/docs#512.
    return {
        "tier": "gold",
        "usdc_volume": "612345.670000000000000001",
        "next_tier_threshold": 2500000,
        "period": 30,
        "tier_details": {
            "name": "gold",
            "volume_threshold": 500000,
            "cancel_rate_per_sec": 800,
            "order_rate_per_sec": 400,
            "order_burst": 600,
            "cancel_burst": 1200,
            "allow_negative": True,
        },
    }


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "status,malformed", [(200, False), (200, True), (401, False), (503, False)]
)
def test_secure_clients_get_rate_limit_tier(
    tier_payload: dict[str, object], mode: str, status: int, malformed: bool
) -> None:
    requests: list[httpx.Request] = []
    if malformed:
        tier_payload["tier_details"] = None

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            json=tier_payload if status == 200 else {"error": "tier unavailable"},
        )

    def run_sync() -> RateLimitTier:
        with (
            SecureClient._create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER_ADDRESS,
                credentials=CREDS,
                validate_credentials=False,
            ) as client,
            httpx.Client(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            ) as http,
        ):
            resolver = client._ctx.secure_clob._header_resolver
            client._ctx.secure_clob.close()
            client._ctx = dataclasses.replace(
                client._ctx,
                secure_clob=SyncTransport(
                    base_url="https://example.test", client=http, header_resolver=resolver
                ),
            )
            result = client.get_rate_limit_tier()
            assert_type(result, RateLimitTier)
            return result

    async def run_async() -> RateLimitTier:
        async with (
            await AsyncSecureClient._create(
                private_key=PRIVATE_KEY,
                wallet=SIGNER_ADDRESS,
                credentials=CREDS,
                validate_credentials=False,
            ) as client,
            httpx.AsyncClient(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            ) as http,
        ):
            resolver = client._ctx.secure_clob._header_resolver
            await client._ctx.secure_clob.close()
            client._ctx = dataclasses.replace(
                client._ctx,
                secure_clob=AsyncTransport(
                    base_url="https://example.test", client=http, header_resolver=resolver
                ),
            )
            result = await client.get_rate_limit_tier()
            assert_type(result, RateLimitTier)
            return result

    if malformed:
        with pytest.raises(UnexpectedResponseError):
            run_sync() if mode == "sync" else asyncio.run(run_async())
    elif status == 200:
        result = run_sync() if mode == "sync" else asyncio.run(run_async())
        assert_type(result.usdc_volume, Decimal | None)
        assert_type(result.next_tier_threshold, int | None)
        assert result.tier == "gold"
        assert result.usdc_volume == Decimal("612345.670000000000000001")
        assert result.next_tier_threshold == 2500000
        assert result.period == 30
        details = result.tier_details
        assert_type(details, RateLimitTierDetails)
        assert details.name == "gold"
        assert details.volume_threshold == 500000
        assert details.cancel_rate_per_sec == 800
        assert details.order_rate_per_sec == 400
        assert details.order_burst == 600
        assert details.cancel_burst == 1200
        assert details.allow_negative is True
    else:
        with pytest.raises(RequestRejectedError, match="tier unavailable") as caught:
            run_sync() if mode == "sync" else asyncio.run(run_async())
        assert caught.value.status == status

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == PATH
    assert not request.url.query
    assert request.content == b""
    assert request.headers["POLY_ADDRESS"] == SIGNER_ADDRESS
    assert request.headers["POLY_API_KEY"] == CREDS.key
    assert request.headers["POLY_PASSPHRASE"] == CREDS.passphrase
    assert request.headers["POLY_SIGNATURE"] == build_hmac_signature(
        secret=CREDS.secret,
        timestamp=int(request.headers["POLY_TIMESTAMP"]),
        method="GET",
        path=PATH,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"tier": "free", "period": 30, "tier_details": {}},
        {
            "tier": "top",
            "usdc_volume": "0",
            "period": 30,
            "tier_details": {"allow_negative": False},
        },
        {"tier": "custom-future-tier", "period": 30, "tier_details": {"order_rate_per_sec": 0}},
    ],
)
def test_rate_limit_tier_accepts_omissions_and_custom_tiers(payload: dict[str, object]) -> None:
    result = RateLimitTier.parse_response(payload)
    assert result.tier == payload["tier"]
    assert result.usdc_volume == (Decimal(0) if "usdc_volume" in payload else None)
    assert result.next_tier_threshold is None


@pytest.mark.parametrize(
    "patch",
    [
        {"tier": None},
        {"period": None},
        {"period": True},
        {"tier_details": None},
        {"tier_details": {"order_burst": "many"}},
        {"tier_details": {"allow_negative": "false"}},
        {"next_tier_threshold": False},
        {"usdc_volume": "NaN"},
        {"usdc_volume": "invalid"},
    ],
)
def test_rate_limit_tier_rejects_invalid_fields(
    tier_payload: dict[str, object], patch: dict[str, object]
) -> None:
    with pytest.raises(UnexpectedResponseError):
        RateLimitTier.parse_response({**tier_payload, **patch})


@pytest.mark.parametrize("field", ["tier", "period", "tier_details"])
def test_rate_limit_tier_requires_contract_fields(
    tier_payload: dict[str, object], field: str
) -> None:
    tier_payload.pop(field)
    with pytest.raises(UnexpectedResponseError):
        RateLimitTier.parse_response(tier_payload)
