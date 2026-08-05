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
