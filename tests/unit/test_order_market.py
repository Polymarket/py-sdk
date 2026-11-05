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
_CTF_ASSET_ID = str((1 << 40) + 8_501_497)


def _book_payload(*, bids: list[dict[str, str]], asks: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "asset_id": _CTF_ASSET_ID,
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
        f"/markets-by-token/{_CTF_ASSET_ID}": {"condition_id": _CONDITION_ID},
        f"/clob-markets/{_CONDITION_ID}": {
            "fd": {"r": 0, "e": 0},
            "mts": 0.01,
            "nr": neg_risk,
            "t": [{"t": _CTF_ASSET_ID, "o": "Yes"}],
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
                token_id=_CTF_ASSET_ID, side="BUY", amount=Decimal("2"), order_type="FAK"
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
                token_id=_CTF_ASSET_ID, side="SELL", shares=Decimal(4), order_type="FAK"
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
                token_id=_CTF_ASSET_ID,
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
    # At 0.55 the amounts move in steps of 0.0011 USDC for 0.002 shares, so 100 USDC
    # becomes 99.9999 USDC for 181.818 shares: exactly 0.55 per share.
    assert offered == 99_999_900
    assert requested == 181_818_000
    assert "/book" not in captured


def test_prepare_market_order_draft_buy_max_spend_resizes_then_steps_down() -> None:
    routes = _market_routes()

    async def run() -> tuple[int, int]:
        client = await _make_client()
        try:
            _install_public_clob(client, _multi_route_handler(routes))
            params = validate_market_order_params(
                token_id=_CTF_ASSET_ID,
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
    # the amounts then step down from it: 49.9994 USDC for 90.908 shares at exactly
    # 0.55.
    assert offered == 49_999_400
    assert requested == 90_908_000


def test_prepare_market_order_draft_sell_uses_min_price_without_book() -> None:
    captured: list[str] = []
    routes = _market_routes()

    async def run() -> tuple[int, int]:
        client = await _make_client()
        try:
            _install_public_clob(client, _tracked_route_handler(routes, captured))
            params = validate_market_order_params(
                token_id=_CTF_ASSET_ID,
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


# Direct coverage of the market BUY amount math shared by protected and unprotected
# orders. The exchange reads a BUY's price as maker / taker, requires that ratio to be
# exactly an on-tick price, and requires collateral and shares in whole units of the
# market's amount precision.
_TICK_SIZES = ["0.1", "0.01", "0.005", "0.0025", "0.001", "0.0001"]
_PROTECTED_BUY_CASES = [
    # (amount, max_price, tick_size)
    ("10", "0.65", "0.01"),
    ("5", "0.07", "0.01"),
    ("25", "0.33", "0.01"),
    ("2", "0.6", "0.1"),
    ("1.5", "0.335", "0.005"),
    ("3", "0.4325", "0.0025"),
    ("10", "0.962", "0.001"),
    ("100", "0.4275", "0.0001"),
]


def _exchange_admits(maker: int, taker: int, tick_size: Decimal) -> bool:
    # The exchange's own admission rule: the 6-decimal price must divide exactly and
    # sit on the market tick.
    if taker <= 0 or maker * 10**6 % taker != 0:
        return False
    return (maker * 10**6 // taker) % int(tick_size * 10**6) == 0


def _exact_buy_amounts_by_search(amount: Decimal, price: Decimal, tick_size: Decimal) -> int:
    # Largest collateral within amount that buys a whole number of share units at
    # exactly price, with collateral in whole units too. Walks the share count down one
    # unit at a time from the most amount could buy.
    unit = 10 ** (6 - resolve_rounding_config(tick_size).amount)
    numerator, denominator = price.as_integer_ratio()
    budget = int(amount * 10**6)
    shares = budget * denominator // numerator // unit * unit
    while shares > 0:
        collateral, remainder = divmod(shares * numerator, denominator)
        if remainder == 0 and collateral % unit == 0 and collateral <= budget:
            return collateral
        shares -= unit
    return 0


def _assert_exact_buy_amounts(
    maker: int, taker: int, amount: Decimal, price: Decimal, tick_size: Decimal
) -> None:
    config = resolve_rounding_config(tick_size)
    assert Decimal(maker) / Decimal(taker) == price
    assert _exchange_admits(maker, taker, tick_size)
    assert maker <= amount * 10**6
    assert maker % 10 ** (6 - config.amount) == 0
    assert taker % 10 ** (6 - config.amount) == 0


@pytest.mark.parametrize(("amount", "max_price", "tick_size"), _PROTECTED_BUY_CASES)
def test_market_buy_amounts_encode_exactly_the_order_price(
    amount: str, max_price: str, tick_size: str
) -> None:
    maker, taker = _compute_market_order_amounts(
        amount=Decimal(amount), price=Decimal(max_price), side="BUY", tick_size=Decimal(tick_size)
    )
    _assert_exact_buy_amounts(maker, taker, Decimal(amount), Decimal(max_price), Decimal(tick_size))


@pytest.mark.parametrize("tick_size", _TICK_SIZES)
def test_market_buy_amounts_spend_the_most_an_exact_price_allows(tick_size: str) -> None:
    tick = Decimal(tick_size)
    prices = [tick * i for i in range(1, int(1 / tick), max(1, int(1 / tick) // 97))]
    amounts = [
        Decimal(a)
        for a in ("0.99", "0.9999", "1", "1.01", "3.33", "10", "25.5", "99.99", "250", "1000")
    ]
    for price in prices:
        for amount in amounts:
            expected = _exact_buy_amounts_by_search(amount, price, tick)
            if expected < 990_000:
                with pytest.raises(UserInputError, match="cannot be spent exactly"):
                    _compute_market_order_amounts(
                        amount=amount, price=price, side="BUY", tick_size=tick
                    )
                continue
            maker, taker = _compute_market_order_amounts(
                amount=amount, price=price, side="BUY", tick_size=tick
            )
            assert maker == expected, (amount, price)
            _assert_exact_buy_amounts(maker, taker, amount, price, tick)


def test_market_buy_amounts_step_by_the_smallest_exact_share_count() -> None:
    # At 0.65 on a 0.01 tick, 0.0013 USDC buys exactly 0.002 shares; 10 USDC holds
    # 7692 such steps.
    maker, taker = _compute_market_order_amounts(
        amount=Decimal("10"), price=Decimal("0.65"), side="BUY", tick_size=Decimal("0.01")
    )
    assert (maker, taker) == (9_999_600, 15_384_000)


@pytest.mark.parametrize(
    ("price", "tick_size", "expected"),
    [
        ("0.7", "0.1", (994_000, 1_420_000)),
        ("0.65", "0.01", (999_700, 1_538_000)),
        ("0.07", "0.01", (999_600, 14_280_000)),
        ("0.335", "0.005", (999_640, 2_984_000)),
        ("0.4325", "0.0025", (999_940, 2_312_000)),
        ("0.962", "0.001", (995_670, 1_035_000)),
        ("0.9999", "0.0001", (999_900, 1_000_000)),
    ],
)
def test_market_buy_of_one_usdc_stays_above_the_minimum(
    price: str, tick_size: str, expected: tuple[int, int]
) -> None:
    maker, taker = _compute_market_order_amounts(
        amount=Decimal("1"), price=Decimal(price), side="BUY", tick_size=Decimal(tick_size)
    )
    assert (maker, taker) == expected
    _assert_exact_buy_amounts(maker, taker, Decimal("1"), Decimal(price), Decimal(tick_size))


def test_market_buy_amounts_exact_division_is_unchanged() -> None:
    maker, taker = _compute_market_order_amounts(
        amount=Decimal("1"), price=Decimal("0.10"), side="BUY", tick_size=Decimal("0.01")
    )
    assert (maker, taker) == (1_000_000, 10_000_000)


def test_market_buy_at_exactly_the_minimum_is_accepted() -> None:
    maker, taker = _compute_market_order_amounts(
        amount=Decimal("0.99"), price=Decimal("0.5"), side="BUY", tick_size=Decimal("0.01")
    )
    assert (maker, taker) == (990_000, 1_980_000)


def test_market_buy_amount_that_steps_below_the_minimum_is_rejected() -> None:
    # 0.99 USDC at 0.65 holds 761 steps of 0.0013, which is 0.9893 and under the
    # 0.99 USDC minimum for a marketable BUY.
    with pytest.raises(UserInputError, match=r"steps of 0\.0013; use at least 0\.9906"):
        _compute_market_order_amounts(
            amount=Decimal("0.99"), price=Decimal("0.65"), side="BUY", tick_size=Decimal("0.01")
        )


@pytest.mark.parametrize("amount", ["0.001", "0.5"])
def test_market_buy_amount_below_the_minimum_is_rejected(amount: str) -> None:
    with pytest.raises(UserInputError, match=r"steps of 0\.0013; use at least 0\.9906"):
        _compute_market_order_amounts(
            amount=Decimal(amount), price=Decimal("0.65"), side="BUY", tick_size=Decimal("0.01")
        )


@pytest.mark.parametrize(("amount", "max_price", "tick_size"), _PROTECTED_BUY_CASES)
def test_protected_market_buy_signs_exactly_max_price(
    amount: str, max_price: str, tick_size: str
) -> None:
    routes = _market_routes()
    routes[f"/clob-markets/{_CONDITION_ID}"]["mts"] = tick_size
    captured: list[str] = []

    async def run() -> tuple[int, int]:
        client = await _make_client()
        try:
            _install_public_clob(client, _tracked_route_handler(routes, captured))
            params = validate_market_order_params(
                token_id=_CTF_ASSET_ID,
                side="BUY",
                amount=amount,
                max_price=max_price,
            )
            draft = await prepare_market_order_draft(client._ctx, params)
            return draft.offered_amount, draft.requested_amount
        finally:
            await client.close()

    maker, taker = asyncio.run(run())
    # A ratio of exactly max_price lifts an ask at max_price and no higher ask, even
    # if the market's tick becomes finer after signing.
    _assert_exact_buy_amounts(maker, taker, Decimal(amount), Decimal(max_price), Decimal(tick_size))
    assert captured.count(f"/clob-markets/{_CONDITION_ID}") == 1
    assert "/book" not in captured


def test_market_sell_amounts_are_exact() -> None:
    # shares (2dp) x price never exceeds the amount precision, so no rounding applies.
    maker, taker = _compute_market_order_amounts(
        amount=Decimal("180"), price=Decimal("0.54"), side="SELL", tick_size=Decimal("0.01")
    )
    assert (maker, taker) == (180_000_000, 97_200_000)
