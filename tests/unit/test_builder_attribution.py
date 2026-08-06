# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.orders.market import adjust_buy_amount_for_fees
from polymarket._internal.actions.orders.market_data import PlatformFeeInfo
from polymarket._internal.actions.orders.orders import create_unsigned_order
from polymarket._internal.actions.orders.types import BYTES32_ZERO, OrderDraft
from polymarket._internal.validation import validate_builder_code
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UserInputError
from polymarket.models.clob.builder import BuilderFeeRates
from polymarket.models.types import TokenId
from polymarket.types import EvmAddress, HexString

_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
_FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")

_VALID_BUILDER = "0x" + "ab" * 32
_OTHER_BUILDER = "0x" + "cd" * 32
_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"
_DUMMY_ADDRESS = EvmAddress("0x000000000000000000000000000000000000dEaD")


def _draft(builder_code: HexString | None) -> OrderDraft:
    return OrderDraft(
        chain_id=137,
        exchange_address=_DUMMY_ADDRESS,
        expiration=0,
        funder_address=_DUMMY_ADDRESS,
        offered_amount=1_000_000,
        order_type="GTC",
        side="BUY",
        signer=_DUMMY_ADDRESS,
        requested_amount=2_000_000,
        token_id=TokenId("token-1"),
        builder_code=builder_code,
    )


def test_validate_builder_code_accepts_valid_32_byte_hex() -> None:
    assert validate_builder_code(_VALID_BUILDER) == _VALID_BUILDER


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0x",
        "0x" + "ab" * 31,
        "0x" + "ab" * 33,
        "ab" * 32,
        "0x" + "zz" * 32,
    ],
)
def test_validate_builder_code_rejects_malformed(value: str) -> None:
    with pytest.raises(UserInputError, match="builder_code"):
        validate_builder_code(value)


@pytest.mark.parametrize("value", [None, 42, True, b"0x" + b"ab" * 32])
def test_validate_builder_code_rejects_non_string(value: object) -> None:
    with pytest.raises(UserInputError, match="builder_code"):
        validate_builder_code(value)


def test_unsigned_order_defaults_builder_to_zero_when_draft_has_none() -> None:
    unsigned = create_unsigned_order(_draft(None), wallet=_DUMMY_ADDRESS, wallet_type="EOA")
    assert unsigned.builder == BYTES32_ZERO


def test_unsigned_order_carries_builder_code_from_draft() -> None:
    unsigned = create_unsigned_order(
        _draft(HexString(_VALID_BUILDER)), wallet=_DUMMY_ADDRESS, wallet_type="EOA"
    )
    assert unsigned.builder == _VALID_BUILDER


def test_unsigned_order_builder_distinguishes_codes() -> None:
    a = create_unsigned_order(
        _draft(HexString(_VALID_BUILDER)), wallet=_DUMMY_ADDRESS, wallet_type="EOA"
    )
    b = create_unsigned_order(
        _draft(HexString(_OTHER_BUILDER)), wallet=_DUMMY_ADDRESS, wallet_type="EOA"
    )
    assert a.builder == _VALID_BUILDER
    assert b.builder == _OTHER_BUILDER
    assert a.builder != b.builder


def test_builder_fee_rates_scales_bps_to_ratio() -> None:
    rates = BuilderFeeRates.parse_response(
        {"builder_maker_fee_rate_bps": 10, "builder_taker_fee_rate_bps": 25}
    )
    assert rates.maker == Decimal("0.001")
    assert rates.taker == Decimal("0.0025")


def test_builder_fee_rates_handles_zero_bps() -> None:
    rates = BuilderFeeRates.parse_response(
        {"builder_maker_fee_rate_bps": 0, "builder_taker_fee_rate_bps": 0}
    )
    assert rates.maker == Decimal(0)
    assert rates.taker == Decimal(0)


