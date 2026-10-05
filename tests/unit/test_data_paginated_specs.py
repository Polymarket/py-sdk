from typing import Any

import pytest

from polymarket import PublicClient
from polymarket.errors import UserInputError


@pytest.mark.parametrize(
    "method,kwargs,cap",
    [
        ("list_trades", {}, 1000),
        ("list_activity", {"user": "wallet"}, 1000),
        ("list_combo_activity", {"user": "wallet"}, 1000),
        ("list_positions", {"user": "wallet"}, 1000),
        ("list_combo_positions", {"user": "wallet"}, 1000),
        ("list_market_holders", {"condition_ids": "0x" + "ab" * 32}, 1000),
        ("list_market_holders", {"condition_ids": "0x" + "ab" * 32, "include_pnl": True}, 100),
        ("list_trader_leaderboard", {}, 1000),
        ("list_biggest_winners", {}, 1000),
        ("list_builder_leaderboard", {}, 1000),
        ("list_price_history", {"asset_id": "1", "interval": "1d"}, 10000),
    ],
)
def test_page_caps(method: str, kwargs: dict[str, Any], cap: int) -> None:
    with PublicClient() as client:
        getattr(client, method)(**kwargs, page_size=cap)
        for size in (0, cap + 1):
            with pytest.raises(UserInputError):
                getattr(client, method)(**kwargs, page_size=size)
