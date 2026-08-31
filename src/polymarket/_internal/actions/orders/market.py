import asyncio
from dataclasses import dataclass
from decimal import Decimal

from polymarket._internal.actions.exchange_asset import resolve_asset_id
from polymarket._internal.actions.orders._numeric import coerce_positive_decimal
from polymarket._internal.actions.orders.context import (
    resolve_order_exchange_address,
    resolve_rounding_config,
    validate_price_on_tick_grid,
)
from polymarket._internal.actions.orders.estimate import (
    ResolvedMarketPrice,
    resolve_market_price_context,
    resolve_market_price_context_sync,
)
from polymarket._internal.actions.orders.market_data import MarketInfo, PlatformFeeInfo
from polymarket._internal.actions.orders.math import (
    decimal_places,
    parse_amount,
    round_down,
    round_up,
)
from polymarket._internal.actions.orders.types import MarketOrderType, OrderDraft
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.validation import validate_builder_code
from polymarket.errors import UserInputError
from polymarket.models.types import ClobAssetId, OrderSide
from polymarket.types import EvmAddress, HexString


@dataclass(frozen=True, slots=True, kw_only=True)
class PrepareMarketOrderParams:
    asset_id: ClobAssetId
    side: OrderSide
    order_type: MarketOrderType
    amount: Decimal | None = None
    shares: Decimal | None = None
    max_spend: Decimal | None = None
    max_price: Decimal | None = None
    min_price: Decimal | None = None
    builder_code: HexString | None = None

    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id


def validate_market_order_params(
    *,
    asset_id: str | None = None,
    token_id: str | None = None,
    side: OrderSide,
    amount: Decimal | int | float | str | None = None,
    shares: Decimal | int | float | str | None = None,
    max_spend: Decimal | int | float | str | None = None,
    max_price: Decimal | int | float | str | None = None,
    min_price: Decimal | int | float | str | None = None,
    order_type: MarketOrderType = "FAK",
    builder_code: str | None = None,
) -> PrepareMarketOrderParams:
    validated_asset = resolve_asset_id(asset_id=asset_id, token_id=token_id)
    if side not in ("BUY", "SELL"):
        raise UserInputError(f"side must be 'BUY' or 'SELL', got {side!r}.")
    if order_type not in ("FAK", "FOK"):
        raise UserInputError(f"order_type must be 'FAK' or 'FOK', got {order_type!r}.")
    validated_builder = validate_builder_code(builder_code) if builder_code is not None else None
    if side == "BUY":
        if amount is None:
            raise UserInputError("amount is required for BUY market orders.")
        if shares is not None:
            raise UserInputError("shares must not be set for BUY market orders.")
        if min_price is not None:
            raise UserInputError("min_price is only valid for SELL market orders.")
        validated_amount = coerce_positive_decimal("amount", amount)
        validated_max_spend = (
            coerce_positive_decimal("max_spend", max_spend) if max_spend is not None else None
        )
        validated_max_price = (
            coerce_positive_decimal("max_price", max_price) if max_price is not None else None
        )
        return PrepareMarketOrderParams(
            asset_id=validated_asset,
            side=side,
            order_type=order_type,
            amount=validated_amount,
            max_spend=validated_max_spend,
            max_price=validated_max_price,
            builder_code=validated_builder,
        )
    if shares is None:
        raise UserInputError("shares is required for SELL market orders.")
    if amount is not None:
        raise UserInputError("amount must not be set for SELL market orders.")
    if max_spend is not None:
        raise UserInputError("max_spend is only valid for BUY market orders.")
    if max_price is not None:
        raise UserInputError("max_price is only valid for BUY market orders.")
    validated_min_price = (
        coerce_positive_decimal("min_price", min_price) if min_price is not None else None
    )
    return PrepareMarketOrderParams(
        asset_id=validated_asset,
        side=side,
        order_type=order_type,
        shares=coerce_positive_decimal("shares", shares),
        min_price=validated_min_price,
        builder_code=validated_builder,
    )


async def prepare_market_order_draft(
    ctx: AsyncSecureClientContext, params: PrepareMarketOrderParams
) -> OrderDraft:
    if _has_protected_price(params):
        return await _prepare_protected_market_order_draft(ctx, params)
    return await _prepare_unprotected_market_order_draft(ctx, params)


def prepare_market_order_draft_sync(
    ctx: SyncSecureClientContext, params: PrepareMarketOrderParams
) -> OrderDraft:
    if _has_protected_price(params):
        return _prepare_protected_market_order_draft_sync(ctx, params)
    return _prepare_unprotected_market_order_draft_sync(ctx, params)