def test_builder_fee_rates_rejects_non_numeric_bps_with_unexpected_response() -> None:
    from polymarket.errors import UnexpectedResponseError

    with pytest.raises(UnexpectedResponseError):
        BuilderFeeRates.parse_response(
            {"builder_maker_fee_rate_bps": "bad", "builder_taker_fee_rate_bps": 25}
        )


def test_adjust_buy_amount_without_builder_matches_legacy() -> None:
    fee = PlatformFeeInfo(rate=Decimal(0), exponent=Decimal(0))
    amount = Decimal("100")
    out = adjust_buy_amount_for_fees(
        amount=amount, price=Decimal("0.5"), max_spend=Decimal("200"), fee=fee
    )
    assert out == amount


def test_adjust_buy_amount_with_builder_taker_fee_reduces_amount_under_max_spend() -> None:
    fee = PlatformFeeInfo(rate=Decimal(0), exponent=Decimal(0))
    amount = Decimal("100")
    price = Decimal("0.5")
    builder_taker = Decimal("0.01")
    max_spend = Decimal("100")
    out = adjust_buy_amount_for_fees(
        amount=amount,
        price=price,
        max_spend=max_spend,
        fee=fee,
        builder_taker_fee_rate=builder_taker,
    )
    expected = max_spend / (Decimal(1) + builder_taker)
    assert out == expected
    assert out < amount


def test_adjust_buy_amount_with_builder_does_not_change_when_max_spend_room_remains() -> None:
    fee = PlatformFeeInfo(rate=Decimal(0), exponent=Decimal(0))
    amount = Decimal("100")
    out = adjust_buy_amount_for_fees(
        amount=amount,
        price=Decimal("0.5"),
        max_spend=Decimal("999"),
        fee=fee,
        builder_taker_fee_rate=Decimal("0.01"),
    )
    assert out == amount


def _mock_transport(captured: list[httpx.Request], routes: dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        for prefix, payload in routes.items():
            if path == prefix or path.startswith(f"{prefix}/"):
                return httpx.Response(200, json=payload, request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return httpx.MockTransport(handler)


def _install_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, clob=transport)


def _install_secure_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)


async def _make_client() -> AsyncSecureClient:
    return await AsyncSecureClient._create(
        private_key=_PRIVATE_KEY,
        wallet=_SIGNER_ADDRESS,
        credentials=_FAKE_CREDS,
        validate_credentials=False,
    )


def test_create_limit_order_propagates_builder_code_to_signed_order() -> None:
    async def run() -> str:
        client = await _make_client()
        try:
            _install_clob(
                client,
                _mock_transport(
                    [],
                    {
                        "/markets-by-token": {"condition_id": _CONDITION_ID},
                        "/clob-markets": {
                            "fd": {"r": 0, "e": 0},
                            "mts": 0.01,
                            "nr": False,
                            "t": [{"t": "8501497", "o": "Yes"}],
                        },
                    },
                ),
            )
            _install_secure_clob(
                client,
                _mock_transport(
                    [],
                    {
                        "/balance-allowance": {
                            "balance": "100000000000",
                            "allowances": {
                                "0xE111180000d2663C0091e4f400237545B87B996B": "100000000000",
                                "0xe2222d279d744050d28e00520010520000310F59": "100000000000",
                            },
                        }
                    },
                ),
            )
            signed = await client.create_limit_order(
                token_id="8501497",
                price="0.5",
                size="10",
                side="BUY",
                builder_code=_VALID_BUILDER,
            )
            return signed.builder
        finally:
            await client.close()

    assert asyncio.run(run()) == _VALID_BUILDER


