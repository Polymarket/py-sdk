# pyright: reportPrivateUsage=false
import dataclasses
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from polymarket import ApiKeyCreds, SecureClient
from polymarket._internal.actions.rewards import END_CURSOR
from polymarket.clients._transport import SyncTransport

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")
_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"


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


def _make_client() -> SecureClient:
    return SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def test_get_order_scoring_routes_to_order_scoring_endpoint() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, {"scoring": True}))
        result = client.get_order_scoring(order_id="ord-1")

    assert result is True
    request = captured[0]
    assert urlparse(str(request.url)).path == "/order-scoring"
    qs = parse_qs(urlparse(str(request.url)).query)
    assert qs.get("order_id") == ["ord-1"]
    assert request.headers.get("POLY_SIGNATURE")


def test_get_orders_scoring_posts_order_ids_and_parses_map() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, {"ord-1": True, "ord-2": False}))
        result = client.get_orders_scoring(order_ids=["ord-1", "ord-2"])

    assert result == {"ord-1": True, "ord-2": False}
    request = captured[0]
    assert request.method == "POST"
    assert urlparse(str(request.url)).path == "/orders-scoring"
    assert b"ord-1" in request.content
    assert b"ord-2" in request.content


def test_list_user_earnings_for_day_passes_signature_type_and_date() -> None:
    captured: list[httpx.Request] = []

    page_payload: dict[str, Any] = {
        "data": [
            {
                "asset_address": "0xASSET",
                "asset_rate": "0.001",
                "condition_id": _CONDITION_ID,
                "date": 1700000000000,
                "earnings": "1.5",
                "maker_address": "0xMAKER",
            }
        ],
        "next_cursor": END_CURSOR,
        "count": 1,
    }

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, page_payload))
        earnings = list(client.list_user_earnings_for_day(date="2026-01-01").iter_items())

    assert len(earnings) == 1
    request = captured[0]
    assert urlparse(str(request.url)).path == "/rewards/user"
    qs = parse_qs(urlparse(str(request.url)).query)
    assert qs.get("date") == ["2026-01-01"]
    assert qs.get("signature_type") == ["0"]


def test_get_total_earnings_for_user_for_day_routes_to_total_endpoint() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(
            client,
            _capture(
                captured,
                200,
                [
                    {
                        "asset_address": "0xASSET",
                        "asset_rate": "0.001",
                        "date": 1700000000000,
                        "earnings": "10.0",
                        "maker_address": "0xMAKER",
                    }
                ],
            ),
        )
        totals = client.get_total_earnings_for_user_for_day(date="2026-01-01")

    assert len(totals) == 1
    request = captured[0]
    assert urlparse(str(request.url)).path == "/rewards/user/total"


def test_get_reward_percentages_routes_to_percentages_endpoint() -> None:
    captured: list[httpx.Request] = []

    with _make_client() as client:
        _install_secure_clob(client, _capture(captured, 200, {_CONDITION_ID: 0.5}))
        result = client.get_reward_percentages()

    assert _CONDITION_ID in result
    request = captured[0]
    assert urlparse(str(request.url)).path == "/rewards/user/percentages"
    qs = parse_qs(urlparse(str(request.url)).query)
    assert qs.get("signature_type") == ["0"]


def test_order_heartbeats_sign_exact_body_and_return_rotated_id() -> None:
    from polymarket._internal.hmac import build_hmac_signature

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"heartbeat_id": "next-id"}
            if request.url.path == "/v1/heartbeats"
            else {"status": "ok"},
            request=request,
        )

    with _make_client() as client:
        _install_secure_clob(client, httpx.MockTransport(handler))
        heartbeat = client.send_order_heartbeat()
        client.send_order_heartbeat(heartbeat_id=heartbeat.heartbeat_id)
        assert client.send_legacy_order_heartbeat().status == "ok"
    assert [request.content for request in captured] == [
        b'{"heartbeat_id":""}',
        b'{"heartbeat_id":"next-id"}',
        b"",
    ]
    for request in captured:
        signature = build_hmac_signature(
            secret=FAKE_CREDS.secret,
            timestamp=int(request.headers["POLY_TIMESTAMP"]),
            method="POST",
            path=request.url.path,
            body=request.content.decode() if request.content else None,
        )
        assert request.headers["POLY_SIGNATURE"] == signature
        assert request.headers["POLY_API_KEY"] == FAKE_CREDS.key
