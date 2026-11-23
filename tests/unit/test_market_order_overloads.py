# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from typing import Any, cast, get_overloads, get_type_hints

import pytest
from _bearer import bearer_credentials_for

from polymarket import AsyncSecureClient
from polymarket.errors import UserInputError
from polymarket.models.types import OrderSide

_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_SIGNER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


def _make_client() -> AsyncSecureClient:
    return asyncio.run(
        AsyncSecureClient._create(
            private_key=_PRIVATE_KEY,
            wallet=_SIGNER,
            credentials=bearer_credentials_for(_PRIVATE_KEY),
            validate_credentials=False,
        )
    )


class TestOverloadStructure:
    def test_create_market_order_has_two_overloads(self) -> None:
        overloads = get_overloads(AsyncSecureClient.create_market_order)
        assert len(overloads) == 2

    def test_place_market_order_has_two_overloads(self) -> None:
        overloads = get_overloads(AsyncSecureClient.place_market_order)
        assert len(overloads) == 2

    def test_create_market_order_buy_overload_accepts_amount_rejects_shares(self) -> None:
        buy_overload = next(
            o
            for o in get_overloads(AsyncSecureClient.create_market_order)
            if "BUY" in repr(inspect.signature(o).parameters["side"].annotation)
        )
        params = inspect.signature(buy_overload).parameters
        assert "amount" in params
        assert "max_spend" in params
        assert "max_price" in params
        assert "shares" not in params
        assert "min_price" not in params

    def test_create_market_order_sell_overload_accepts_shares_rejects_amount(self) -> None:
        sell_overload = next(
            o
            for o in get_overloads(AsyncSecureClient.create_market_order)
            if "SELL" in repr(inspect.signature(o).parameters["side"].annotation)
        )
        params = inspect.signature(sell_overload).parameters
        assert "shares" in params
        assert "amount" not in params
        assert "max_spend" not in params
        assert "max_price" not in params
        assert "min_price" in params

    def test_place_market_order_buy_overload_accepts_amount_rejects_shares(self) -> None:
        buy_overload = next(
            o
            for o in get_overloads(AsyncSecureClient.place_market_order)
            if "BUY" in repr(inspect.signature(o).parameters["side"].annotation)
        )
        params = inspect.signature(buy_overload).parameters
        assert "amount" in params
        assert "max_spend" in params
        assert "max_price" in params
        assert "shares" not in params
        assert "min_price" not in params

    def test_place_market_order_sell_overload_accepts_shares_rejects_amount(self) -> None:
        sell_overload = next(
            o
            for o in get_overloads(AsyncSecureClient.place_market_order)
            if "SELL" in repr(inspect.signature(o).parameters["side"].annotation)
        )
        params = inspect.signature(sell_overload).parameters
        assert "shares" in params
        assert "amount" not in params
        assert "max_spend" not in params
        assert "max_price" not in params
        assert "min_price" in params

    def test_buy_overload_amount_is_required(self) -> None:
        for method in (AsyncSecureClient.create_market_order, AsyncSecureClient.place_market_order):
            buy_overload = next(
                o
                for o in get_overloads(method)
                if "BUY" in repr(inspect.signature(o).parameters["side"].annotation)
            )
            amount_param = inspect.signature(buy_overload).parameters["amount"]
            assert amount_param.default is inspect.Parameter.empty, (
                f"{method.__name__} BUY overload: amount should be required"
            )

    def test_sell_overload_shares_is_required(self) -> None:
        for method in (AsyncSecureClient.create_market_order, AsyncSecureClient.place_market_order):
            sell_overload = next(
                o
                for o in get_overloads(method)
                if "SELL" in repr(inspect.signature(o).parameters["side"].annotation)
            )
            shares_param = inspect.signature(sell_overload).parameters["shares"]
            assert shares_param.default is inspect.Parameter.empty, (
                f"{method.__name__} SELL overload: shares should be required"
            )

    def test_buy_overload_side_literal_is_buy_only(self) -> None:
        for method in (AsyncSecureClient.create_market_order, AsyncSecureClient.place_market_order):
            hints = get_type_hints(get_overloads(method)[0])
            side_hint = hints["side"]
            args = getattr(side_hint, "__args__", ())
            assert args == ("BUY",), (
                f"{method.__name__} first overload side should be Literal['BUY']: got {args}"
            )

    def test_sell_overload_side_literal_is_sell_only(self) -> None:
        for method in (AsyncSecureClient.create_market_order, AsyncSecureClient.place_market_order):
            hints = get_type_hints(get_overloads(method)[1])
            side_hint = hints["side"]
            args = getattr(side_hint, "__args__", ())
            assert args == ("SELL",), (
                f"{method.__name__} second overload side should be Literal['SELL']: got {args}"
            )


