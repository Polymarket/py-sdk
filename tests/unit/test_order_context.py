from decimal import Decimal

import pytest

from polymarket._internal.actions.orders.context import (
    resolve_exchange_address,
    resolve_rounding_config,
    validate_price_on_tick_grid,
)
from polymarket._internal.actions.orders.math import decimal_places
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket.errors import UnexpectedResponseError, UserInputError


def test_resolve_rounding_config_supports_known_tick_sizes() -> None:
    assert resolve_rounding_config(Decimal("0.1")).price == 1
    assert resolve_rounding_config(Decimal("0.01")).price == 2
    assert resolve_rounding_config(Decimal("0.005")).price == 3
    assert resolve_rounding_config(Decimal("0.0025")).price == 4
    assert resolve_rounding_config(Decimal("0.001")).price == 3
    assert resolve_rounding_config(Decimal("0.0001")).price == 4


def test_resolve_rounding_config_amount_and_size_follow_table() -> None:
    config = resolve_rounding_config(Decimal("0.001"))
    assert config.amount == 5
    assert config.size == 2


def test_resolve_rounding_config_rejects_unsupported_tick_size() -> None:
    with pytest.raises(UnexpectedResponseError, match="Unsupported tick size"):
        resolve_rounding_config(Decimal("0.0005"))


def test_resolve_exchange_address_selects_neg_risk_when_true() -> None:
    assert (
        resolve_exchange_address(PRODUCTION_CONFIG, neg_risk=True)
        == PRODUCTION_CONFIG.neg_risk_exchange
    )


def test_resolve_exchange_address_selects_standard_when_false() -> None:
    assert (
        resolve_exchange_address(PRODUCTION_CONFIG, neg_risk=False)
        == PRODUCTION_CONFIG.standard_exchange
    )


# Prices are generated as integer numerators over the tick's scale, which
# yields the exact Decimal a user would get from typing the literal.
_ALL_TICKS = [
    Decimal("0.1"),
    Decimal("0.01"),
    Decimal("0.005"),
    Decimal("0.0025"),
    Decimal("0.001"),
    Decimal("0.0001"),
]


def _grid(tick: Decimal) -> tuple[int, int]:
    scale = 10 ** decimal_places(tick)
    return scale, int(tick * scale)


def test_validate_price_accepts_every_on_grid_price_and_returns_it_unchanged() -> None:
    for tick in _ALL_TICKS:
        scale, step = _grid(tick)
        for k in range(step, scale - step + 1, step):
            price = Decimal(k) / scale
            assert validate_price_on_tick_grid(price, tick, "price") == price


def test_validate_price_rejects_every_off_grid_price_at_tick_precision() -> None:
    for tick in [Decimal("0.005"), Decimal("0.0025")]:
        scale, step = _grid(tick)
        for k in range(step, scale - step + 1):
            if k % step == 0:
                continue
            with pytest.raises(UserInputError, match="multiple of tick size"):
                validate_price_on_tick_grid(Decimal(k) / scale, tick, "price")


@pytest.mark.parametrize(
    ("price", "tick"),
    [
        (Decimal("0.15"), Decimal("0.1")),
        (Decimal("0.555"), Decimal("0.01")),
        (Decimal("0.0125"), Decimal("0.005")),
        (Decimal("0.00255"), Decimal("0.0025")),
        (Decimal("0.5555"), Decimal("0.001")),
        (Decimal("0.55555"), Decimal("0.0001")),
        # Values a scale-rounding grid check would silently snap onto the grid
        # without the decimal-count guard.
        (Decimal("0.555001"), Decimal("0.01")),
        (Decimal("0.0100001"), Decimal("0.005")),
        (Decimal("0.55000000001"), Decimal("0.1")),
        (Decimal("0.00250000001"), Decimal("0.0025")),
    ],
)
def test_validate_price_rejects_prices_exceeding_tick_precision(
    price: Decimal, tick: Decimal
) -> None:
    with pytest.raises(UserInputError, match="decimal places"):
        validate_price_on_tick_grid(price, tick, "price")


def test_validate_price_rejects_prices_outside_unit_range() -> None:
    for tick in _ALL_TICKS:
        for price in [Decimal(0), Decimal(1), Decimal("1.5"), -tick, tick / 2]:
            with pytest.raises(UserInputError, match="must be between"):
                validate_price_on_tick_grid(price, tick, "price")
