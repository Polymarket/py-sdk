from dataclasses import dataclass
from decimal import Decimal

from polymarket._internal.actions.orders.math import decimal_places
from polymarket._internal.environment import EnvironmentConfig
from polymarket._internal.protocol import is_v2_position_id
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.types import EvmAddress


@dataclass(frozen=True, slots=True)
class RoundingConfig:
    amount: int
    price: int
    size: int


_ROUNDING_BY_TICK: dict[Decimal, RoundingConfig] = {
    Decimal("0.1"): RoundingConfig(amount=3, price=1, size=2),
    Decimal("0.01"): RoundingConfig(amount=4, price=2, size=2),
    Decimal("0.005"): RoundingConfig(amount=5, price=3, size=2),
    Decimal("0.0025"): RoundingConfig(amount=6, price=4, size=2),
    Decimal("0.001"): RoundingConfig(amount=5, price=3, size=2),
    Decimal("0.0001"): RoundingConfig(amount=6, price=4, size=2),
}


def resolve_rounding_config(tick_size: Decimal) -> RoundingConfig:
    config = _ROUNDING_BY_TICK.get(tick_size)
    if config is None:
        raise UnexpectedResponseError(f"Unsupported tick size: {tick_size}")
    return config


def validate_price_on_tick_grid(price: Decimal, tick_size: Decimal, field: str) -> Decimal:
    """Validate that a user-supplied order price lies on the market's tick grid
    within ``[tick_size, 1 - tick_size]`` and return it unchanged.

    Grid membership is fully determined by the tick size: valid prices have at
    most as many decimals as the tick and are integer multiples of it. This
    mirrors the exchange's own validation, which divides the price by the
    market's minimum tick and requires an integer result. ``field`` names the
    caller's parameter and prefixes every error message.
    """
    tick_decimals = decimal_places(tick_size)
    if price < tick_size or price > Decimal(1) - tick_size:
        raise UserInputError(
            f"{field} must be between {tick_size} and {Decimal(1) - tick_size} "
            f"for tick size {tick_size}."
        )
    if decimal_places(price) > tick_decimals:
        raise UserInputError(
            f"{field} must conform to tick size {tick_size} with at most "
            f"{tick_decimals} decimal places."
        )
    if price % tick_size != 0:
        raise UserInputError(f"{field} {price} must be a multiple of tick size {tick_size}.")
    return price


def resolve_exchange_address(config: EnvironmentConfig, neg_risk: bool) -> EvmAddress:
    return EvmAddress(config.neg_risk_exchange if neg_risk else config.standard_exchange)


def resolve_order_exchange_address(
    config: EnvironmentConfig, *, asset_id: str, neg_risk: bool
) -> EvmAddress:
    if is_v2_position_id(asset_id):
        return EvmAddress(config.exchange_v3)
    return resolve_exchange_address(config, neg_risk)


__all__ = [
    "RoundingConfig",
    "resolve_exchange_address",
    "resolve_order_exchange_address",
    "resolve_rounding_config",
    "validate_price_on_tick_grid",
]
