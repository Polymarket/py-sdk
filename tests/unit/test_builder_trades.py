# pyright: reportPrivateUsage=false
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncPublicClient, AsyncSecureClient, PublicClient
from polymarket._internal.actions._cursor import END_CURSOR
from polymarket._internal.actions.builders import (
    build_list_builder_trades_request,
    parse_builder_trades_page,
)
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.environments import PRODUCTION
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.clob.builder import BuilderTrade

_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_SIGNER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
_FAKE_CREDS = ApiKeyCreds(key="k", passphrase="p", secret="dGVzdA==")
_VALID_BUILDER_CODE = "0x" + "ab" * 32

_WIRE_TRADE: dict[str, Any] = {
    "id": "trade-1",
    "tradeType": "TRADE",
    "takerOrderHash": "0x" + "aa" * 32,
    "builder": "0xbuilder",
    "market": "0xmarket",
    "assetId": "1234567890",
    "side": "BUY",
    "size": "1.5",
    "sizeUsdc": "0.75",
    "price": "0.5",
    "status": "MINED",
    "outcome": "Yes",
    "outcomeIndex": 0,
    "owner": "0xowner",
    "maker": "0xmaker",
    "transactionHash": "0x" + "bb" * 32,
    "matchTime": 1700000000000,
    "bucketIndex": 7,
    "fee": "0.01",
    "feeUsdc": "0.005",
}


