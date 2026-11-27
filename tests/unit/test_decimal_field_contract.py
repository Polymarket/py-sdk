import inspect
from datetime import datetime
from decimal import Decimal
from typing import get_type_hints

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.clob.last_trade import LastTradePrice, LastTradePriceForToken
from polymarket.models.clob.order_book import OrderBook, OrderBookLevel


class TestStrictStringFieldsExposeBareDecimal:
    def test_model_fields_annotation_is_bare_decimal(self) -> None:
        assert OrderBookLevel.model_fields["price"].annotation is Decimal
        assert OrderBookLevel.model_fields["size"].annotation is Decimal

    def test_get_type_hints_resolves_to_bare_decimal(self) -> None:
        hints = get_type_hints(OrderBookLevel, include_extras=True)
        assert hints["price"] is Decimal
        assert hints["size"] is Decimal

    @pytest.mark.parametrize(
        ("model", "field", "annotation"),
        [
            (OrderBookLevel, "price", Decimal),
            (OrderBookLevel, "size", Decimal),
            (OrderBook, "min_order_size", Decimal),
            (OrderBook, "tick_size", Decimal),
            (OrderBook, "last_trade_price", Decimal | None),
            (OrderBook, "timestamp", datetime | None),
            (LastTradePrice, "price", Decimal),
            (LastTradePriceForToken, "price", Decimal),
        ],
    )
    def test_market_read_annotations_are_canonical(
        self, model: type[object], field: str, annotation: object
    ) -> None:
        assert get_type_hints(model, include_extras=True)[field] == annotation
        assert inspect.signature(model).parameters[field].annotation == annotation


class TestStrictStringValidatorAcceptsAndRejects:
    def test_string_input_parses_to_decimal(self) -> None:
        level = OrderBookLevel.parse_response({"price": "0.5", "size": "10"})
        assert isinstance(level.price, Decimal)
        assert level.price == Decimal("0.5")
        assert isinstance(level.size, Decimal)
        assert level.size == Decimal("10")

    def test_direct_decimal_input_is_accepted(self) -> None:
        level = OrderBookLevel.parse_response({"price": Decimal("0.5"), "size": Decimal("10")})
        assert level.price == Decimal("0.5")
        assert level.size == Decimal("10")

    def test_float_input_is_rejected(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            OrderBookLevel.parse_response({"price": 0.5, "size": "10"})

    def test_int_input_is_rejected(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            OrderBookLevel.parse_response({"price": 1, "size": "10"})

    def test_bool_input_is_rejected(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            OrderBookLevel.parse_response({"price": True, "size": "10"})


class TestNoDecimalStringAliasLeaksToPublicSurface:
    def test_validators_module_does_not_export_old_names(self) -> None:
        from polymarket.models.clob import _validators

        assert "DecimalString" not in _validators.__all__
        assert "DecimalishString" not in _validators.__all__

    def test_validators_module_does_not_define_old_names(self) -> None:
        from polymarket.models.clob import _validators

        assert not hasattr(_validators, "DecimalString")
        assert not hasattr(_validators, "DecimalishString")