def test_create_limit_order_without_builder_code_signs_zero_bytes32() -> None:
    async def run() -> str:
        client = await _make_client()
        try:
            _install_clob(
                client,
                _mock_transport(
                    [],
                    {
                        "/markets-by-token": {"condition_id": _CONDITION_ID},
                        "/clob-markets": {
                            "fd": {"r": 0, "e": 0},
                            "mts": 0.01,
                            "nr": False,
                            "t": [{"t": "8501497", "o": "Yes"}],
                        },
                    },
                ),
            )
            _install_secure_clob(
                client,
                _mock_transport(
                    [],
                    {
                        "/balance-allowance": {
                            "balance": "100000000000",
                            "allowances": {
                                "0xE111180000d2663C0091e4f400237545B87B996B": "100000000000",
                                "0xe2222d279d744050d28e00520010520000310F59": "100000000000",
                            },
                        }
                    },
                ),
            )
            signed = await client.create_limit_order(
                token_id="8501497", price="0.5", size="10", side="BUY"
            )
            return signed.builder
        finally:
            await client.close()

    assert asyncio.run(run()) == BYTES32_ZERO


def test_create_limit_order_rejects_invalid_builder_code_before_any_request() -> None:
    captured: list[httpx.Request] = []

    async def run() -> int:
        client = await _make_client()
        try:
            _install_clob(client, _mock_transport(captured, {}))
            _install_secure_clob(client, _mock_transport(captured, {}))
            with pytest.raises(UserInputError, match="builder_code"):
                await client.create_limit_order(
                    token_id="8501497",
                    price="0.5",
                    size="10",
                    side="BUY",
                    builder_code="not-hex",
                )
            return len(captured)
        finally:
            await client.close()

    assert asyncio.run(run()) == 0


def test_get_builder_fee_rates_hits_fees_endpoint_and_parses() -> None:
    captured: list[httpx.Request] = []

    async def run() -> BuilderFeeRates:
        client = await _make_client()
        try:
            _install_clob(
                client,
                _mock_transport(
                    captured,
                    {
                        "/fees/builder-fees": {
                            "builder_maker_fee_rate_bps": 10,
                            "builder_taker_fee_rate_bps": 25,
                        }
                    },
                ),
            )
            return await client.get_builder_fee_rates(_VALID_BUILDER)
        finally:
            await client.close()

    rates = asyncio.run(run())
    assert rates.maker == Decimal("0.001")
    assert rates.taker == Decimal("0.0025")
    assert any(
        urlparse(str(r.url)).path == f"/fees/builder-fees/{_VALID_BUILDER}" for r in captured
    )


def test_get_builder_fee_rates_validates_builder_code_before_request() -> None:
    captured: list[httpx.Request] = []

    async def run() -> int:
        client = await _make_client()
        try:
            _install_clob(client, _mock_transport(captured, {}))
            with pytest.raises(UserInputError, match="builder_code"):
                await client.get_builder_fee_rates("0xtoo-short")
            return len(captured)
        finally:
            await client.close()

    assert asyncio.run(run()) == 0


def test_get_builder_fee_rates_rejects_zero_builder_code_before_request() -> None:
    captured: list[httpx.Request] = []

    async def run() -> int:
        client = await _make_client()
        try:
            _install_clob(client, _mock_transport(captured, {}))
            with pytest.raises(UserInputError, match="zero"):
                await client.get_builder_fee_rates(BYTES32_ZERO)
            return len(captured)
        finally:
            await client.close()

    assert asyncio.run(run()) == 0


def _market_buy_public_routes() -> dict[str, Any]:
    return {
        "/markets-by-token": {"condition_id": _CONDITION_ID},
        "/clob-markets": {
            "fd": {"r": "0", "e": "0"},
            "mts": 0.01,
            "nr": False,
            "t": [{"t": "8501497", "o": "Yes"}],
        },
        "/book": {
            "asset_id": "8501497",
            "market": "0xMARKET",
            "bids": [],
            "asks": [{"price": "0.50", "size": "1000"}],
            "min_order_size": "1",
            "tick_size": "0.01",
            "neg_risk": False,
            "hash": "0xhash",
            "timestamp": "0",
        },
        "/fees/builder-fees": {
            "builder_maker_fee_rate_bps": 10,
            "builder_taker_fee_rate_bps": 100,
        },
    }


