"""Tests for ``_repr_html_`` on SDK models, containers, and auth types."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from decimal import Decimal
from typing import Any

from polymarket._jupyter import card, safe_html_repr, truncate_mid
from polymarket.auth import BuilderApiKey, RelayerApiKey
from polymarket.models import OrderBook
from polymarket.models.clob.account import ClobTrade, OpenOrder
from polymarket.models.clob.api_key import ApiKeyCreds
from polymarket.models.clob.order_response import AcceptedOrder, RejectedOrder
from polymarket.models.clob.price_history import PriceHistoryPoint
from polymarket.models.data.activity import TradeActivity, UnknownActivity
from polymarket.models.data.portfolio import Position
from polymarket.models.gamma import Event, Market
from polymarket.pagination import AsyncPaginator, Page, Paginator

_CONDITION_ID = "0x" + "11" * 32


def _make_market(**overrides: object) -> Market:
    payload: dict[str, object] = {
        "id": "MARKET-1",
        "question": "Will X happen?",
        "slug": "will-x-happen",
        "conditionId": _CONDITION_ID,
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.6", "0.4"],
        "clobTokenIds": ["TOKEN-YES", "TOKEN-NO"],
        "active": True,
        "closed": False,
        "endDate": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return Market.parse_response(payload)


def _make_event(**overrides: object) -> Event:
    payload: dict[str, object] = {
        "id": "EVENT-1",
        "title": "Some Event",
        "slug": "some-event",
        "active": True,
        "endDate": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return Event.parse_response(payload)


def _make_book(**overrides: object) -> OrderBook:
    payload: dict[str, object] = {
        "market": "0xfooBar123456789",
        "asset_id": "8501497",
        "timestamp": "1700000000000",
        "bids": [{"price": "0.48", "size": "50"}, {"price": "0.49", "size": "100"}],
        "asks": [{"price": "0.52", "size": "70"}, {"price": "0.51", "size": "80"}],
        "min_order_size": "5",
        "tick_size": "0.01",
        "neg_risk": True,
        "last_trade_price": "0.50",
        "hash": "abc",
    }
    payload.update(overrides)
    return OrderBook.model_validate(payload)


def _make_position(**overrides: object) -> Position:
    payload: dict[str, object] = {
        "conditionId": _CONDITION_ID,
        "proxyWallet": "0x" + "ab" * 20,
        "asset": "TOKEN-YES",
        "size": "100",
        "avgPrice": "0.55",
        "curPrice": "0.60",
        "cashPnl": "5.00",
        "outcome": "Yes",
        "title": "Will X happen?",
    }
    payload.update(overrides)
    return Position.model_validate(payload)


_OPEN_ORDER_PAYLOAD: dict[str, Any] = {
    "asset_id": "8501497",
    "associate_trades": ["trade-1"],
    "created_at": 1700000000000,
    "expiration": 1800000000,
    "id": "order-abcdef0123456789",
    "maker_address": "0xMAKER",
    "market": "0xMARKET01234567890",
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
    "id": "trade-abcdef0123456789",
    "last_update": 1700000010000,
    "maker_address": "0xMAKER",
    "maker_orders": [],
    "market": "0xMARKET01234567890",
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


def test_card_renders_title_and_rows() -> None:
    html = card("Some Title", rows=[("k", "v")])
    assert "Some Title" in html
    assert "k" in html and "v" in html
    assert html.startswith("<div")
    assert html.endswith("</div>")


def test_card_escapes_title_and_values() -> None:
    html = card("Hi <script>alert(1)</script>", rows=[("k", "<b>v</b>")])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>v</b>" not in html
    assert "&lt;b&gt;v&lt;/b&gt;" in html


def test_card_with_no_rows_omits_table() -> None:
    html = card("Just a title")
    assert "<table" not in html


def test_card_with_hint() -> None:
    html = card("T", rows=[("k", "v")], hint="hint text")
    assert "hint text" in html


def test_truncate_mid_short_string_passthrough() -> None:
    assert truncate_mid("short") == "short"


def test_truncate_mid_long_string_truncates() -> None:
    out = truncate_mid("0xabcdef1234567890fedcba")
    assert "…" in out
    assert out.startswith("0xabcd")
    assert out.endswith("dcba")


def test_truncate_mid_none() -> None:
    assert truncate_mid(None) == "—"


def test_safe_html_repr_falls_back_on_exception() -> None:
    class _Boom:
        def __repr__(self) -> str:
            return "<Boom>"

        @safe_html_repr
        def _repr_html_(self) -> str:
            raise RuntimeError("boom")

    out = _Boom()._repr_html_()
    assert "&lt;Boom&gt;" in out


def test_market_repr_html_contains_key_fields() -> None:
    m = _make_market()
    html = m._repr_html_()
    assert "Will X happen?" in html
    assert "will-x-happen" in html
    assert "open" in html
    assert "2026-12-31" in html
    assert "0.6" in html and "0.4" in html


def test_market_repr_html_status_closed() -> None:
    m = _make_market(active=False, closed=True)
    assert "closed" in m._repr_html_()


def test_market_repr_html_escapes_question() -> None:
    m = _make_market(question="Hi <script>alert(1)</script>?")
    html = m._repr_html_()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_event_repr_html_contains_key_fields() -> None:
    e = _make_event()
    html = e._repr_html_()
    assert "Some Event" in html
    assert "some-event" in html
    assert "open" in html


def test_orderbook_repr_html_contains_best_bid_ask_and_spread() -> None:
    book = _make_book()
    html = book._repr_html_()
    assert "OrderBook" in html
    assert "0.49" in html
    assert "0.51" in html
    assert "spread" in html
    assert "2 bids / 2 asks" in html


def test_orderbook_repr_html_handles_empty_sides() -> None:
    book = _make_book(bids=[], asks=[])
    html = book._repr_html_()
    assert "—" in html
    assert "0 bids / 0 asks" in html


def test_position_repr_html_contains_market_and_pnl() -> None:
    p = _make_position()
    html = p._repr_html_()
    assert "Will X happen?" in html
    assert "Yes" in html
    assert "100" in html
    assert "5.00" in html


def test_open_order_repr_html_contains_id_and_side() -> None:
    order = OpenOrder.model_validate(_OPEN_ORDER_PAYLOAD)
    html = order._repr_html_()
    assert "OpenOrder" in html
    assert "BUY" in html
    assert "LIVE" in html
    assert "0.5" in html


def test_clob_trade_repr_html_contains_price_and_side() -> None:
    trade = ClobTrade.model_validate(_CLOB_TRADE_PAYLOAD)
    html = trade._repr_html_()
    assert "Trade" in html
    assert "BUY" in html
    assert "0.5" in html
    assert "5" in html


def test_price_history_point_repr_html_formats_timestamp() -> None:
    pt = PriceHistoryPoint(t=1700000000, p=0.62)
    html = pt._repr_html_()
    assert "PriceHistoryPoint" in html
    assert "0.62" in html
    assert "2023-11-14" in html


def test_accepted_order_repr_html() -> None:
    o = AcceptedOrder(
        order_id="order-abc123def456",
        status="live",
        making_amount=Decimal("100"),
        taking_amount=Decimal("200"),
        trade_ids=("t1", "t2"),
        transactions_hashes=(),
    )
    html = o._repr_html_()
    assert "OrderResponse" in html
    assert "accepted" in html
    assert "live" in html
    assert "2" in html


def test_rejected_order_repr_html() -> None:
    r = RejectedOrder(code="not_enough_balance", message="insufficient pUSD balance")
    html = r._repr_html_()
    assert "rejected" in html
    assert "not_enough_balance" in html
    assert "insufficient pUSD balance" in html


def test_trade_activity_repr_html_uses_variant_class_name() -> None:
    activity = TradeActivity.model_validate(
        {
            "type": "TRADE",
            "proxyWallet": "0x" + "ab" * 20,
            "timestamp": 1700000000,
            "transactionHash": "0xTX1234567890",
            "conditionId": _CONDITION_ID,
            "asset": "TOKEN-1",
            "side": "BUY",
            "size": "5",
            "amount": "2.5",
            "price": "0.5",
            "outcome": "Yes",
            "outcomeIndex": 0,
            "title": "Some Market",
            "slug": "some-market",
            "icon": "i.png",
            "eventSlug": "evt",
        }
    )
    html = activity._repr_html_()
    assert "TradeActivity" in html
    assert "Some Market" in html
    assert "BUY" in html
    assert "Yes" in html


def test_unknown_activity_repr_html_shows_type_tag() -> None:
    unknown = UnknownActivity.model_validate(
        {
            "type": "WEIRD_NEW_TYPE",
            "proxyWallet": "0x" + "ab" * 20,
            "timestamp": 1700000000,
            "transactionHash": "0xTX",
            "raw": {"a": 1, "b": 2, "c": 3},
        }
    )
    html = unknown._repr_html_()
    assert "UnknownActivity" in html
    assert "WEIRD_NEW_TYPE" in html
    assert "3" in html


def test_paginator_repr_replaces_default_object_repr() -> None:
    p = Paginator[int](fetch=lambda _c: Page(items=(), has_more=False))
    text = repr(p)
    assert "object at" not in text
    assert "Paginator" in text
    assert "unfetched" in text


def test_paginator_repr_html_no_fetch() -> None:
    fetched: list[str | None] = []

    def fetch(cursor: str | None) -> Page[int]:
        fetched.append(cursor)
        return Page(items=(), has_more=False)

    p = Paginator[int](fetch=fetch)
    _ = repr(p)
    html = p._repr_html_()
    assert "Paginator" in html
    assert fetched == []


def test_async_paginator_repr_no_fetch() -> None:
    fetched: list[str | None] = []

    async def fetch(cursor: str | None) -> Page[int]:
        fetched.append(cursor)
        return Page(items=(), has_more=False)

    p = AsyncPaginator[int](fetch=fetch)
    text = repr(p)
    html = p._repr_html_()
    assert "AsyncPaginator" in text
    assert "AsyncPaginator" in html
    assert fetched == []


def test_page_repr_html_shows_count_and_has_more() -> None:
    page: Page[int] = Page(items=(1, 2, 3), has_more=True, next_cursor="abc123def456")
    html = page._repr_html_()
    assert "Page" in html
    assert "3" in html
    assert "True" in html
    assert "next_cursor" in html


def test_page_repr_html_with_total_count() -> None:
    page: Page[int] = Page(items=(1,), has_more=False, total_count=42)
    html = page._repr_html_()
    assert "42" in html


def test_api_key_creds_repr_redacts_key() -> None:
    """Regression: api key was exposed via pydantic's default __repr__."""
    creds = ApiKeyCreds.model_validate(
        {"apiKey": "real-api-key", "passphrase": "real-pass", "secret": "real-secret"}
    )
    text = repr(creds)
    assert "real-api-key" not in text
    assert "real-pass" not in text
    assert "real-secret" not in text
    assert "redacted" in text