async def _prepare_protected_market_order_draft(
    ctx: AsyncSecureClientContext, params: PrepareMarketOrderParams
) -> OrderDraft:
    notional = _resolve_market_order_notional(params)
    if params.side == "BUY" and params.max_spend is not None:
        metadata, builder_taker_fee_rate = await asyncio.gather(
            ctx.order_metadata.resolve_market(ctx, token_id=params.asset_id),
            ctx.order_metadata.resolve_builder_taker_fee_rate(
                ctx, builder_code=params.builder_code
            ),
        )
    else:
        metadata = await ctx.order_metadata.resolve_market(ctx, token_id=params.asset_id)
        builder_taker_fee_rate = Decimal(0)
    try:
        price = _resolve_protected_market_order_price(params, metadata.tick_size)
    except UserInputError:
        metadata = await ctx.order_metadata.fetch_current_market(ctx, token_id=params.asset_id)
        price = _resolve_protected_market_order_price(params, metadata.tick_size)
    resolved_amount = notional
    if params.side == "BUY" and params.max_spend is not None:
        resolved_amount = _resolve_buy_amount_for_fees(
            amount=notional,
            max_spend=params.max_spend,
            price=price,
            metadata=metadata,
            builder_taker_fee_rate=builder_taker_fee_rate,
        )
    return _build_market_order_draft(
        ctx,
        params,
        price=price,
        tick_size=metadata.tick_size,
        neg_risk=metadata.neg_risk,
        resolved_amount=resolved_amount,
        protect_price=True,
    )


def _prepare_protected_market_order_draft_sync(
    ctx: SyncSecureClientContext, params: PrepareMarketOrderParams
) -> OrderDraft:
    notional = _resolve_market_order_notional(params)
    metadata = ctx.order_metadata.resolve_market(ctx, token_id=params.asset_id)
    builder_taker_fee_rate = (
        ctx.order_metadata.resolve_builder_taker_fee_rate(ctx, builder_code=params.builder_code)
        if params.side == "BUY" and params.max_spend is not None
        else Decimal(0)
    )
    try:
        price = _resolve_protected_market_order_price(params, metadata.tick_size)
    except UserInputError:
        metadata = ctx.order_metadata.fetch_current_market(ctx, token_id=params.asset_id)
        price = _resolve_protected_market_order_price(params, metadata.tick_size)
    resolved_amount = notional
    if params.side == "BUY" and params.max_spend is not None:
        resolved_amount = _resolve_buy_amount_for_fees(
            amount=notional,
            max_spend=params.max_spend,
            price=price,
            metadata=metadata,
            builder_taker_fee_rate=builder_taker_fee_rate,
        )
    return _build_market_order_draft(
        ctx,
        params,
        price=price,
        tick_size=metadata.tick_size,
        neg_risk=metadata.neg_risk,
        resolved_amount=resolved_amount,
        protect_price=True,
    )


async def _prepare_unprotected_market_order_draft(
    ctx: AsyncSecureClientContext, params: PrepareMarketOrderParams
) -> OrderDraft:
    notional = _resolve_market_order_notional(params)
    if params.side == "BUY" and params.max_spend is not None:
        price_context, metadata, builder_taker_fee_rate = await asyncio.gather(
            resolve_market_price_context(
                ctx,
                token_id=params.asset_id,
                side=params.side,
                notional=notional,
                order_type=params.order_type,
            ),
            ctx.order_metadata.resolve_market(ctx, token_id=params.asset_id),
            ctx.order_metadata.resolve_builder_taker_fee_rate(
                ctx, builder_code=params.builder_code
            ),
        )
        resolved_amount = _resolve_buy_amount_for_fees(
            amount=notional,
            max_spend=params.max_spend,
            price=price_context.price,
            metadata=metadata,
            builder_taker_fee_rate=builder_taker_fee_rate,
        )
    else:
        price_context = await resolve_market_price_context(
            ctx,
            token_id=params.asset_id,
            side=params.side,
            notional=notional,
            order_type=params.order_type,
        )
        resolved_amount = notional
    return _build_unprotected_market_order_draft(
        ctx, params, price_context=price_context, resolved_amount=resolved_amount
    )


def _prepare_unprotected_market_order_draft_sync(
    ctx: SyncSecureClientContext, params: PrepareMarketOrderParams
) -> OrderDraft:
    notional = _resolve_market_order_notional(params)
    price_context = resolve_market_price_context_sync(
        ctx,
        token_id=params.asset_id,
        side=params.side,
        notional=notional,
        order_type=params.order_type,
    )
    if params.side == "BUY" and params.max_spend is not None:
        metadata = ctx.order_metadata.resolve_market(ctx, token_id=params.asset_id)
        builder_taker_fee_rate = ctx.order_metadata.resolve_builder_taker_fee_rate(
            ctx, builder_code=params.builder_code
        )
        resolved_amount = _resolve_buy_amount_for_fees(
            amount=notional,
            max_spend=params.max_spend,
            price=price_context.price,
            metadata=metadata,
            builder_taker_fee_rate=builder_taker_fee_rate,
        )
    else:
        resolved_amount = notional
    return _build_unprotected_market_order_draft(
        ctx, params, price_context=price_context, resolved_amount=resolved_amount
    )


