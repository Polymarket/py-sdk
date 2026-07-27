import time
from dataclasses import dataclass
from decimal import Decimal

from polymarket._internal.actions.orders._numeric import coerce_positive_decimal
from polymarket._internal.actions.orders.context import (
    resolve_exchange_address,
    resolve_rounding_config,
    validate_price_on_tick_grid,
)
from polymarket._internal.actions.orders.market_data import (
    fetch_neg_risk,
    fetch_neg_risk_sync,
    fetch_tick_size,
    fetch_tick_size_sync,
)
from polymarket._internal.actions.orders.math import (
    decimal_places,
    parse_amount,
    round_down,
    round_up,
)
from polymarket._internal.actions.orders.types import OrderDraft
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.validation import require_nonempty, validate_builder_code
from polymarket.errors import UserInputError
from polymarket.models.types import OrderSide, TokenId
from polymarket.types import EvmAddress, HexString

_MIN_EXPIRATION_BUFFER_S = 180


@dataclass(frozen=True, slots=True, kw_only=True)
class PrepareLimitOrderParams:
    token_id: TokenId
    price: Decimal
    size: Decimal
    side: OrderSide
    post_only: bool = False
    expiration: int | None = None
    builder_code: HexString | None = None


def validate_limit_order_params(
    *,
    token_id: str,
    price: Decimal | int | float | str,
    size: Decimal | int | float | str,
    side: OrderSide,
    post_only: bool = False,
    expiration: int | None = None,
    builder_code: str | None = None,
) -> PrepareLimitOrderParams:
    validated_token = TokenId(require_nonempty("token_id", token_id))
    validated_price = coerce_positive_decimal("price", price)
    validated_size = coerce_positive_decimal("size", size)
    if side not in ("BUY", "SELL"):
        raise UserInputError(f"side must be 'BUY' or 'SELL', got {side!r}.")
    if type(post_only) is not bool:
        raise UserInputError("post_only must be a bool.")
    if expiration is not None:
        if type(expiration) is not int:
            raise UserInputError("expiration must be a non-negative integer.")
        if expiration < 0:
            raise UserInputError("expiration must be a non-negative integer.")
        minimum = int(time.time()) + _MIN_EXPIRATION_BUFFER_S
        if expiration < minimum:
            raise UserInputError(
                f"expiration must be at least {_MIN_EXPIRATION_BUFFER_S} seconds in the future."
            )
    validated_builder = validate_builder_code(builder_code) if builder_code is not None else None
    return PrepareLimitOrderParams(
        token_id=validated_token,
        price=validated_price,
        size=validated_size,
        side=side,
        post_only=post_only,
        expiration=expiration,
        builder_code=validated_builder,
    )


async def prepare_limit_order_draft(
    ctx: AsyncSecureClientContext, params: PrepareLimitOrderParams
) -> OrderDraft:
    tick_size = await fetch_tick_size(ctx, token_id=params.token_id)
    neg_risk = await fetch_neg_risk(ctx, token_id=params.token_id)
    price = validate_price_on_tick_grid(params.price, tick_size, "price")
    offered, requested = _compute_limit_order_amounts(
        price=price, size=params.size, side=params.side, tick_size=tick_size
    )
    return OrderDraft(
        chain_id=ctx.environment.chain_id,
        exchange_address=resolve_exchange_address(ctx.environment, neg_risk),
        expiration=params.expiration if params.expiration is not None else 0,
        funder_address=ctx.wallet,
        offered_amount=offered,
        order_type="GTC" if params.expiration is None else "GTD",
        side=params.side,
        signer=EvmAddress(ctx.signer.address),
        requested_amount=requested,
        token_id=params.token_id,
        builder_code=params.builder_code,
    )


def prepare_limit_order_draft_sync(
    ctx: SyncSecureClientContext, params: PrepareLimitOrderParams
) -> OrderDraft:
    tick_size = fetch_tick_size_sync(ctx, token_id=params.token_id)
    neg_risk = fetch_neg_risk_sync(ctx, token_id=params.token_id)
    price = validate_price_on_tick_grid(params.price, tick_size, "price")
    offered, requested = _compute_limit_order_amounts(
        price=price, size=params.size, side=params.side, tick_size=tick_size
    )
    return OrderDraft(
        chain_id=ctx.environment.chain_id,
        exchange_address=resolve_exchange_address(ctx.environment, neg_risk),
        expiration=params.expiration if params.expiration is not None else 0,
        funder_address=ctx.wallet,
        offered_amount=offered,
        order_type="GTC" if params.expiration is None else "GTD",
        side=params.side,
        signer=EvmAddress(ctx.signer.address),
        requested_amount=requested,
        token_id=params.token_id,
        builder_code=params.builder_code,
    )


def _compute_limit_order_amounts(
    *, price: Decimal, size: Decimal, side: OrderSide, tick_size: Decimal
) -> tuple[int, int]:
    config = resolve_rounding_config(tick_size)
    if side == "BUY":
        taker = round_down(size, config.size)
        maker = _round_amount(taker * price, config.amount)
        return parse_amount(maker), parse_amount(taker)
    maker = round_down(size, config.size)
    taker = _round_amount(maker * price, config.amount)
    return parse_amount(maker), parse_amount(taker)


def _round_amount(value: Decimal, amount_decimals: int) -> Decimal:
    if decimal_places(value) <= amount_decimals:
        return value
    value = round_up(value, amount_decimals + 4)
    if decimal_places(value) > amount_decimals:
        value = round_down(value, amount_decimals)
    return value


__all__ = [
    "PrepareLimitOrderParams",
    "prepare_limit_order_draft",
    "prepare_limit_order_draft_sync",
    "validate_limit_order_params",
]
