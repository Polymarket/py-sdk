from decimal import Decimal
from typing import get_type_hints

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.clob.order_book import OrderBookLevel
from polymarket.models.rtds_events import CryptoPricesChainlinkTwapPayload, PriceUpdatePayload


class TestStrictStringFieldsExposeBareDecimal:
    def test_model_fields_annotation_is_bare_decimal(self) -> None:
        assert OrderBookLevel.model_fields["price"].annotation is Decimal
        assert OrderBookLevel.model_fields["size"].annotation is Decimal

    def test_get_type_hints_resolves_to_bare_decimal(self) -> None:
        hints = get_type_hints(OrderBookLevel)
        assert hints["price"] is Decimal
        assert hints["size"] is Decimal


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


class TestNumberOrStringValidatorAcceptsBroaderInput:
    def test_string_input_parses_to_decimal(self) -> None:
        payload = PriceUpdatePayload.parse_response(
            {"symbol": "BTC", "timestamp": 0, "value": "1.5"}
        )
        assert isinstance(payload.value, Decimal)
        assert payload.value == Decimal("1.5")

    def test_int_input_parses_to_decimal(self) -> None:
        payload = PriceUpdatePayload.parse_response({"symbol": "BTC", "timestamp": 0, "value": 1})
        assert payload.value == Decimal("1")

    def test_float_input_parses_to_decimal(self) -> None:
        payload = PriceUpdatePayload.parse_response({"symbol": "BTC", "timestamp": 0, "value": 1.5})
        assert payload.value == Decimal("1.5")

    def test_direct_decimal_input_is_accepted(self) -> None:
        payload = PriceUpdatePayload.parse_response(
            {"symbol": "BTC", "timestamp": 0, "value": Decimal("1.5")}
        )
        assert payload.value == Decimal("1.5")

    def test_bool_input_is_rejected(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            PriceUpdatePayload.parse_response({"symbol": "BTC", "timestamp": 0, "value": True})


class TestTwapPayloadExposesBareDecimal:
    def test_model_field_annotation_is_bare_decimal(self) -> None:
        assert CryptoPricesChainlinkTwapPayload.model_fields["value"].annotation is Decimal

    def test_get_type_hints_resolves_to_bare_decimal(self) -> None:
        hints = get_type_hints(CryptoPricesChainlinkTwapPayload)
        assert hints["value"] is Decimal


class TestNoDecimalStringAliasLeaksToPublicSurface:
    def test_validators_module_does_not_export_old_names(self) -> None:
        from polymarket.models.clob import _validators

        assert "DecimalString" not in _validators.__all__
        assert "DecimalishString" not in _validators.__all__

    def test_validators_module_does_not_define_old_names(self) -> None:
        from polymarket.models.clob import _validators

        assert not hasattr(_validators, "DecimalString")
        assert not hasattr(_validators, "DecimalishString")
