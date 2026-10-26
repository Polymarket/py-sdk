"""Build and sign a market order — without posting it.

    POLYMARKET_PRIVATE_KEY=0x... POLYMARKET_DEPOSIT_WALLET=0x... \
        uv run python -m examples.create_market_order

`create_market_order` signs the order locally and returns it; it does NOT submit
to the exchange. Use `place_market_order` (or `post_order`) to actually trade.
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

        # `find_order_example_market` guarantees minimum_order_size is set.
        amount = market.trading.minimum_order_size
        if amount is None:
            raise SystemExit("Selected market has no minimum order size.")

        estimated_price = client.estimate_market_price(
            asset_id=asset_id, side="BUY", amount=amount, order_type="FAK"
        )
        order = client.create_market_order(
            asset_id=asset_id,
            side="BUY",
            amount=amount,
            order_type="FAK",
        )

        print("Signed market order (built locally, not submitted):")
        print_values_table(
            {
                "market": market.question or market.slug or market.id,
                "minimumOrderSize": amount,
                "assetId": order.token_id,
                "side": order.side,
                "orderType": order.order_type,
                "estimatedPrice": estimated_price,
                "maker": order.maker,
                "makerAmount": order.maker_amount,
                "takerAmount": order.taker_amount,
            }
        )


if __name__ == "__main__":
    main()