class TestBuilderTradeModel:
    def test_parses_required_fields_with_alias_mapping(self) -> None:
        trade = BuilderTrade.parse_response(_WIRE_TRADE)
        assert trade.id == "trade-1"
        assert trade.trade_type == "TRADE"
        assert trade.taker_order_hash == "0x" + "aa" * 32
        assert trade.builder == "0xbuilder"
        assert trade.market == "0xmarket"
        assert trade.token_id == "1234567890"
        assert trade.side == "BUY"
        assert trade.size == Decimal("1.5")
        assert trade.size_usdc == Decimal("0.75")
        assert trade.price == Decimal("0.5")
        assert trade.outcome_index == 0
        assert trade.transaction_hash == "0x" + "bb" * 32
        assert trade.bucket_index == 7
        assert trade.fee == Decimal("0.01")
        assert trade.fee_usdc == Decimal("0.005")

    def test_parses_match_time_from_epoch_ms_int(self) -> None:
        trade = BuilderTrade.parse_response(_WIRE_TRADE)
        assert trade.matched_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)

    def test_parses_match_time_from_epoch_ms_digit_string(self) -> None:
        trade = BuilderTrade.parse_response({**_WIRE_TRADE, "matchTime": "1700000000000"})
        assert trade.matched_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)

    def test_optional_timestamps_default_to_none(self) -> None:
        trade = BuilderTrade.parse_response(_WIRE_TRADE)
        assert trade.created_at is None
        assert trade.updated_at is None

    def test_optional_timestamps_parsed_when_present(self) -> None:
        trade = BuilderTrade.parse_response(
            {**_WIRE_TRADE, "createdAt": 1700000000000, "updatedAt": 1700000005000}
        )
        assert trade.created_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        assert trade.updated_at == datetime(2023, 11, 14, 22, 13, 25, tzinfo=UTC)

    def test_error_msg_defaults_to_none(self) -> None:
        trade = BuilderTrade.parse_response(_WIRE_TRADE)
        assert trade.error_msg is None

    def test_error_msg_alias_maps_from_err_msg(self) -> None:
        trade = BuilderTrade.parse_response({**_WIRE_TRADE, "err_msg": "boom"})
        assert trade.error_msg == "boom"

    def test_rejects_non_string_size(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            BuilderTrade.parse_response({**_WIRE_TRADE, "size": 1.5})

    def test_rejects_invalid_match_time(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            BuilderTrade.parse_response({**_WIRE_TRADE, "matchTime": "not-an-epoch"})

    def test_rejects_bool_match_time(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            BuilderTrade.parse_response({**_WIRE_TRADE, "matchTime": True})

    def test_parses_match_time_from_epoch_seconds_digit_string(self) -> None:
        trade = BuilderTrade.parse_response({**_WIRE_TRADE, "matchTime": "1777040544"})
        assert trade.matched_at == datetime(2026, 4, 24, 14, 22, 24, tzinfo=UTC)

    def test_parses_match_time_from_epoch_seconds_int(self) -> None:
        trade = BuilderTrade.parse_response({**_WIRE_TRADE, "matchTime": 1777040544})
        assert trade.matched_at == datetime(2026, 4, 24, 14, 22, 24, tzinfo=UTC)

    def test_parses_created_and_updated_at_from_iso_strings(self) -> None:
        trade = BuilderTrade.parse_response(
            {
                **_WIRE_TRADE,
                "createdAt": "2026-04-24T14:22:24.198666Z",
                "updatedAt": "2026-04-24T14:23:38.514014Z",
            }
        )
        assert trade.created_at == datetime(2026, 4, 24, 14, 22, 24, 198666, tzinfo=UTC)
        assert trade.updated_at == datetime(2026, 4, 24, 14, 23, 38, 514014, tzinfo=UTC)

    def test_parses_mixed_wire_shape_as_returned_by_live_endpoint(self) -> None:
        trade = BuilderTrade.parse_response(
            {
                **_WIRE_TRADE,
                "matchTime": "1777040544",
                "createdAt": "2026-04-24T14:22:24.198666Z",
                "updatedAt": "2026-04-24T14:23:38.514014Z",
            }
        )
        assert trade.matched_at == datetime(2026, 4, 24, 14, 22, 24, tzinfo=UTC)
        assert trade.created_at == datetime(2026, 4, 24, 14, 22, 24, 198666, tzinfo=UTC)


class TestBuildListBuilderTradesRequest:
    def test_returns_endpoint_path(self) -> None:
        path, _ = build_list_builder_trades_request(builder_code=_VALID_BUILDER_CODE)
        assert path == "/builder/trades"

    def test_builder_code_lands_in_params(self) -> None:
        _, params = build_list_builder_trades_request(builder_code=_VALID_BUILDER_CODE)
        assert params["builder_code"] == _VALID_BUILDER_CODE

    def test_builder_code_required_when_invalid(self) -> None:
        with pytest.raises(UserInputError, match="builder_code"):
            build_list_builder_trades_request(builder_code="not-a-builder-code")

    def test_builder_code_rejects_non_string(self) -> None:
        with pytest.raises(UserInputError, match="builder_code"):
            build_list_builder_trades_request(builder_code=42)  # type: ignore[arg-type]

    def test_token_id_renamed_to_asset_id_on_wire(self) -> None:
        _, params = build_list_builder_trades_request(
            builder_code=_VALID_BUILDER_CODE, token_id="9876"
        )
        assert params["asset_id"] == "9876"
        assert "token_id" not in params

    def test_optional_filters_land_in_params(self) -> None:
        _, params = build_list_builder_trades_request(
            builder_code=_VALID_BUILDER_CODE,
            market="0xmarket",
            id="trade-1",
            after="2026-01-01",
            before="2026-12-31",
        )
        assert params["market"] == "0xmarket"
        assert params["id"] == "trade-1"
        assert params["after"] == "2026-01-01"
        assert params["before"] == "2026-12-31"

    def test_unset_filters_are_omitted(self) -> None:
        _, params = build_list_builder_trades_request(builder_code=_VALID_BUILDER_CODE)
        assert set(params.keys()) == {"builder_code"}

    def test_cursor_becomes_next_cursor_query_param(self) -> None:
        _, params = build_list_builder_trades_request(
            builder_code=_VALID_BUILDER_CODE, cursor="abc123"
        )
        assert params["next_cursor"] == "abc123"

    def test_empty_cursor_rejected(self) -> None:
        with pytest.raises(UserInputError):
            build_list_builder_trades_request(builder_code=_VALID_BUILDER_CODE, cursor="")

    def test_empty_market_rejected(self) -> None:
        with pytest.raises(UserInputError):
            build_list_builder_trades_request(builder_code=_VALID_BUILDER_CODE, market="")


class TestParseBuilderTradesPage:
    def test_parses_data_array_and_cursor(self) -> None:
        page = parse_builder_trades_page(
            {"data": [_WIRE_TRADE], "next_cursor": "cursor-2", "count": 1, "limit": 50}
        )
        assert len(page.items) == 1
        assert page.items[0].id == "trade-1"
        assert page.next_cursor == "cursor-2"
        assert page.has_more is True
        assert page.total_count == 1

    def test_end_cursor_signals_no_more(self) -> None:
        page = parse_builder_trades_page(
            {"data": [], "next_cursor": END_CURSOR, "count": 0, "limit": 50}
        )
        assert page.items == ()
        assert page.next_cursor is None
        assert page.has_more is False

    def test_malformed_payload_raises(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            parse_builder_trades_page("not a dict")

    def test_malformed_items_raises(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            parse_builder_trades_page(
                {"data": [{"missing": "required"}], "next_cursor": END_CURSOR, "count": 0}
            )

    def test_missing_next_cursor_raises(self) -> None:
        with pytest.raises(UnexpectedResponseError, match="missing next_cursor"):
            parse_builder_trades_page({"data": [_WIRE_TRADE], "count": 1})

    def test_null_next_cursor_raises(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            parse_builder_trades_page({"data": [], "next_cursor": None, "count": 0})

    def test_non_string_next_cursor_raises(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            parse_builder_trades_page({"data": [], "next_cursor": 42, "count": 0})


def _capture(captured: list[httpx.Request], payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


class TestPublicClientListBuilderTrades:
    def test_first_page_hits_builder_trades_endpoint_with_filters(self) -> None:
        captured: list[httpx.Request] = []
        with PublicClient() as client:
            handler = _capture(
                captured,
                {"data": [_WIRE_TRADE], "next_cursor": END_CURSOR, "count": 1, "limit": 50},
            )
            client._ctx = type(client._ctx)(
                environment=client._ctx.environment,
                gamma=client._ctx.gamma,
                data=client._ctx.data,
                clob=SyncTransport(
                    base_url=PRODUCTION.clob_url,
                    client=httpx.Client(base_url=PRODUCTION.clob_url, transport=handler),
                ),
                rfq=client._ctx.rfq,
            )

            page = client.list_builder_trades(
                builder_code=_VALID_BUILDER_CODE, market="0xmarket", token_id="42"
            ).first_page()

        assert len(captured) == 1
        request = captured[0]
        assert request.method == "GET"
        url = urlparse(str(request.url))
        assert url.path == "/builder/trades"
        qs = parse_qs(url.query)
        assert qs["builder_code"] == [_VALID_BUILDER_CODE]
        assert qs["market"] == ["0xmarket"]
        assert qs["asset_id"] == ["42"]
        assert "token_id" not in qs
        assert page.items[0].id == "trade-1"
        assert page.has_more is False


class TestAsyncPublicClientListBuilderTrades:
    def test_iterates_pages_until_end_cursor(self) -> None:
        captured: list[httpx.Request] = []
        pages = iter(
            [
                {"data": [_WIRE_TRADE], "next_cursor": "page-2", "count": 2, "limit": 1},
                {
                    "data": [{**_WIRE_TRADE, "id": "trade-2"}],
                    "next_cursor": END_CURSOR,
                    "count": 2,
                    "limit": 1,
                },
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json=next(pages), request=request)

        async def run() -> list[str]:
            async with AsyncPublicClient() as client:
                client._ctx = type(client._ctx)(
                    environment=client._ctx.environment,
                    gamma=client._ctx.gamma,
                    data=client._ctx.data,
                    clob=AsyncTransport(
                        base_url=PRODUCTION.clob_url,
                        client=httpx.AsyncClient(
                            base_url=PRODUCTION.clob_url, transport=httpx.MockTransport(handler)
                        ),
                    ),
                    rfq=client._ctx.rfq,
                )
                ids: list[str] = []
                async for trade in client.list_builder_trades(
                    builder_code=_VALID_BUILDER_CODE
                ).iter_items():
                    ids.append(trade.id)
                return ids

        ids = asyncio.run(run())
        assert ids == ["trade-1", "trade-2"]
        assert len(captured) == 2
        first_qs = parse_qs(urlparse(str(captured[0].url)).query)
        assert "next_cursor" not in first_qs
        second_qs = parse_qs(urlparse(str(captured[1].url)).query)
        assert second_qs["next_cursor"] == ["page-2"]


class TestAsyncSecureClientListBuilderTrades:
    def test_method_is_available_and_hits_clob_transport(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={"data": [_WIRE_TRADE], "next_cursor": END_CURSOR, "count": 1, "limit": 50},
                request=request,
            )

        async def run() -> BuilderTrade:
            client = await AsyncSecureClient._create(
                private_key=_PRIVATE_KEY,
                wallet=_SIGNER,
                credentials=_FAKE_CREDS,
                validate_credentials=False,
            )
            try:
                import dataclasses

                client._ctx = dataclasses.replace(
                    client._ctx,
                    clob=AsyncTransport(
                        base_url=PRODUCTION.clob_url,
                        client=httpx.AsyncClient(
                            base_url=PRODUCTION.clob_url, transport=httpx.MockTransport(handler)
                        ),
                    ),
                )
                page = await client.list_builder_trades(
                    builder_code=_VALID_BUILDER_CODE
                ).first_page()
                return page.items[0]
            finally:
                await client.close()

        trade = asyncio.run(run())
        assert trade.id == "trade-1"
        # The builder trades endpoint is public — no L2 auth headers needed.
        assert "POLY_SIGNATURE" not in captured[0].headers
