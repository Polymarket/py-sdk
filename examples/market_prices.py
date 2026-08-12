"""Read CLOB market data — order book, price, midpoint, spread, last trade.

    uv run python -m examples.market_prices

No credentials required. Discovers a token id from a live market, then queries
its prices and book.
"""

from __future__ import annotations

from examples.lib.tables import print_values_table
from polymarket import PublicClient


def main() -> None:
    with PublicClient() as client:
        items = client.list_markets(page_size=1).first_page().items
        if not items:
            raise SystemExit("No live markets found.")
        market = items[0]
        token_id = market.outcomes.yes.token_id
        if token_id is None:
            raise SystemExit("Discovered market has no tradable YES token; try again.")

        order_book = client.get_order_book(token_id=token_id)
        buy_price = client.get_price(token_id=token_id, side="BUY")
        midpoint = client.get_midpoint(token_id=token_id)
        spread = client.get_spread(token_id=token_id)
        last_trade = client.get_last_trade_price(token_id=token_id)

        print_values_table(
            {
                "market": market.question or market.slug or market.id,
                "tokenId": token_id,
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