def _secure_full_allowance_routes() -> dict[str, Any]:
    return {
        "/balance-allowance": {
            "balance": "100000000000",
            "allowances": {
                "0xE111180000d2663C0091e4f400237545B87B996B": "100000000000",
                "0xe2222d279d744050d28e00520010520000310F59": "100000000000",
            },
        }
    }


def test_create_market_buy_with_builder_and_max_spend_fetches_fee_and_signs_builder() -> None:
    public_captured: list[httpx.Request] = []

    async def run() -> tuple[str, int, int]:
        client = await _make_client()
        try:
            _install_clob(client, _mock_transport(public_captured, _market_buy_public_routes()))
            _install_secure_clob(client, _mock_transport([], _secure_full_allowance_routes()))
            signed = await client.create_market_order(
                token_id="8501497",
                side="BUY",
                amount=Decimal("50"),
                max_spend=Decimal("50"),
                builder_code=_VALID_BUILDER,
            )
            return signed.builder, signed.maker_amount, signed.taker_amount
        finally:
            await client.close()

    builder, maker_amount, _ = asyncio.run(run())
    assert builder == _VALID_BUILDER
    fee_calls = [
        r
        for r in public_captured
        if urlparse(str(r.url)).path == f"/fees/builder-fees/{_VALID_BUILDER}"
    ]
    assert len(fee_calls) == 1, "fee endpoint must be hit exactly once"
    assert maker_amount < 50_000_000


def test_repeated_max_spend_orders_reuse_market_and_builder_fees() -> None:
    public_captured: list[httpx.Request] = []

    async def run() -> None:
        client = await _make_client()
        try:
            _install_clob(client, _mock_transport(public_captured, _market_buy_public_routes()))
            for _ in range(2):
                await client.create_market_order(
                    token_id="8501497",
                    side="BUY",
                    amount=Decimal("50"),
                    max_spend=Decimal("50"),
                    builder_code=_VALID_BUILDER,
                )
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(request.url)).path for request in public_captured]
    assert paths.count("/markets-by-token/8501497") == 1
    assert paths.count(f"/clob-markets/{_CONDITION_ID}") == 1
    assert paths.count(f"/fees/builder-fees/{_VALID_BUILDER}") == 1
    assert paths.count("/book") == 2


def test_create_market_buy_with_zero_builder_and_max_spend_skips_fee_fetch() -> None:
    public_captured: list[httpx.Request] = []

    async def run() -> str:
        client = await _make_client()
        try:
            _install_clob(client, _mock_transport(public_captured, _market_buy_public_routes()))
            _install_secure_clob(client, _mock_transport([], _secure_full_allowance_routes()))
            signed = await client.create_market_order(
                token_id="8501497",
                side="BUY",
                amount=Decimal("50"),
                max_spend=Decimal("50"),
                builder_code=BYTES32_ZERO,
            )
            return signed.builder
        finally:
            await client.close()

    builder = asyncio.run(run())
    assert builder == BYTES32_ZERO
    fee_calls = [
        r for r in public_captured if urlparse(str(r.url)).path.startswith("/fees/builder-fees/")
    ]
    assert fee_calls == [], "zero builder must not trigger fee endpoint"


def test_create_market_buy_without_max_spend_skips_fee_fetch_even_with_builder() -> None:
    public_captured: list[httpx.Request] = []

    async def run() -> str:
        client = await _make_client()
        try:
            _install_clob(client, _mock_transport(public_captured, _market_buy_public_routes()))
            _install_secure_clob(client, _mock_transport([], _secure_full_allowance_routes()))
            signed = await client.create_market_order(
                token_id="8501497",
                side="BUY",
                amount=Decimal("50"),
                builder_code=_VALID_BUILDER,
            )
            return signed.builder
        finally:
            await client.close()

    builder = asyncio.run(run())
    assert builder == _VALID_BUILDER
    fee_calls = [
        r for r in public_captured if urlparse(str(r.url)).path.startswith("/fees/builder-fees/")
    ]
    assert fee_calls == [], "no max_spend => no fee endpoint call"