def test_api_key_creds_repr_html_redacts_all_fields() -> None:
    creds = ApiKeyCreds.model_validate(
        {"apiKey": "real-api-key", "passphrase": "real-pass", "secret": "real-secret"}
    )
    html = creds._repr_html_()
    assert "real-api-key" not in html
    assert "real-pass" not in html
    assert "real-secret" not in html
    assert "***" in html


def test_builder_api_key_repr_html_redacts() -> None:
    key = BuilderApiKey(key="real-key", secret="real-secret", passphrase="real-pass")
    html = key._repr_html_()
    assert "real-key" not in html
    assert "real-secret" not in html
    assert "real-pass" not in html
    assert "***" in html


def test_builder_api_key_repr_redacts() -> None:
    key = BuilderApiKey(key="real-key", secret="real-secret", passphrase="real-pass")
    text = repr(key)
    assert "real-key" not in text
    assert "real-secret" not in text
    assert "real-pass" not in text


def test_relayer_api_key_repr_html_redacts_key_but_shows_address() -> None:
    key = RelayerApiKey(key="real-relayer-key", address="0x" + "ab" * 20)
    html = key._repr_html_()
    assert "real-relayer-key" not in html
    assert "***" in html
    assert "0x" in html


def test_relayer_api_key_repr_redacts() -> None:
    key = RelayerApiKey(key="real-relayer-key", address="0x" + "ab" * 20)
    assert "real-relayer-key" not in repr(key)


def test_repr_html_methods_render_pure_html_strings() -> None:
    rendered: list[str] = [
        _make_market()._repr_html_(),
        _make_event()._repr_html_(),
        _make_book()._repr_html_(),
        _make_position()._repr_html_(),
        OpenOrder.model_validate(_OPEN_ORDER_PAYLOAD)._repr_html_(),
        ClobTrade.model_validate(_CLOB_TRADE_PAYLOAD)._repr_html_(),
        PriceHistoryPoint(t=1, p=0.5)._repr_html_(),
    ]
    assert all(isinstance(s, str) and s for s in rendered)


def test_async_paginator_repr_runs_without_event_loop() -> None:
    async def fetch(_c: str | None) -> Page[int]:
        return Page(items=(), has_more=False)

    p = AsyncPaginator[int](fetch=fetch)
    assert "AsyncPaginator" in repr(p)
    assert "AsyncPaginator" in p._repr_html_()
