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
                    "size": position.size if position.size is not None else "0",
                    "currentValue": (
                        position.current_value if position.current_value is not None else "0"
                    ),
                    "avgPrice": position.avg_price if position.avg_price is not None else "",
                    "curPrice": position.cur_price if position.cur_price is not None else "",
                    "redeemable": position.redeemable if position.redeemable is not None else False,
                    "mergeable": position.mergeable if position.mergeable is not None else False,
                    "assetId": position.asset_id or "",
                }
                for position in positions
            ]
        )


if __name__ == "__main__":
    main()
