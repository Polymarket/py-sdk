# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from decimal import Decimal
from typing import Any

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.orders.context import resolve_rounding_config
from polymarket._internal.actions.orders.market import (
    _compute_market_order_amounts,
    adjust_buy_amount_for_fees,
    prepare_market_order_draft,
    validate_market_order_params,
)
from polymarket._internal.actions.orders.market_data import PlatformFeeInfo
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UserInputError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"


def _book_payload(*, bids: list[dict[str, str]], asks: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "asset_id": "8501497",
        "market": "0xMARKET",
        "bids": bids,
        "asks": asks,
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": False,
        "hash": "0xhash",
        "timestamp": "1700000000",
    }


def _market_routes(*, neg_risk: bool = False) -> dict[str, dict[str, Any]]:
    return {
        "/markets-by-token/8501497": {"condition_id": _CONDITION_ID},
        f"/clob-markets/{_CONDITION_ID}": {
            "fd": {"r": 0, "e": 0},
            "mts": 0.01,
            "nr": neg_risk,
            "t": [{"t": "8501497", "o": "Yes"}],
        },
    }


def _multi_route_handler(routes: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import urlparse

        path = urlparse(str(request.url)).path
        if path in routes:
            return httpx.Response(200, json=routes[path], request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return httpx.MockTransport(handler)


def _tracked_route_handler(
    routes: dict[str, dict[str, Any]], captured: list[str]
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import urlparse

        path = urlparse(str(request.url)).path
        captured.append(path)
        if path in routes:
            return httpx.Response(200, json=routes[path], request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return httpx.MockTransport(handler)


def _install_public_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, clob=transport)


async def _make_client() -> AsyncSecureClient:
    return await AsyncSecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def test_validate_market_order_params_requires_amount_for_buy() -> None:
    with pytest.raises(UserInputError, match="amount is required"):
        validate_market_order_params(token_id="8501497", side="BUY")


def test_validate_market_order_params_rejects_shares_on_buy() -> None:
    with pytest.raises(UserInputError, match="shares must not be set"):
        validate_market_order_params(
            token_id="8501497", side="BUY", amount=Decimal(10), shares=Decimal(1)
        )


def test_validate_market_order_params_requires_shares_for_sell() -> None:
    with pytest.raises(UserInputError, match="shares is required"):
        validate_market_order_params(token_id="8501497", side="SELL")


def test_validate_market_order_params_rejects_max_spend_on_sell() -> None:
    with pytest.raises(UserInputError, match="max_spend is only valid"):
        validate_market_order_params(
            token_id="8501497", side="SELL", shares=Decimal(10), max_spend=Decimal(10)
        )


def test_validate_market_order_params_rejects_min_price_on_buy() -> None:
    with pytest.raises(UserInputError, match="min_price is only valid"):
        validate_market_order_params(
            token_id="8501497", side="BUY", amount=Decimal(10), min_price=Decimal("0.50")
        )


def test_validate_market_order_params_rejects_max_price_on_sell() -> None:
    with pytest.raises(UserInputError, match="max_price is only valid"):
        validate_market_order_params(
            token_id="8501497", side="SELL", shares=Decimal(10), max_price=Decimal("0.50")
        )


def test_validate_market_order_params_defaults_order_type_to_fak() -> None:
    params = validate_market_order_params(token_id="8501497", side="BUY", amount=Decimal(10))
    assert params.order_type == "FAK"


def test_validate_market_order_params_accepts_fok() -> None:
    params = validate_market_order_params(
        token_id="8501497", side="BUY", amount=Decimal(10), order_type="FOK"
    )
    assert params.order_type == "FOK"


def test_adjust_buy_amount_for_fees_returns_amount_when_cap_covers() -> None:
    result = adjust_buy_amount_for_fees(
        amount=Decimal(10),
        price=Decimal("0.5"),
        max_spend=Decimal(100),
        fee=PlatformFeeInfo(rate=Decimal("0.0005"), exponent=Decimal(1)),
    )
    assert result == Decimal(10)


def test_adjust_buy_amount_for_fees_reduces_when_cap_too_low() -> None:
    fee = PlatformFeeInfo(rate=Decimal("0.0005"), exponent=Decimal(1))
    result = adjust_buy_amount_for_fees(
        amount=Decimal(10),
        price=Decimal("0.5"),
        max_spend=Decimal(10),
        fee=fee,
    )
    assert result < Decimal(10)
    assert result > Decimal(0)


def test_adjust_buy_amount_for_fees_passes_through_when_rate_zero() -> None:
    result = adjust_buy_amount_for_fees(
        amount=Decimal(10),
        price=Decimal("0.5"),
        max_spend=Decimal(10),
        fee=PlatformFeeInfo(rate=Decimal(0), exponent=Decimal(0)),
    )
    assert result == Decimal(10)


def test_prepare_market_order_draft_buy_uses_book_and_tick() -> None:
    captured: list[str] = []
    routes = {
        "/book": _book_payload(
            bids=[{"price": "0.40", "size": "5"}],
            asks=[
                {"price": "0.55", "size": "5"},
                {"price": "0.50", "size": "5"},
            ],
        ),
    }

    async def run() -> tuple[int, int]:
        client = await _make_client()
        try:
            _install_public_clob(client, _tracked_route_handler(routes, captured))
            params = validate_market_order_params(
                token_id="8501497", side="BUY", amount=Decimal("2"), order_type="FAK"
            )
            draft = await prepare_market_order_draft(client._ctx, params)
            return draft.offered_amount, draft.requested_amount
        finally:
            await client.close()

    offered, requested = asyncio.run(run())
    assert offered == 2_000_000  # 2 USDC
    assert requested == 4_000_000  # 2 / 0.5 = 4 shares
    assert captured == ["/book"]


def test_prepare_market_order_draft_sell_swaps_amounts() -> None:
    routes = {
        "/book": _book_payload(
            bids=[
                {"price": "0.45", "size": "5"},
                {"price": "0.50", "size": "5"},
            ],
            asks=[{"price": "0.55", "size": "5"}],
        ),
    }

    async def run() -> tuple[int, int]:
        client = await _make_client()
        try:
            _install_public_clob(client, _multi_route_handler(routes))
            params = validate_market_order_params(
                token_id="8501497", side="SELL", shares=Decimal(4), order_type="FAK"
            )
            draft = await prepare_market_order_draft(client._ctx, params)
            return draft.offered_amount, draft.requested_amount
        finally:
            await client.close()

    offered, requested = asyncio.run(run())
    assert offered == 4_000_000  # 4 shares
    assert requested == 2_000_000  # 4 * 0.5 = 2 USDC


def test_prepare_market_order_draft_buy_uses_max_price_without_book() -> None:
    captured: list[str] = []
    routes = _market_routes()

    async def run() -> tuple[int, int]:
        client = await _make_client()
        try:
            _install_public_clob(client, _tracked_route_handler(routes, captured))
            params = validate_market_order_params(
                token_id="8501497",
                side="BUY",
                amount=Decimal("100"),
                max_price=Decimal("0.55"),
                order_type="FAK",
            )
            draft = await prepare_market_order_draft(client._ctx, params)
            return draft.offered_amount, draft.requested_amount
        finally:
            await client.close()

    offered, requested = asyncio.run(run())
    assert offered == 100_000_000
    # 100 / 0.55 = 181.8181..., rounded DOWN to 181.8181 shares so the encoded
    # price (100 / 181.8181 = 0.5500000...) stays at or above max_price and the
    # order can lift an ask resting exactly at 0.55.
    assert requested == 181_818_100
    assert "/book" not in captured


def test_prepare_market_order_draft_buy_max_spend_resizes_then_rounds_shares_down() -> None:
    routes = _market_routes()

    async def run() -> tuple[int, int]:
        client = await _make_client()
        try:
            _install_public_clob(client, _multi_route_handler(routes))
            params = validate_market_order_params(
                token_id="8501497",
                side="BUY",
                amount=Decimal("100"),
                max_spend=Decimal("50"),
                max_price=Decimal("0.55"),
                order_type="FAK",
            )
            draft = await prepare_market_order_draft(client._ctx, params)
            return draft.offered_amount, draft.requested_amount
        finally:
            await client.close()

    offered, requested = asyncio.run(run())
    # Fee resizing (zero fee rate in the fixture) caps the spend at max_spend first;
    # the share count is then rounded down from the resized amount: 50 / 0.55 =
    # 90.9090... -> 90.9090 shares, encoded price 0.5500000... >= max_price.
    assert offered == 50_000_000
    assert requested == 90_909_000


def test_prepare_market_order_draft_sell_uses_min_price_without_book() -> None:
    captured: list[str] = []
    routes = _market_routes()

    async def run() -> tuple[int, int]:
        client = await _make_client()
        try:
            _install_public_clob(client, _tracked_route_handler(routes, captured))
            params = validate_market_order_params(
                token_id="8501497",
                side="SELL",
                shares=Decimal("180"),
                min_price=Decimal("0.54"),
                order_type="FOK",
            )
            draft = await prepare_market_order_draft(client._ctx, params)
            return draft.offered_amount, draft.requested_amount
        finally:
            await client.close()

    offered, requested = asyncio.run(run())
    assert offered == 180_000_000
    assert requested == 97_200_000
    assert "/book" not in captured


# Direct coverage of the amount math shared by protected and unprotected market
# orders. The exchange derives a BUY's price as maker / taker (a 16-digit quotient,
# not snapped to the tick grid) and only matches when it is at or above the ask, so
# the taker amount must round DOWN.
_PROTECTED_BUY_CASES = [
    # (amount, max_price, tick_size)
    ("1", "0.07", "0.01"),
    ("1", "0.03", "0.01"),
    ("5", "0.07", "0.01"),
    ("25", "0.33", "0.01"),
    ("1", "0.99", "0.01"),
    ("2", "0.6", "0.1"),
    ("1.5", "0.335", "0.005"),
    ("3", "0.4325", "0.0025"),
    ("8", "0.962", "0.001"),
    ("100", "0.4275", "0.0001"),
]


@pytest.mark.parametrize(("amount", "max_price", "tick_size"), _PROTECTED_BUY_CASES)
def test_market_buy_amounts_encode_a_price_that_crosses_at_max_price(
    amount: str, max_price: str, tick_size: str
) -> None:
    maker, taker = _compute_market_order_amounts(
        amount=Decimal(amount), price=Decimal(max_price), side="BUY", tick_size=Decimal(tick_size)
    )
    encoded_price = Decimal(maker) / Decimal(taker)
    assert encoded_price >= Decimal(max_price)
    assert encoded_price < Decimal(max_price) + Decimal(tick_size)


@pytest.mark.parametrize(("amount", "max_price", "tick_size"), _PROTECTED_BUY_CASES)
def test_market_buy_amounts_never_overspend_and_respect_exchange_precision(
    amount: str, max_price: str, tick_size: str
) -> None:
    config = resolve_rounding_config(Decimal(tick_size))
    maker, taker = _compute_market_order_amounts(
        amount=Decimal(amount), price=Decimal(max_price), side="BUY", tick_size=Decimal(tick_size)
    )
    assert Decimal(maker) <= Decimal(amount) * 10**6
    # Market BUY maker amounts must be multiples of the size tick (whole cents) and
    # taker amounts multiples of the amount tick.
    assert maker % 10 ** (6 - config.size) == 0
    assert taker % 10 ** (6 - config.amount) == 0


def test_market_buy_amounts_at_the_venue_minimum_keep_the_full_dollar() -> None:
    # 1 / 0.07: maker stays 1.00 (meets the $1 minimum) and 14.2857 shares encode
    # 0.0700000..., which lifts a 0.07 ask. A FOK fills 14.2857 * 0.07 = 0.999999 of
    # the 1.00 budget, inside the exchange's fill tolerance.
    maker, taker = _compute_market_order_amounts(
        amount=Decimal("1"), price=Decimal("0.07"), side="BUY", tick_size=Decimal("0.01")
    )
    assert (maker, taker) == (1_000_000, 14_285_700)


def test_market_buy_amounts_exact_division_is_unchanged() -> None:
    maker, taker = _compute_market_order_amounts(
        amount=Decimal("1"), price=Decimal("0.10"), side="BUY", tick_size=Decimal("0.01")
    )
    assert (maker, taker) == (1_000_000, 10_000_000)


def test_market_sell_amounts_are_exact() -> None:
    # shares (2dp) x price never exceeds the amount precision, so no rounding applies.
    maker, taker = _compute_market_order_amounts(
        amount=Decimal("180"), price=Decimal("0.54"), side="SELL", tick_size=Decimal("0.01")
    )
    assert (maker, taker) == (180_000_000, 97_200_000)
