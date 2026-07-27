# pyright: reportPrivateUsage=false
import dataclasses
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, SecureClient
from polymarket._internal.actions.account import END_CURSOR
from polymarket.clients._transport import SyncTransport
from polymarket.errors import UserInputError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")

_OPEN_ORDER_PAYLOAD: dict[str, Any] = {
    "asset_id": "8501497",
    "associate_trades": ["trade-1"],
    "created_at": 1700000000000,
    "expiration": 1800000000,
    "id": "order-1",
    "maker_address": "0xMAKER",
    "market": "0xMARKET",
    "order_type": "GTC",
    "original_size": "100",
    "outcome": "Yes",
    "owner": "0xOWNER",
    "price": "0.5",
    "side": "BUY",
    "size_matched": "50",
    "status": "LIVE",
}

_CLOB_TRADE_PAYLOAD: dict[str, Any] = {
    "asset_id": "8501497",
    "bucket_index": 7,
    "fee_rate_bps": "10",
    "id": "trade-1",
    "last_update": 1700000010000,
    "maker_address": "0xMAKER",
    "maker_orders": [
        {
            "asset_id": "8501497",
            "fee_rate_bps": "10",
            "maker_address": "0xMAKER",
            "matched_amount": "5",
            "order_id": "order-1",
            "outcome": "Yes",
            "owner": "0xOWNER",
            "price": "0.5",
            "side": "BUY",
        }
    ],
    "market": "0xMARKET",
    "match_time": 1700000000000,
    "outcome": "Yes",
    "owner": "0xOWNER",
    "price": "0.5",
    "side": "BUY",
    "size": "5",
    "status": "MINED",
    "taker_order_id": "order-2",
    "trader_side": "TAKER",
    "transaction_hash": "0xTX",
}


def _capture(captured: list[httpx.Request], status: int, payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, json=payload, request=request)

    return httpx.MockTransport(handler)


def _install_secure_clob(client: SecureClient, handler: httpx.MockTransport) -> None:
    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=handler),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)


def _assert_l2_headers(request: httpx.Request) -> None:
    headers = request.headers
    assert headers.get("POLY_ADDRESS")
    assert headers.get("POLY_API_KEY") == FAKE_CREDS.key
    assert headers.get("POLY_PASSPHRASE") == FAKE_CREDS.passphrase
    assert headers.get("POLY_SIGNATURE")
    assert headers.get("POLY_TIMESTAMP")


def _make_client() -> SecureClient:
    return SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def test_get_closed_only_mode_returns_bool_and_uses_l2_headers() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, {"closed_only": True}))
        result = client.get_closed_only_mode()

    assert result is True
    request = captured[0]
    assert request.method == "GET"
    assert urlparse(str(request.url)).path == "/auth/ban-status/closed-only"
    _assert_l2_headers(request)


def test_list_open_orders_paginates_until_end_cursor() -> None:
    captured: list[httpx.Request] = []
    responses = iter(
        [
            {"data": [_OPEN_ORDER_PAYLOAD], "next_cursor": "cursor-2", "count": 2},
            {
                "data": [{**_OPEN_ORDER_PAYLOAD, "id": "order-2"}],
                "next_cursor": END_CURSOR,
                "count": 2,
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=next(responses), request=request)

    with _make_client() as client:
        _install_secure_clob(client, httpx.MockTransport(handler))
        ids = [order.id for order in client.list_open_orders(market="0xMARKET").iter_items()]

    assert ids == ["order-1", "order-2"]
    assert len(captured) == 2
    assert urlparse(str(captured[0].url)).path == "/data/orders"
    first_qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert first_qs.get("market") == ["0xMARKET"]
    assert "next_cursor" not in first_qs
    second_qs = parse_qs(urlparse(str(captured[1].url)).query)
    assert second_qs.get("next_cursor") == ["cursor-2"]


def test_get_order_targets_data_order_path() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, _OPEN_ORDER_PAYLOAD))
        order = client.get_order(order_id="order-1")

    assert order.id == "order-1"
    request = captured[0]
    assert urlparse(str(request.url)).path == "/data/order/order-1"
    _assert_l2_headers(request)


def test_list_account_trades_paginates_and_passes_filters() -> None:
    captured: list[httpx.Request] = []
    responses = iter(
        [
            {"data": [_CLOB_TRADE_PAYLOAD], "next_cursor": END_CURSOR, "count": 1},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=next(responses), request=request)

    with _make_client() as client:
        _install_secure_clob(client, httpx.MockTransport(handler))
        trades = [
            t.id
            for t in client.list_account_trades(
                market="0xMARKET", maker_address="0xMAKER"
            ).iter_items()
        ]

    assert trades == ["trade-1"]
    request = captured[0]
    assert urlparse(str(request.url)).path == "/data/trades"
    qs = parse_qs(urlparse(str(request.url)).query)
    assert qs.get("market") == ["0xMARKET"]
    assert qs.get("maker_address") == ["0xMAKER"]


def test_get_notifications_includes_signature_type_for_eoa_wallet() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, []))
        client.get_notifications()

    request = captured[0]
    assert urlparse(str(request.url)).path == "/notifications"
    qs = parse_qs(urlparse(str(request.url)).query)
    assert qs.get("signature_type") == ["0"]
    _assert_l2_headers(request)


def test_drop_notifications_uses_delete_with_comma_separated_ids() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, "OK"))
        client.drop_notifications(ids=["a", "b"])

    request = captured[0]
    assert request.method == "DELETE"
    assert urlparse(str(request.url)).path == "/notifications"
    qs = parse_qs(urlparse(str(request.url)).query)
    assert qs.get("ids") == ["a,b"]
    assert qs.get("signature_type") == ["0"]


def test_drop_notifications_rejects_empty_id_list() -> None:
    with pytest.raises(UserInputError), _make_client() as client:
        client.drop_notifications(ids=[])


def test_get_balance_allowance_for_collateral_omits_token_id() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(
            client,
            _capture(captured, 200, {"balance": "1000", "allowances": {}}),
        )
        result = client.get_balance_allowance(asset_type="COLLATERAL")

    assert result.balance == 1000
    request = captured[0]
    assert urlparse(str(request.url)).path == "/balance-allowance"
    qs = parse_qs(urlparse(str(request.url)).query)
    assert qs.get("asset_type") == ["COLLATERAL"]
    assert qs.get("signature_type") == ["0"]
    assert "token_id" not in qs


def test_get_balance_allowance_for_conditional_includes_token_id() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(
            client,
            _capture(captured, 200, {"balance": "0", "allowances": {}}),
        )
        client.get_balance_allowance(asset_type="CONDITIONAL", token_id="8501497")

    qs = parse_qs(urlparse(str(captured[0].url)).query)
    assert qs.get("asset_type") == ["CONDITIONAL"]
    assert qs.get("token_id") == ["8501497"]
