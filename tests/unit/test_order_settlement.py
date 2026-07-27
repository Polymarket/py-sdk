# pyright: reportPrivateUsage=false
import dataclasses
from decimal import Decimal
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, SecureClient
from polymarket.clients._transport import SyncTransport
from polymarket.errors import TimeoutError, TransactionFailedError
from polymarket.models.clob.order_response import AcceptedOrder
from polymarket.types import TransactionHash

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")

TX_HASH = "0x" + "11" * 32
OTHER_TX_HASH = "0x" + "22" * 32


def _make_client() -> SecureClient:
    return SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )


def _trade_payload(
    *,
    trade_id: str = "trade-1",
    status: str = "TRADE_STATUS_MATCHED",
    transaction_hash: str = "",
) -> dict[str, Any]:
    return {
        "id": trade_id,
        "market": "0xmarket",
        "asset_id": "123",
        "owner": "owner",
        "maker_address": "0xmaker",
        "taker_order_id": "0xorder",
        "side": "BUY",
        "trader_side": "TAKER",
        "price": "0.5",
        "size": "100",
        "outcome": "YES",
        "status": status,
        "fee_rate_bps": "0",
        "bucket_index": 0,
        "transaction_hash": transaction_hash,
        "maker_orders": [],
        "match_time": "1752500000",
        "last_update": "1752500000",
    }


def _install_trades_handler(
    client: SecureClient, pages_by_trade_id: dict[str, list[list[dict[str, Any]]]]
) -> list[httpx.Request]:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        parsed = urlparse(str(request.url))
        if parsed.path != "/data/trades":
            return httpx.Response(404, json={"error": "not mocked"}, request=request)
        trade_id = parse_qs(parsed.query)["id"][0]
        queued = pages_by_trade_id[trade_id]
        items = queued.pop(0) if len(queued) > 1 else queued[0]
        return httpx.Response(200, json={"data": items, "next_cursor": "LTE="}, request=request)

    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(base_url="https://clob.test", transport=httpx.MockTransport(handler)),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)
    return captured


def _accepted_order(
    *,
    status: str = "matched",
    trade_ids: tuple[str, ...] = (),
    transactions_hashes: tuple[str, ...] = (),
) -> AcceptedOrder:
    return AcceptedOrder(
        order_id="0xorder",
        status=cast(Any, status),
        making_amount=Decimal("50"),
        taking_amount=Decimal("100"),
        trade_ids=trade_ids,
        transactions_hashes=cast(tuple[TransactionHash, ...], transactions_hashes),
    )


def test_returns_empty_immediately_when_order_had_no_fills() -> None:
    client = _make_client()
    captured = _install_trades_handler(client, {})

    hashes = client.wait_for_order_fill_settlement(_accepted_order(status="live"))

    assert hashes == ()
    assert captured == []


def test_returns_hashes_from_order_when_there_are_no_trade_ids_to_poll() -> None:
    client = _make_client()
    captured = _install_trades_handler(client, {})

    hashes = client.wait_for_order_fill_settlement(_accepted_order(transactions_hashes=(TX_HASH,)))

    assert hashes == (TX_HASH,)
    assert captured == []


def test_polls_trade_ids_even_when_order_includes_hashes() -> None:
    client = _make_client()
    captured = _install_trades_handler(
        client,
        {"trade-1": [[_trade_payload(status="TRADE_STATUS_CONFIRMED", transaction_hash=TX_HASH)]]},
    )

    hashes = client.wait_for_order_fill_settlement(
        _accepted_order(trade_ids=("trade-1",), transactions_hashes=(OTHER_TX_HASH,))
    )

    assert hashes == (TX_HASH,)
    assert len(captured) == 1


def test_polls_until_every_fill_confirms() -> None:
    client = _make_client()
    captured = _install_trades_handler(
        client,
        {
            "trade-1": [
                # A hash before confirmation is not terminal: it can still be
                # replaced if the transaction is retried.
                [_trade_payload(status="TRADE_STATUS_MINED", transaction_hash=OTHER_TX_HASH)],
                [_trade_payload(status="TRADE_STATUS_CONFIRMED", transaction_hash=TX_HASH)],
            ]
        },
    )

    hashes = client.wait_for_order_fill_settlement(_accepted_order(trade_ids=("trade-1",)))

    assert hashes == (TX_HASH,)
    assert len(captured) == 2


def test_returns_settled_hashes_when_only_some_fills_fail() -> None:
    client = _make_client()
    _install_trades_handler(
        client,
        {
            "trade-1": [[_trade_payload(trade_id="trade-1", status="TRADE_STATUS_FAILED")]],
            "trade-2": [
                [
                    _trade_payload(
                        trade_id="trade-2",
                        status="TRADE_STATUS_CONFIRMED",
                        transaction_hash=OTHER_TX_HASH,
                    )
                ]
            ],
        },
    )

    hashes = client.wait_for_order_fill_settlement(
        _accepted_order(trade_ids=("trade-1", "trade-2"))
    )

    assert hashes == (OTHER_TX_HASH,)


def test_raises_transaction_failed_when_every_fill_fails() -> None:
    client = _make_client()
    _install_trades_handler(client, {"trade-1": [[_trade_payload(status="TRADE_STATUS_FAILED")]]})

    with pytest.raises(TransactionFailedError):
        client.wait_for_order_fill_settlement(_accepted_order(trade_ids=("trade-1",)))


def test_raises_timeout_when_fills_are_still_settling() -> None:
    client = _make_client()
    _install_trades_handler(client, {"trade-1": [[_trade_payload()]]})

    with pytest.raises(TimeoutError):
        client.wait_for_order_fill_settlement(
            _accepted_order(trade_ids=("trade-1",)), timeout_s=0.01
        )
