"""Perps public market model validation contracts."""

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from polymarket.models.perps.market import (
    PerpsBbo,
    PerpsBook,
    PerpsBookLevel,
    PerpsCandle,
    PerpsFeeScheduleEntry,
    PerpsFeeTier,
    PerpsFundingRate,
    PerpsInstrument,
    PerpsInstrumentSettlement,
    PerpsRiskTier,
    PerpsStatistic,
    PerpsTicker,
    PerpsTickerUpdate,
    PerpsTrade,
)

_EPOCH_MS = 1_751_500_000_000
_TIMESTAMP = datetime(2025, 7, 2, 23, 46, 40, tzinfo=UTC)


@pytest.mark.parametrize(
    ("model", "fields"),
    [
        (PerpsRiskTier, {"lower_bound": Decimal}),
        (
            PerpsInstrumentSettlement,
            {"sequence": int, "timestamp": datetime, "price": Decimal, "insurance_debit": Decimal},
        ),
        (
            PerpsInstrument,
            {
                "price_bounds": Decimal,
                "liquidation_fee": Decimal,
                "min_notional": Decimal,
                "max_market_notional": Decimal,
                "max_limit_notional": Decimal,
            },
        ),
        (
            PerpsTicker,
            {
                "index_price": Decimal,
                "mark_price": Decimal,
                "last_price": Decimal,
                "mid_price": Decimal,
                "open_interest": Decimal,
                "funding_rate": Decimal,
                "next_funding": datetime,
                "timestamp": datetime | None,
                "open_price": Decimal | None,
                "volume_24h": Decimal | None,
            },
        ),
        (
            PerpsTickerUpdate,
            {
                "index_price": Decimal,
                "mark_price": Decimal,
                "last_price": Decimal,
                "mid_price": Decimal,
                "open_interest": Decimal,
                "funding_rate": Decimal,
                "next_funding": datetime,
            },
        ),
        (
            PerpsCandle,
            {
                "timestamp": datetime,
                "open": Decimal,
                "high": Decimal,
                "low": Decimal,
                "close": Decimal,
                "volume": Decimal,
            },
        ),
        (PerpsStatistic, {"volume": Decimal, "open_price": Decimal}),
        (PerpsBookLevel, {"price": Decimal, "quantity": Decimal}),
        (PerpsBook, {"timestamp": datetime}),
        (
            PerpsBbo,
            {
                "bid_price": Decimal,
                "bid_quantity": Decimal,
                "ask_price": Decimal,
                "ask_quantity": Decimal,
                "timestamp": datetime | None,
            },
        ),
        (
            PerpsTrade,
            {
                "price": Decimal,
                "quantity": Decimal,
                "timestamp": datetime,
                "hash": str | None,
            },
        ),
        (PerpsFundingRate, {"funding_rate": Decimal, "timestamp": datetime}),
        (
            PerpsFeeTier,
            {
                "min_volume_30d": Decimal,
                "taker_fee_rate": Decimal,
                "maker_fee_rate": Decimal,
            },
        ),
        (
            PerpsFeeScheduleEntry,
            {"taker_fee_rate": Decimal, "maker_fee_rate": Decimal},
        ),
    ],
)
def test_public_annotations_are_canonical(model: type[object], fields: dict[str, object]) -> None:
    hints = get_type_hints(model, include_extras=True)
    for field, expected in fields.items():
        assert hints[field] == expected


def test_generated_signatures_use_canonical_types_and_compact_aliases() -> None:
    ticker_parameters = inspect.signature(PerpsTickerUpdate).parameters
    assert ticker_parameters["idx"].annotation is Decimal
    assert ticker_parameters["nxf"].annotation is datetime

    trade_parameters = inspect.signature(PerpsTrade).parameters
    assert trade_parameters["price"].annotation is Decimal
    assert trade_parameters["timestamp"].annotation is datetime
    assert trade_parameters["hash"].annotation == (str | None)


def test_compact_market_payload_preserves_decimal_and_timestamp_parsing() -> None:
    ticker = PerpsTickerUpdate.model_validate(
        {
            "iid": 4,
            "idx": 100,
            "mark": 100.1,
            "last": Decimal("100.2"),
            "mid": "100.15",
            "oi": "5000",
            "fr": "0.0001",
            "nxf": _EPOCH_MS,
        }
    )

    assert ticker.index_price == Decimal("100")
    assert ticker.mark_price == Decimal("100.1")
    assert ticker.last_price == Decimal("100.2")
    assert ticker.next_funding == _TIMESTAMP


@pytest.mark.parametrize("value", [True, False])
def test_decimal_fields_reject_bool(value: bool) -> None:
    with pytest.raises(ValidationError, match="decimal-ish"):
        PerpsBookLevel.model_validate([value, "1"])


def test_market_fields_preserve_multiple_validation_errors() -> None:
    with pytest.raises(ValidationError) as captured:
        PerpsTickerUpdate.model_validate(
            {
                "iid": 4,
                "idx": True,
                "mark": [],
                "last": "100.2",
                "mid": "100.15",
                "oi": "5000",
                "fr": "0.0001",
                "nxf": "1751500000000",
            }
        )

    assert [error["loc"] for error in captured.value.errors()] == [
        ("idx",),
        ("mark",),
        ("nxf",),
    ]


def test_tuple_models_preserve_nested_field_error_locations() -> None:
    with pytest.raises(ValidationError) as captured:
        PerpsBook.model_validate(
            {
                "instrument_id": 4,
                "bids": [[True, []]],
                "asks": [],
                "timestamp": _EPOCH_MS,
                "sequence": 1,
            }
        )

    assert [error["loc"] for error in captured.value.errors()] == [
        ("bids", 0, "price"),
        ("bids", 0, "quantity"),
    ]


