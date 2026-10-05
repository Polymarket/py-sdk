"""Read CLOB market data — order book, price, midpoint, spread, last trade.

    uv run python -m examples.market_prices

No credentials required. Discovers an asset ID from a live market, then queries
its prices and book.
"""

from __future__ import annotations

from examples.lib.markets import market_yes_asset_id
from examples.lib.tables import print_values_table
from polymarket import PublicClient


def main() -> None:
    with PublicClient() as client:
        items = client.list_markets(page_size=1).first_page().items
        if not items:
            raise SystemExit("No live markets found.")
        market = items[0]
        asset_id = market_yes_asset_id(market)
        if asset_id is None:
            raise SystemExit("Discovered market has no tradable YES asset; try again.")

        order_book = client.get_order_book(asset_id=asset_id)
        buy_price = client.get_price(asset_id=asset_id, side="BUY")
        midpoint = client.get_midpoint(asset_id=asset_id)
        spread = client.get_spread(asset_id=asset_id)
        last_trade = client.get_last_trade_price(asset_id=asset_id)

        print_values_table(
            {
                "market": market.question or market.slug or market.id,
                "assetId": asset_id,
                "bids": len(order_book.bids),
                "asks": len(order_book.asks),
                "buyPrice": buy_price,
                "midpoint": midpoint,
                "spread": spread,
                "lastTradePrice": last_trade.price if last_trade is not None else "N/A",
                "lastTradeSide": last_trade.side if last_trade is not None else "N/A",
            }
        )


if __name__ == "__main__":
    main()
