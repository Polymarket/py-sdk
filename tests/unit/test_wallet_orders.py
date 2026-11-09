# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx
from _relayer_helpers import FAKE_CREDS, make_deposit_client, make_sync_deposit_client

from polymarket._internal.actions.account import (
    build_list_wallet_open_orders_request,
    parse_wallet_open_orders_page,
)
from polymarket._internal.actions.orders.cancel import build_cancel_wallet_orders_request
from polymarket.errors import UserInputError


def test_wallet_orders_filters_and_redacted_owner() -> None:
    signer = "0x" + "12" * 20
    owner = "0x" + "56" * 20
    path, params = build_list_wallet_open_orders_request(
        asset_id="123", market="condition", signer_addresses=[signer, owner], cursor="next"
    )
    assert path == "/data/wallet-open-orders"
    assert params == {
        "asset_id": "123",
        "market": "condition",
        "session_keys": f"{signer},{owner}",
        "cursor": "next",
    }
    page = parse_wallet_open_orders_page(
        {
            "data": [
                {
                    "id": "order",
                    "asset_id": "123",
                    "market": "condition",
                    "signer_address": signer,
                    "maker_address": "0x" + "34" * 20,
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
    order = page.items[0]
    assert order.owner is None
    assert order.signer_address == signer
    assert order.price == Decimal("0.05")
    assert order.size_matched == Decimal("5")
    assert order.created_at == datetime.fromtimestamp(1700000000, tz=UTC)
    assert order.expires_at is None
    assert not page.has_more


@pytest.mark.parametrize("signer_addresses", [[], ["0x" + "12" * 20] * 51, ["not-an-address"]])
def test_wallet_orders_reject_invalid_signer_filters(signer_addresses: list[str]) -> None:
    # An empty filter must not widen into every signer's orders.
    with pytest.raises(UserInputError, match="signer_addresses"):
        build_list_wallet_open_orders_request(signer_addresses=signer_addresses)


def test_empty_wallet_order_page_can_continue() -> None:
    page = parse_wallet_open_orders_page({"data": [], "next_cursor": "next"})
    assert page.items == ()
    assert page.has_more
    assert page.next_cursor == "next"


@pytest.mark.parametrize(
    "order_ids",
    [
        [],
        ["id"] * 1001,
        ["malformed"],
    ],
)
def test_wallet_cancel_rejects_invalid_order_ids(order_ids: list[str]) -> None:
    with pytest.raises(UserInputError):
        build_cancel_wallet_orders_request(order_ids=order_ids)


def test_wallet_cancel_keeps_requested_ids() -> None:
    order_id = "0x" + "12" * 32
    assert build_cancel_wallet_orders_request(order_ids=[order_id]) == (
        "/cancel-wallet-orders",
        {"order_ids": [order_id]},
    )


@pytest.mark.parametrize("async_client", [False, True])
def test_wallet_order_clients_follow_empty_pages_and_cancel(async_client: bool) -> None:
    order_id = "0x" + "12" * 32
    session_address = "0x" + "34" * 20
    cancellation_bodies: list[dict[str, object]] = []
    with respx.mock as router:

        def wallet_orders(request: httpx.Request) -> httpx.Response:
            assert request.headers["POLY_API_KEY"] == FAKE_CREDS.key
            assert request.headers["POLY_SIGNATURE"]
            assert request.url.params["session_keys"] == session_address
            assert request.url.params["asset_id"] == "123"
            assert "next_cursor" not in request.url.params
            if "cursor" not in request.url.params:
                return httpx.Response(200, json={"data": [], "next_cursor": "next"})
            assert request.url.params["cursor"] == "next"
            return httpx.Response(200, json={"data": [], "next_cursor": ""})

        router.get("https://clob.polymarket.com/data/wallet-open-orders").mock(
            side_effect=wallet_orders
        )

        def cancel_wallet_orders(request: httpx.Request) -> httpx.Response:
            assert request.headers["POLY_API_KEY"] == FAKE_CREDS.key
            assert request.headers["POLY_SIGNATURE"]
            cancellation_bodies.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "canceled": [order_id] if len(cancellation_bodies) == 1 else [],
                    "not_canceled": {},
                },
            )

        cancel_route = router.delete("https://clob.polymarket.com/cancel-wallet-orders").mock(
            side_effect=cancel_wallet_orders
        )

        async def run() -> None:
            client = await make_deposit_client()
            try:
                pages = [
                    page
                    async for page in client.list_wallet_open_orders(
                        asset_id="123", signer_addresses=[session_address]
                    )
                ]
                assert len(pages) == 2
                assert pages[0].items == () and pages[0].has_more
                assert not pages[1].has_more
                cancellation = await client.cancel_wallet_orders(order_ids=[order_id])
                assert cancellation.canceled == (order_id,)
                all_cancellation = await client.cancel_all_wallet_orders()
                assert all_cancellation.canceled == ()
                owner_context = client._ctx
                client._ctx = dataclasses.replace(owner_context, signer_type="SESSION_KEY")
                with pytest.raises(UserInputError, match="Deposit Wallet owner"):
                    await client.cancel_wallet_orders(order_ids=[order_id])
                with pytest.raises(UserInputError, match="Deposit Wallet owner"):
                    await client.cancel_all_wallet_orders()
                client._ctx = owner_context
            finally:
                await client.close()

        if async_client:
            asyncio.run(run())
        else:
            with make_sync_deposit_client() as client:
                pages = list(
                    client.list_wallet_open_orders(
                        asset_id="123", signer_addresses=[session_address]
                    )
                )
                assert len(pages) == 2
                assert pages[0].items == () and pages[0].has_more
                assert not pages[1].has_more
                cancellation = client.cancel_wallet_orders(order_ids=[order_id])
                assert cancellation.canceled == (order_id,)
                all_cancellation = client.cancel_all_wallet_orders()
                assert all_cancellation.canceled == ()
                owner_context = client._ctx
                client._ctx = dataclasses.replace(owner_context, signer_type="SESSION_KEY")
                with pytest.raises(UserInputError, match="Deposit Wallet owner"):
                    client.cancel_wallet_orders(order_ids=[order_id])
                with pytest.raises(UserInputError, match="Deposit Wallet owner"):
                    client.cancel_all_wallet_orders()
                client._ctx = owner_context
        assert cancel_route.call_count == 2
        assert cancellation_bodies == [{"order_ids": [order_id]}, {"all": True}]
