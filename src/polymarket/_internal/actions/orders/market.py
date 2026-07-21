from dataclasses import dataclass
from decimal import Decimal

from polymarket._internal.actions.orders._numeric import coerce_positive_decimal
from polymarket._internal.actions.orders.context import (
    resolve_exchange_address,
    resolve_rounding_config,
    validate_price_on_tick_grid,
)
from polymarket._internal.actions.orders.estimate import (
    resolve_estimated_market_price,
    resolve_estimated_market_price_sync,
)
from polymarket._internal.actions.orders.market_data import (
    PlatformFeeInfo,
    fetch_builder_fee_rates,
    fetch_builder_fee_rates_sync,
    fetch_neg_risk,
    fetch_neg_risk_sync,
    fetch_platform_fee_info,
    fetch_platform_fee_info_sync,
    fetch_tick_size,
    fetch_tick_size_sync,
    resolve_condition_by_token,
    resolve_condition_by_token_sync,
)
from polymarket._internal.actions.orders.math import (
    decimal_places,
    parse_amount,
    round_down,
    round_up,
)
from polymarket._internal.actions.orders.types import BYTES32_ZERO, MarketOrderType, OrderDraft
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.validation import require_nonempty, validate_builder_code
from polymarket.errors import UserInputError
from polymarket.models.types import OrderSide, TokenId
from polymarket.types import EvmAddress, HexString


@dataclass(frozen=True, slots=True, kw_only=True)
class PrepareMarketOrderParams:
    token_id: TokenId
    side: OrderSide
    order_type: MarketOrderType
    amount: Decimal | None = None
    shares: Decimal | None = None
    max_spend: Decimal | None = None
    max_price: Decimal | None = None
    min_price: Decimal | None = None
    builder_code: HexString | None = None


def validate_market_order_params(
    *,
    token_id: str,
    side: OrderSide,
    amount: Decimal | int | float | str | None = None,
    shares: Decimal | int | float | str | None = None,
    max_spend: Decimal | int | float | str | None = None,
    max_price: Decimal | int | float | str | None = None,
    min_price: Decimal | int | float | str | None = None,
    order_type: MarketOrderType = "FAK",
    builder_code: str | None = None,
) -> PrepareMarketOrderParams:
    validated_token = TokenId(require_nonempty("token_id", token_id))
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
            token_id=validated_token,
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
        token_id=validated_token,
        side=side,
        order_type=order_type,
        shares=coerce_positive_decimal("shares", shares),
        min_price=validated_min_price,
        builder_code=validated_builder,
    )


async def prepare_market_order_draft(
    ctx: AsyncSecureClientContext, params: PrepareMarketOrderParams
) -> OrderDraft:
    tick_size = await fetch_tick_size(ctx, token_id=params.token_id)
    notional = params.amount if params.side == "BUY" else params.shares
    assert notional is not None
    price = await _resolve_market_order_price(ctx, params, notional=notional, tick_size=tick_size)
    neg_risk = await fetch_neg_risk(ctx, token_id=params.token_id)
    resolved_amount = await _resolve_buy_amount_for_fees(ctx, params, price=price)
    offered, requested = _compute_market_order_amounts(
        amount=resolved_amount,
        price=price,
        protect_price=_has_protected_price(params),
        side=params.side,
        tick_size=tick_size,
    )
    return OrderDraft(
        chain_id=ctx.environment.chain_id,
        exchange_address=resolve_exchange_address(ctx.environment, neg_risk),
        expiration=0,
        funder_address=ctx.wallet,
        offered_amount=offered,
        order_type=params.order_type,
        side=params.side,
        signer=EvmAddress(ctx.signer.address),
        requested_amount=requested,
        token_id=params.token_id,
        builder_code=params.builder_code,
    )


