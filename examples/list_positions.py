"""List a wallet's open positions.

    POLYMARKET_DEPOSIT_WALLET=0x... uv run python -m examples.list_positions

Reads only — no signing key required, just a wallet address to inspect.
"""

from __future__ import annotations

from examples.lib.env import require_env
from examples.lib.tables import print_rows_table
from polymarket import PublicClient


def main() -> None:
    wallet = require_env("POLYMARKET_DEPOSIT_WALLET")
    with PublicClient() as client:
        positions = list(client.list_positions(user=wallet, page_size=100).iter_items())

        print(f"Found {len(positions)} open positions for {wallet}")
        print_rows_table(
            [
                {
                    "title": position.title or position.slug or position.condition_id,
                    "outcome": position.outcome or "",
                    "current_size": position.current_size,
                    "current_value": position.current_value,
                    "avg_price": position.avg_price,
                    "current_price": position.current_price,
                    "redeemable": position.redeemable,
                    "mergeable": position.mergeable,
                    "asset_id": position.asset_id,
                }
                for position in positions
            ]
        )


if __name__ == "__main__":
    main()