class TestRuntimeValidationStillCatchesMisuse:
    def test_buy_without_amount_raises(self) -> None:
        client = _make_client()
        try:
            with pytest.raises(UserInputError, match="amount is required"):
                asyncio.run(
                    cast(Any, client.create_market_order)(token_id="1", side=cast(OrderSide, "BUY"))
                )
        finally:
            asyncio.run(client.close())

    def test_buy_with_shares_raises(self) -> None:
        client = _make_client()
        try:
            with pytest.raises(UserInputError, match="shares must not be set"):
                asyncio.run(
                    cast(Any, client.create_market_order)(
                        token_id="1", side="BUY", amount=Decimal(1), shares=Decimal(1)
                    )
                )
        finally:
            asyncio.run(client.close())

    def test_sell_without_shares_raises(self) -> None:
        client = _make_client()
        try:
            with pytest.raises(UserInputError, match="shares is required"):
                asyncio.run(
                    cast(Any, client.create_market_order)(
                        token_id="1", side=cast(OrderSide, "SELL")
                    )
                )
        finally:
            asyncio.run(client.close())

    def test_sell_with_amount_raises(self) -> None:
        client = _make_client()
        try:
            with pytest.raises(UserInputError, match="amount must not be set"):
                asyncio.run(
                    cast(Any, client.create_market_order)(
                        token_id="1", side="SELL", shares=Decimal(1), amount=Decimal(1)
                    )
                )
        finally:
            asyncio.run(client.close())

    def test_sell_with_max_spend_raises(self) -> None:
        client = _make_client()
        try:
            with pytest.raises(UserInputError, match="max_spend is only valid for BUY"):
                asyncio.run(
                    cast(Any, client.create_market_order)(
                        token_id="1",
                        side="SELL",
                        shares=Decimal(1),
                        max_spend=Decimal(1),
                    )
                )
        finally:
            asyncio.run(client.close())

    def test_buy_with_min_price_raises(self) -> None:
        client = _make_client()
        try:
            with pytest.raises(UserInputError, match="min_price is only valid for SELL"):
                asyncio.run(
                    cast(Any, client.create_market_order)(
                        token_id="1",
                        side="BUY",
                        amount=Decimal(1),
                        min_price=Decimal("0.50"),
                    )
                )
        finally:
            asyncio.run(client.close())

    def test_sell_with_max_price_raises(self) -> None:
        client = _make_client()
        try:
            with pytest.raises(UserInputError, match="max_price is only valid for BUY"):
                asyncio.run(
                    cast(Any, client.create_market_order)(
                        token_id="1",
                        side="SELL",
                        shares=Decimal(1),
                        max_price=Decimal("0.50"),
                    )
                )
        finally:
            asyncio.run(client.close())

    def test_invalid_side_raises(self) -> None:
        client = _make_client()
        try:
            with pytest.raises(UserInputError, match="side must be 'BUY' or 'SELL'"):
                asyncio.run(
                    cast(Any, client.create_market_order)(
                        token_id="1", side="WRONG", amount=Decimal(1)
                    )
                )
        finally:
            asyncio.run(client.close())


class TestPyrightStaticContract:
    @staticmethod
    async def _example_buy(client: AsyncSecureClient) -> None:
        await client.create_market_order(token_id="1", side="BUY", amount=Decimal(2))
        await client.create_market_order(
            token_id="1", side="BUY", amount=Decimal(2), max_spend=Decimal(3)
        )
        await client.create_market_order(
            token_id="1", side="BUY", amount=Decimal(2), max_price=Decimal("0.55")
        )
        await client.place_market_order(token_id="1", side="BUY", amount=Decimal(2))
        await client.place_market_order(
            token_id="1", side="BUY", amount=Decimal(2), max_price=Decimal("0.55")
        )

    @staticmethod
    async def _example_sell(client: AsyncSecureClient) -> None:
        await client.create_market_order(token_id="1", side="SELL", shares=Decimal(5))
        await client.create_market_order(
            token_id="1", side="SELL", shares=Decimal(5), min_price=Decimal("0.45")
        )
        await client.place_market_order(token_id="1", side="SELL", shares=Decimal(5))
        await client.place_market_order(
            token_id="1", side="SELL", shares=Decimal(5), min_price=Decimal("0.45")
        )

    def test_typed_examples_are_callable(self) -> None:
        assert inspect.iscoroutinefunction(self._example_buy)
        assert inspect.iscoroutinefunction(self._example_sell)