def prepare_market_order_draft_sync(
    ctx: SyncSecureClientContext, params: PrepareMarketOrderParams
) -> OrderDraft:
    tick_size = fetch_tick_size_sync(ctx, token_id=params.token_id)
    notional = params.amount if params.side == "BUY" else params.shares
    assert notional is not None
    price = _resolve_market_order_price_sync(ctx, params, notional=notional, tick_size=tick_size)
    neg_risk = fetch_neg_risk_sync(ctx, token_id=params.token_id)
    resolved_amount = _resolve_buy_amount_for_fees_sync(ctx, params, price=price)
    offered, requested = _compute_market_order_amounts(
        amount=resolved_amount,
        price=price,
        protect_price=_has_protected_price(params),
        side=params.side,
        tick_size=tick_size,
    )
    return OrderDraft(
        chain_id=ctx.environment.chain_id,
        exchange_address=resolve_exchange_address(ctx.environment, neg_risk),
        expiration=0,
        funder_address=ctx.wallet,
        offered_amount=offered,
        order_type=params.order_type,
        side=params.side,
        signer=EvmAddress(ctx.signer.address),
        requested_amount=requested,
        token_id=params.token_id,
        builder_code=params.builder_code,
    )


async def _resolve_market_order_price(
    ctx: AsyncSecureClientContext,
    params: PrepareMarketOrderParams,
    *,
    notional: Decimal,
    tick_size: Decimal,
) -> Decimal:
    if params.side == "BUY" and params.max_price is not None:
        return validate_price_on_tick_grid(params.max_price, tick_size, "max_price")
    if params.side == "SELL" and params.min_price is not None:
        return validate_price_on_tick_grid(params.min_price, tick_size, "min_price")
    return await resolve_estimated_market_price(
        ctx,
        token_id=params.token_id,
        side=params.side,
        notional=notional,
        order_type=params.order_type,
        tick_size=tick_size,
    )


def _resolve_market_order_price_sync(
    ctx: SyncSecureClientContext,
    params: PrepareMarketOrderParams,
    *,
    notional: Decimal,
    tick_size: Decimal,
) -> Decimal:
    if params.side == "BUY" and params.max_price is not None:
        return validate_price_on_tick_grid(params.max_price, tick_size, "max_price")
    if params.side == "SELL" and params.min_price is not None:
        return validate_price_on_tick_grid(params.min_price, tick_size, "min_price")
    return resolve_estimated_market_price_sync(
        ctx,
        token_id=params.token_id,
        side=params.side,
        notional=notional,
        order_type=params.order_type,
        tick_size=tick_size,
    )


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


async def _resolve_buy_amount_for_fees(
    ctx: AsyncSecureClientContext, params: PrepareMarketOrderParams, *, price: Decimal
) -> Decimal:
    if params.side != "BUY" or params.max_spend is None or params.amount is None:
        return params.amount if params.amount is not None else params.shares  # type: ignore[return-value]
    condition_id = await resolve_condition_by_token(ctx, token_id=params.token_id)
    fee_info = await fetch_platform_fee_info(ctx, condition_id=condition_id)
    builder_taker_fee_rate = Decimal(0)
    if params.builder_code is not None and params.builder_code != BYTES32_ZERO:
        rates = await fetch_builder_fee_rates(ctx, builder_code=params.builder_code)
        builder_taker_fee_rate = rates.taker
    return adjust_buy_amount_for_fees(
        amount=params.amount,
        price=price,
        max_spend=params.max_spend,
        fee=fee_info,
        builder_taker_fee_rate=builder_taker_fee_rate,
    )


def _resolve_buy_amount_for_fees_sync(
    ctx: SyncSecureClientContext, params: PrepareMarketOrderParams, *, price: Decimal
) -> Decimal:
    if params.side != "BUY" or params.max_spend is None or params.amount is None:
        return params.amount if params.amount is not None else params.shares  # type: ignore[return-value]
    condition_id = resolve_condition_by_token_sync(ctx, token_id=params.token_id)
    fee_info = fetch_platform_fee_info_sync(ctx, condition_id=condition_id)
    builder_taker_fee_rate = Decimal(0)
    if params.builder_code is not None and params.builder_code != BYTES32_ZERO:
        rates = fetch_builder_fee_rates_sync(ctx, builder_code=params.builder_code)
        builder_taker_fee_rate = rates.taker
    return adjust_buy_amount_for_fees(
        amount=params.amount,
        price=price,
        max_spend=params.max_spend,
        fee=fee_info,
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
