from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from polymarket._internal.actions import clob as _clob_actions
from polymarket._internal.actions.exchange_asset import resolve_asset_id
from polymarket._internal.actions.orders._numeric import coerce_positive_decimal
from polymarket._internal.actions.orders.types import MarketOrderType
from polymarket._internal.context import AsyncClientContext, SyncClientContext
from polymarket.errors import InsufficientLiquidityError, UnexpectedResponseError, UserInputError
from polymarket.models.clob.order_book import OrderBook, OrderBookLevel
from polymarket.models.types import ClobAssetId, OrderSide


@dataclass(frozen=True, slots=True)
class ResolvedMarketPrice:
    price: Decimal
    tick_size: Decimal
    neg_risk: bool


def _validate_estimate_inputs(
    *,
    asset_id: str | None,
    token_id: str | None,
    side: OrderSide,
    amount: Decimal | int | float | str | None,
    shares: Decimal | int | float | str | None,
    order_type: MarketOrderType,
) -> tuple[ClobAssetId, Decimal]:
    validated_asset = resolve_asset_id(asset_id=asset_id, token_id=token_id)
    if side == "BUY":
        if amount is None:
            raise UserInputError("amount is required for BUY estimates.")
        if shares is not None:
            raise UserInputError("shares must not be set for BUY estimates.")
        notional = coerce_positive_decimal("amount", amount)
    elif side == "SELL":
        if shares is None:
            raise UserInputError("shares is required for SELL estimates.")
        if amount is not None:
            raise UserInputError("amount must not be set for SELL estimates.")
        notional = coerce_positive_decimal("shares", shares)
    else:
        raise UserInputError(f"side must be 'BUY' or 'SELL', got {side!r}.")
    if order_type not in ("FAK", "FOK"):
        raise UserInputError(f"order_type must be 'FAK' or 'FOK', got {order_type!r}.")
    return validated_asset, notional


async def estimate_market_price(
    ctx: AsyncClientContext,
    *,
    asset_id: str | None = None,
    token_id: str | None = None,
    side: OrderSide,
    amount: Decimal | int | float | str | None = None,
    shares: Decimal | int | float | str | None = None,
    order_type: MarketOrderType = "FOK",
) -> Decimal:
    validated_token, notional = _validate_estimate_inputs(
        asset_id=asset_id,
        token_id=token_id,
        side=side,
        amount=amount,
        shares=shares,
        order_type=order_type,
    )
    return await resolve_estimated_market_price(
        ctx,
        token_id=validated_token,
        side=side,
        notional=notional,
        order_type=order_type,
    )


def estimate_market_price_sync(
    ctx: SyncClientContext,
    *,
    asset_id: str | None = None,
    token_id: str | None = None,
    side: OrderSide,
    amount: Decimal | int | float | str | None = None,
    shares: Decimal | int | float | str | None = None,
    order_type: MarketOrderType = "FOK",
) -> Decimal:
    validated_token, notional = _validate_estimate_inputs(
        asset_id=asset_id,
        token_id=token_id,
        side=side,
        amount=amount,
        shares=shares,
        order_type=order_type,
    )
    return resolve_estimated_market_price_sync(
        ctx,
        token_id=validated_token,
        side=side,
        notional=notional,
        order_type=order_type,
    )


async def resolve_estimated_market_price(
    ctx: AsyncClientContext,
    *,
    token_id: ClobAssetId,
    side: OrderSide,
    notional: Decimal,
    order_type: MarketOrderType,
) -> Decimal:
    return (
        await resolve_market_price_context(
            ctx,
            token_id=token_id,
            side=side,
            notional=notional,
            order_type=order_type,
        )
    ).price


async def resolve_market_price_context(
    ctx: AsyncClientContext,
    *,
    token_id: ClobAssetId,
    side: OrderSide,
    notional: Decimal,
    order_type: MarketOrderType,
) -> ResolvedMarketPrice:
    path, params = _clob_actions.build_order_book_request(token_id=token_id)
    book = _clob_actions.parse_order_book(await ctx.clob.get_json(path, params=params))
    return _resolve_market_price_context(
        book, token_id=token_id, side=side, notional=notional, order_type=order_type
    )


def resolve_estimated_market_price_sync(
    ctx: SyncClientContext,
    *,
    token_id: ClobAssetId,
    side: OrderSide,
    notional: Decimal,
    order_type: MarketOrderType,
) -> Decimal:
    return resolve_market_price_context_sync(
        ctx,
        token_id=token_id,
        side=side,
        notional=notional,
        order_type=order_type,
    ).price


def resolve_market_price_context_sync(
    ctx: SyncClientContext,
    *,
    token_id: ClobAssetId,
    side: OrderSide,
    notional: Decimal,
    order_type: MarketOrderType,
) -> ResolvedMarketPrice:
    path, params = _clob_actions.build_order_book_request(token_id=token_id)
    book = _clob_actions.parse_order_book(ctx.clob.get_json(path, params=params))
    return _resolve_market_price_context(
        book, token_id=token_id, side=side, notional=notional, order_type=order_type
    )


def _resolve_market_price_context(
    book: OrderBook,
    *,
    token_id: ClobAssetId,
    side: OrderSide,
    notional: Decimal,
    order_type: MarketOrderType,
) -> ResolvedMarketPrice:
    if book.asset_id != token_id:
        raise UnexpectedResponseError(
            f"Order book returned asset {book.asset_id} for requested asset {token_id}."
        )
    if side == "BUY":
        price = _calculate_buy_market_price(book.asks, notional, order_type)
    else:
        price = _calculate_sell_market_price(book.bids, notional, order_type)
    if price < book.tick_size or price > Decimal(1) - book.tick_size:
        raise UnexpectedResponseError(
            f"Resolved market price {price} fell outside the valid range for tick size "
            f"{book.tick_size}."
        )
    return ResolvedMarketPrice(
        price=price,
        tick_size=book.tick_size,
        neg_risk=book.neg_risk,
    )


def _calculate_buy_market_price(
    asks: Sequence[OrderBookLevel], amount: Decimal, order_type: MarketOrderType
) -> Decimal:
    if not asks:
        raise InsufficientLiquidityError("No resting liquidity.")
    cumulative = Decimal(0)
    for level in reversed(asks):
        cumulative += level.size * level.price
        if cumulative >= amount:
            return level.price
    if order_type == "FOK":
        raise InsufficientLiquidityError("Insufficient liquidity for full fill.")
    return asks[0].price


def _calculate_sell_market_price(
    bids: Sequence[OrderBookLevel], shares: Decimal, order_type: MarketOrderType
) -> Decimal:
    if not bids:
        raise InsufficientLiquidityError("No resting liquidity.")
    cumulative = Decimal(0)
    for level in reversed(bids):
        cumulative += level.size
        if cumulative >= shares:
            return level.price
    if order_type == "FOK":
        raise InsufficientLiquidityError("Insufficient liquidity for full fill.")
    return bids[0].price


__all__ = [
    "ResolvedMarketPrice",
    "estimate_market_price",
    "estimate_market_price_sync",
    "resolve_estimated_market_price",
    "resolve_estimated_market_price_sync",
    "resolve_market_price_context",
    "resolve_market_price_context_sync",
]
