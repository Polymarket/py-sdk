import time
from dataclasses import dataclass
from decimal import Decimal

from polymarket._internal.actions.exchange_asset import resolve_asset_id
from polymarket._internal.actions.orders._numeric import coerce_positive_decimal
from polymarket._internal.actions.orders.context import (
    resolve_order_exchange_address,
    resolve_rounding_config,
    validate_price_on_tick_grid,
)
from polymarket._internal.actions.orders.market_data import MarketInfo
from polymarket._internal.actions.orders.math import (
    decimal_places,
    parse_amount,
    round_down,
    round_up,
)
from polymarket._internal.actions.orders.types import OrderDraft
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.validation import validate_builder_code
from polymarket.errors import UserInputError
from polymarket.models.types import ClobAssetId, OrderSide
from polymarket.types import EvmAddress, HexString

_MIN_EXPIRATION_BUFFER_S = 180


@dataclass(frozen=True, slots=True, kw_only=True)
class PrepareLimitOrderParams:
    asset_id: ClobAssetId
    price: Decimal
    size: Decimal
    side: OrderSide
    post_only: bool = False
    expiration: int | None = None
    builder_code: HexString | None = None

    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id


def validate_limit_order_params(
    *,
    asset_id: str | None = None,
    token_id: str | None = None,
    price: Decimal | int | float | str,
    size: Decimal | int | float | str,
    side: OrderSide,
    post_only: bool = False,
    expiration: int | None = None,
    builder_code: str | None = None,
) -> PrepareLimitOrderParams:
    validated_asset = resolve_asset_id(asset_id=asset_id, token_id=token_id)
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
        asset_id=validated_asset,
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
    metadata = await ctx.order_metadata.resolve_market(ctx, token_id=params.asset_id)
    try:
        price = validate_price_on_tick_grid(params.price, metadata.tick_size, "price")
    except UserInputError:
        metadata = await ctx.order_metadata.fetch_current_market(ctx, token_id=params.asset_id)
        price = validate_price_on_tick_grid(params.price, metadata.tick_size, "price")
    return _build_limit_order_draft(ctx, params, price=price, metadata=metadata)


def prepare_limit_order_draft_sync(
    ctx: SyncSecureClientContext, params: PrepareLimitOrderParams
) -> OrderDraft:
    metadata = ctx.order_metadata.resolve_market(ctx, token_id=params.asset_id)
    try:
        price = validate_price_on_tick_grid(params.price, metadata.tick_size, "price")
    except UserInputError:
        metadata = ctx.order_metadata.fetch_current_market(ctx, token_id=params.asset_id)
        price = validate_price_on_tick_grid(params.price, metadata.tick_size, "price")
    return _build_limit_order_draft(ctx, params, price=price, metadata=metadata)


def _build_limit_order_draft(
    ctx: AsyncSecureClientContext | SyncSecureClientContext,
    params: PrepareLimitOrderParams,
    *,
    price: Decimal,
    metadata: MarketInfo,
) -> OrderDraft:
    offered, requested = _compute_limit_order_amounts(
        price=price,
        size=params.size,
        side=params.side,
        tick_size=metadata.tick_size,
    )
    return OrderDraft(
        chain_id=ctx.environment_config.chain_id,
        exchange_address=resolve_order_exchange_address(
            ctx.environment_config, asset_id=params.asset_id, neg_risk=metadata.neg_risk
        ),
        expiration=params.expiration if params.expiration is not None else 0,
        funder_address=ctx.wallet,
        offered_amount=offered,
        order_type="GTC" if params.expiration is None else "GTD",
        side=params.side,
        signer=EvmAddress(ctx.signer.address),
        requested_amount=requested,
        asset_id=params.asset_id,
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
