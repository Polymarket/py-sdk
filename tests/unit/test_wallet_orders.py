# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import json

import httpx
import pytest
import respx
from _relayer_helpers import make_deposit_client, make_sync_deposit_client

from polymarket._internal.actions.account import (
    build_list_wallet_open_orders_request,
    parse_wallet_open_orders_page,
)
from polymarket._internal.actions.orders.cancel import build_cancel_wallet_orders_request
from polymarket.errors import UserInputError

_ORDER_ID = "0x" + "12" * 32
_SIGNER = "0x" + "34" * 20


def test_wallet_orders_filters_and_redacted_owner() -> None:
    _, params = build_list_wallet_open_orders_request(
        asset_id="123", signer_addresses=[_SIGNER, _SIGNER]
    )
    assert params == {"asset_id": "123", "session_keys": f"{_SIGNER},{_SIGNER}"}
    page = parse_wallet_open_orders_page(
        {
            "data": [
                {
                    "id": "order",
                    "asset_id": "123",
                    "market": "condition",
                    "signer_address": _SIGNER,
                    "maker_address": _SIGNER,
                    "owner": "",
                    "side": "BUY",
                    "price": "0.05",
                    "original_size": "10",
                    "size_matched": "5",
                    "outcome": "Yes",
                    "order_type": "GTC",
                    "status": "LIVE",
                    "created_at": 1700000000,
                    "expiration": "0",
                }
            ],
            "next_cursor": "",
        }
    )
    assert page.items[0].owner is None
    assert not page.has_more


@pytest.mark.parametrize("signer_addresses", [[], [_SIGNER] * 51, ["not-an-address"]])
def test_wallet_orders_reject_invalid_signer_filters(signer_addresses: list[str]) -> None:
    with pytest.raises(UserInputError, match="signer_addresses"):
        build_list_wallet_open_orders_request(signer_addresses=signer_addresses)


@pytest.mark.parametrize("order_ids", [[], [_ORDER_ID] * 1001, ["malformed"]])
def test_wallet_cancel_rejects_invalid_order_ids(order_ids: list[str]) -> None:
    with pytest.raises(UserInputError, match="order_ids"):
        build_cancel_wallet_orders_request(order_ids=order_ids)


def _wallet_orders(request: httpx.Request) -> httpx.Response:
    # The first page is empty but continues; iteration must follow it.
    cursor = "" if "cursor" in request.url.params else "next"
    return httpx.Response(200, json={"data": [], "next_cursor": cursor})


@pytest.mark.parametrize("async_client", [False, True])
def test_wallet_order_clients_follow_cursor_and_cancel(async_client: bool) -> None:
    bodies: list[object] = []
    with respx.mock as router:
        router.get("https://clob.polymarket.com/data/wallet-open-orders").mock(
            side_effect=_wallet_orders
        )

        def cancel(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"canceled": [], "not_canceled": {}})

        router.delete("https://clob.polymarket.com/cancel-wallet-orders").mock(side_effect=cancel)

        async def run_async() -> int:
            client = await make_deposit_client()
            try:
                pages = [page async for page in client.list_wallet_open_orders()]
                await client.cancel_wallet_orders(order_ids=[_ORDER_ID])
                await client.cancel_all_wallet_orders()
                client._ctx = dataclasses.replace(client._ctx, signer_type="SESSION_KEY")
                with pytest.raises(UserInputError, match="Deposit Wallet owner"):
                    await client.cancel_all_wallet_orders()
                return len(pages)
            finally:
                await client.close()

        if async_client:
            page_count = asyncio.run(run_async())
        else:
            with make_sync_deposit_client() as client:
                page_count = len(list(client.list_wallet_open_orders()))
                client.cancel_wallet_orders(order_ids=[_ORDER_ID])
                client.cancel_all_wallet_orders()
                client._ctx = dataclasses.replace(client._ctx, signer_type="SESSION_KEY")
                with pytest.raises(UserInputError, match="Deposit Wallet owner"):
                    client.cancel_all_wallet_orders()

    assert page_count == 2
    assert bodies == [{"order_ids": [_ORDER_ID]}, {"all": True}]
