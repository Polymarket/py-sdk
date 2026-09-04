"""Find a live, tradable market for the order examples.

Port of the ts-sdk `findOrderExampleMarket` helper: scan liquid markets and
return the first binary market that has an order book, is accepting orders, has
a usable price band, and a non-empty book.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from polymarket import ClobAssetId, Market, PolymarketError, PublicClient, SecureClient

# Either client exposes the read methods this helper needs.
MarketLookupClient = PublicClient | SecureClient


class OrderExampleMarketVersion(IntEnum):
    V1 = 1
    V2 = 2


@dataclass(frozen=True, slots=True)
class OrderExampleMarket:
    market: Market
    version: OrderExampleMarketVersion


def find_order_example_market(client: MarketLookupClient) -> OrderExampleMarket:
    """Return a liquid, order-book-enabled binary market suitable for order examples."""
    paginator = client.list_markets(
        closed=False,
        liquidity_num_min=1000,
        page_size=1000,
        order="liquidityNum",
        ascending=False,
        sports_market_types=["moneyline", "spreads", "totals"],
    )
    for candidate in paginator.iter_items():
        version = _order_example_market_version(client, candidate)
        if version is not None:
            return OrderExampleMarket(market=candidate, version=version)
    raise SystemExit("Could not find a live market for the order example.")


def _order_example_market_version(
    client: MarketLookupClient, market: Market
) -> OrderExampleMarketVersion | None:
    version = resolve_order_example_market_version(market)
    if (
        version is None
        or market.state.enable_order_book is not True
        or market.state.accepting_orders is not True
        or market.trading.minimum_order_size is None
        or market.trading.minimum_tick_size is None
        or market.prices.best_ask is None
        or market.prices.best_ask >= 1
        or market.prices.best_bid is None
        or market.prices.best_bid <= 0
    ):
        return None

    asset_id = (
        market.outcomes.yes.token_id
        if version is OrderExampleMarketVersion.V1
        else market.outcomes.yes.position_id
    )
    if asset_id is None:
        return None

    try:
        book = client.get_order_book(asset_id=asset_id)
    except PolymarketError:
        return None
    return version if book.asks and book.bids else None


def resolve_order_example_market_version(market: Market) -> OrderExampleMarketVersion | None:
    """Resolve whether an order example should use CTF token IDs or V2 position IDs."""

    # CTF markets may also expose position IDs for Combos, so a complete token
    # pair remains the V1 discriminant when both pairs are present.
    if market.outcomes.yes.token_id is not None and market.outcomes.no.token_id is not None:
        return OrderExampleMarketVersion.V1
    if market.outcomes.yes.position_id is not None and market.outcomes.no.position_id is not None:
        return OrderExampleMarketVersion.V2
    return None


def market_yes_asset_id(market: Market) -> ClobAssetId | None:
    """Return the market's tradable YES asset using its outcome-pair representation."""

    version = resolve_order_example_market_version(market)
    if version is OrderExampleMarketVersion.V1:
        return market.outcomes.yes.token_id
    if version is OrderExampleMarketVersion.V2:
        return market.outcomes.yes.position_id
    return None
