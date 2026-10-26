"""Build and sign a limit order — without posting it.

    POLYMARKET_PRIVATE_KEY=0x... POLYMARKET_DEPOSIT_WALLET=0x... \
        uv run python -m examples.create_limit_order

`create_limit_order` signs the order locally and returns it; it does NOT submit
to the exchange. Use `place_limit_order` (or `post_order`) to actually trade.
"""

from __future__ import annotations

from examples.lib.env import require_env
from examples.lib.markets import OrderExampleMarketVersion, find_order_example_market
from examples.lib.tables import print_values_table
from polymarket import SecureClient


def main() -> None:
    client = SecureClient.create(
        private_key=require_env("POLYMARKET_PRIVATE_KEY"),
        wallet=require_env("POLYMARKET_DEPOSIT_WALLET"),
    )
    with client:
        selected = find_order_example_market(client)
        market = selected.market
        # CTF markets trade by token ID; Polymarket V2 markets trade by position ID.
        asset_id = (
            market.outcomes.yes.token_id
            if selected.version is OrderExampleMarketVersion.V1
            else market.outcomes.yes.position_id
        )
        if asset_id is None:
            raise SystemExit("Selected market has no tradable YES asset.")

        # `find_order_example_market` guarantees these are set. Bid one tick above
        # zero and one minimum lot — a passive price that will rest on the book.
        price = market.trading.minimum_tick_size
        size = market.trading.minimum_order_size
        if price is None or size is None:
            raise SystemExit("Selected market is missing tick size or order size.")
        order = client.create_limit_order(
            asset_id=asset_id,
            price=price,
            size=size,
            side="BUY",
        )

        print("Signed limit order (built locally, not submitted):")
        print_values_table(
            {
                "market": market.question or market.slug or market.id,
                "minimumTickSize": price,
                "minimumOrderSize": size,
                "assetId": order.token_id,
                "side": order.side,
                "orderType": order.order_type,
                "maker": order.maker,
                "makerAmount": order.maker_amount,
                "takerAmount": order.taker_amount,
            }
        )


if __name__ == "__main__":
    main()