def _build_unprotected_market_order_draft(
    ctx: AsyncSecureClientContext | SyncSecureClientContext,
    params: PrepareMarketOrderParams,
    *,
    price_context: ResolvedMarketPrice,
    resolved_amount: Decimal,
) -> OrderDraft:
    return _build_market_order_draft(
        ctx,
        params,
        price=price_context.price,
        tick_size=price_context.tick_size,
        neg_risk=price_context.neg_risk,
        resolved_amount=resolved_amount,
        protect_price=False,
    )


def _build_market_order_draft(
    ctx: AsyncSecureClientContext | SyncSecureClientContext,
    params: PrepareMarketOrderParams,
    *,
    price: Decimal,
    tick_size: Decimal,
    neg_risk: bool,
    resolved_amount: Decimal,
    protect_price: bool,
) -> OrderDraft:
    offered, requested = _compute_market_order_amounts(
        amount=resolved_amount,
        price=price,
        protect_price=protect_price,
        side=params.side,
        tick_size=tick_size,
    )
    return OrderDraft(
        chain_id=ctx.environment_config.chain_id,
        exchange_address=resolve_order_exchange_address(
            ctx.environment_config, asset_id=params.asset_id, neg_risk=neg_risk
        ),
        expiration=0,
        funder_address=ctx.wallet,
        offered_amount=offered,
        order_type=params.order_type,
        side=params.side,
        signer=EvmAddress(ctx.signer.address),
        requested_amount=requested,
        asset_id=params.asset_id,
        builder_code=params.builder_code,
    )


def _resolve_protected_market_order_price(
    params: PrepareMarketOrderParams, tick_size: Decimal
) -> Decimal:
    if params.side == "BUY" and params.max_price is not None:
        return validate_price_on_tick_grid(params.max_price, tick_size, "max_price")
    if params.side == "SELL" and params.min_price is not None:
        return validate_price_on_tick_grid(params.min_price, tick_size, "min_price")
    raise RuntimeError("Protected market order requires max_price or min_price.")


def _resolve_market_order_notional(params: PrepareMarketOrderParams) -> Decimal:
    notional = params.amount if params.side == "BUY" else params.shares
    if notional is None:
        raise RuntimeError("Validated market order is missing its side-specific amount.")
    return notional


def _has_protected_price(params: PrepareMarketOrderParams) -> bool:
    return (params.side == "BUY" and params.max_price is not None) or (
        params.side == "SELL" and params.min_price is not None
    )


def _compute_market_order_amounts(
    *,
    amount: Decimal,
    price: Decimal,
    side: OrderSide,
    tick_size: Decimal,
    protect_price: bool = False,
) -> tuple[int, int]:
    config = resolve_rounding_config(tick_size)
    raw_price = round_down(price, config.price)
    raw_maker = round_down(amount, config.size)
    raw_taker = raw_maker / raw_price if side == "BUY" else raw_maker * raw_price
    if decimal_places(raw_taker) > config.amount:
        raw_taker = round_up(raw_taker, config.amount + 4)
        if decimal_places(raw_taker) > config.amount:
            raw_taker = (
                round_up(raw_taker, config.amount)
                if protect_price
                else round_down(raw_taker, config.amount)
            )
    return parse_amount(raw_maker), parse_amount(raw_taker)


def _resolve_buy_amount_for_fees(
    *,
    amount: Decimal,
    max_spend: Decimal,
    price: Decimal,
    metadata: MarketInfo,
    builder_taker_fee_rate: Decimal,
) -> Decimal:
    return adjust_buy_amount_for_fees(
        amount=amount,
        price=price,
        max_spend=max_spend,
        fee=metadata.fee_info,
        builder_taker_fee_rate=builder_taker_fee_rate,
    )


def adjust_buy_amount_for_fees(
    *,
    amount: Decimal,
    price: Decimal,
    max_spend: Decimal,
    fee: PlatformFeeInfo,
    builder_taker_fee_rate: Decimal = Decimal(0),
) -> Decimal:
    effective_rate = fee.rate * ((price * (Decimal(1) - price)) ** fee.exponent)
    platform_fee = (amount / price) * effective_rate
    builder_fee = amount * builder_taker_fee_rate
    total_cost = amount + platform_fee + builder_fee
    if max_spend <= total_cost:
        return max_spend / (Decimal(1) + effective_rate / price + builder_taker_fee_rate)
    return amount


__all__ = [
    "PrepareMarketOrderParams",
    "adjust_buy_amount_for_fees",
    "prepare_market_order_draft",
    "prepare_market_order_draft_sync",
    "validate_market_order_params",
]