@pytest.mark.parametrize("value", [1.5, "1751500000000", True, None])
def test_required_timestamp_preserves_strict_epoch_ms_input(value: object) -> None:
    with pytest.raises(ValidationError, match="epoch-ms"):
        PerpsFundingRate.model_validate({"funding_rate": "0.001", "timestamp": value})


def test_tuple_preprocessing_and_optional_values_are_preserved() -> None:
    candle = PerpsCandle.model_validate((_EPOCH_MS, 1, 2.5, "0.5", Decimal("1.5"), 10, 3))
    bbo = PerpsBbo.model_validate(
        {"iid": 7, "bp": "1", "bq": "2", "ap": "3", "aq": "4", "timestamp": None}
    )

    assert candle.timestamp == _TIMESTAMP
    assert candle.open == Decimal("1")
    assert candle.high == Decimal("2.5")
    assert candle.volume == Decimal("10")
    assert bbo.timestamp is None


def test_optional_decimal_fields_accept_none_and_missing_values() -> None:
    ticker = PerpsTicker.model_validate(
        {
            "instrument_id": 7,
            "symbol": "XYZ-PERP",
            "index_price": "100",
            "mark_price": "101",
            "last_price": "100.5",
            "mid_price": "100.6",
            "open_interest": "5000",
            "funding_rate": "0.0001",
            "next_funding": _EPOCH_MS,
            "open_price": None,
        }
    )

    assert ticker.open_price is None
    assert ticker.volume_24h is None
    assert ticker.timestamp is None


@pytest.mark.parametrize("placeholder", ["", "0x"])
def test_trade_normalizes_placeholder_transaction_hash(placeholder: str) -> None:
    trade = PerpsTrade.model_validate(
        {
            "tid": 1,
            "iid": 7,
            "side": "long",
            "p": "100",
            "qty": "2",
            "ts": _EPOCH_MS,
            "hash": placeholder,
        }
    )

    assert trade.hash is None


def test_optional_timestamp_accepts_datetime_without_rewriting_it() -> None:
    bbo = PerpsBbo.model_validate(
        {
            "instrument_id": 7,
            "bid_price": "1",
            "bid_quantity": "2",
            "ask_price": "3",
            "ask_quantity": "4",
            "timestamp": _TIMESTAMP,
        }
    )

    assert bbo.timestamp is _TIMESTAMP


@pytest.mark.parametrize("value", [1.5, "1751500000000", True])
def test_optional_timestamp_preserves_strict_epoch_ms_input(value: object) -> None:
    with pytest.raises(ValidationError, match="epoch-ms"):
        PerpsBbo.model_validate(
            {
                "iid": 7,
                "bp": "1",
                "bq": "2",
                "ap": "3",
                "aq": "4",
                "timestamp": value,
            }
        )


def test_instrument_settlement_preserves_identity_and_precision() -> None:
    instrument_payload = {
        "instrument_id": 1,
        "category": "crypto",
        "symbol": "BTC-PERP",
        "base_asset": "BTC",
        "quote_asset": "USD",
        "funding_interval": "1h",
        "quantity_decimals": 4,
        "price_decimals": 2,
        "price_bounds": "0.1",
        "liquidation_fee": "0.01",
        "max_order_count": 200,
        "min_notional": "1",
        "max_market_notional": "100000",
        "max_limit_notional": "1000000",
        "max_leverage": 10,
        "isolated_only": True,
        "risk_tiers": [{"lower_bound": "0", "max_leverage": 10}],
    }
    for metadata in ({}, {"close_only": False}):
        legacy = PerpsInstrument.model_validate({**instrument_payload, **metadata})
        assert legacy.close_only is False
        assert legacy.settlement is None
        assert legacy.display_symbol is None
    retired = PerpsInstrument.model_validate(
        {
            **instrument_payload,
            "close_only": True,
            "display_symbol": "BTC-USD",
            "settlement": {
                "sequence": 2**64 - 1,
                "timestamp": _EPOCH_MS + 1,
                "price": "9007199254740993.00000001",
                "insurance_debit": "0.000000000000000001",
            },
        }
    )
    assert retired.symbol == "BTC-PERP"
    assert retired.id == 1
    assert retired.close_only is True
    assert retired.display_symbol == "BTC-USD"
    assert retired.settlement is not None
    assert retired.settlement.sequence == 2**64 - 1
    assert retired.settlement.timestamp == _TIMESTAMP.replace(microsecond=1000)
    assert retired.settlement.price == Decimal("9007199254740993.00000001")
    assert retired.settlement.insurance_debit == Decimal("0.000000000000000001")


@pytest.mark.parametrize("metadata", [{}, {"settlement": False}, {"settlement": True}])
def test_trade_settlement_flags_across_wire_shapes(metadata: dict[str, bool]) -> None:
    expanded = PerpsTrade.model_validate(
        {
            "trade_id": 3,
            "instrument_id": 1,
            "side": "long",
            "price": "123.000000000000000001",
            "quantity": "2",
            "timestamp": _EPOCH_MS,
            **metadata,
        }
    )
    compact = PerpsTrade.model_validate(
        {
            "tid": 3,
            "iid": 1,
            "side": "long",
            "p": "123.000000000000000001",
            "qty": "2",
            "ts": _EPOCH_MS,
            **metadata,
        }
    )
    assert expanded == compact
    assert expanded.settlement is metadata.get("settlement", False)
    assert expanded.price == Decimal("123.000000000000000001")
