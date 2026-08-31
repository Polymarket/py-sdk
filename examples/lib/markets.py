"""Find a live, tradable market for the order examples.

Port of the ts-sdk `findOrderExampleMarket` helper: scan liquid markets and
return the first binary market that has an order book, is accepting orders, has
a usable price band, and a non-empty book.
"""

from __future__ import annotations

from polymarket import ClobAssetId, Market, PolymarketError, PublicClient, SecureClient

# Either client exposes the read methods this helper needs.
MarketLookupClient = PublicClient | SecureClient


def find_order_example_market(client: MarketLookupClient) -> Market:
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
        if _is_order_example_candidate(client, candidate):
            return candidate
    raise SystemExit("Could not find a live market for the order example.")


def _is_order_example_candidate(client: MarketLookupClient, market: Market) -> bool:
    asset_id = market_yes_asset_id(market)
    if (
        market.state.enable_order_book is not True
        or market.state.accepting_orders is not True
        or market.trading.minimum_order_size is None
        or market.trading.minimum_tick_size is None
        or asset_id is None
        or market.prices.best_ask is None
        or market.prices.best_ask >= 1
        or market.prices.best_bid is None
        or market.prices.best_bid <= 0
    ):
        return False

    try:
        book = client.get_order_book(asset_id=asset_id)
    except PolymarketError:
        return False
    return len(book.asks) > 0 and len(book.bids) > 0


def market_yes_asset_id(market: Market) -> ClobAssetId | None:
    """Return the market's tradable YES asset using its outcome-pair representation."""

    if market.outcomes.yes.token_id is not None and market.outcomes.no.token_id is not None:
        return market.outcomes.yes.token_id
    if market.outcomes.yes.position_id is not None and market.outcomes.no.position_id is not None:
        return market.outcomes.yes.position_id
    return None
