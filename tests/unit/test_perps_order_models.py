"""Perps order and fill model validation tests."""

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import get_type_hints

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.perps.orders import PerpsFill, PerpsOrder, PerpsTpSlOrderFields


def _compact_order(**overrides: object) -> dict[str, object]:
    return {
        "oid": 5,
        "iid": 1,
        "buy": True,
        "p": "0.5",
        "qty": "10",
        "tif": "gtc",
        "po": False,
        "ro": True,
        "status": "open",
        "rest": "10",
        "fill": "0",
        "cts": 1751500000000,
        "uts": 1751500000001,
        **overrides,
    }


def _expanded_order(**overrides: object) -> dict[str, object]:
    return {
        "order_id": 5,
        "instrument_id": 1,
        "buy": False,
        "price": "0.5",
        "quantity": "10",
        "tif": "gtc",
        "post_only": False,
        "ro": True,
        "status": "open",
        "resting_quantity": "10",
        "filled_quantity": "0",
        "created_timestamp": 1751500000000,
        "updated_timestamp": 1751500000001,
        **overrides,
    }


def _compact_fill(**overrides: object) -> dict[str, object]:
    return {
        "tid": 9,
        "oid": 5,
        "iid": 1,
        "side": "long",
        "p": "100.5",
        "qty": "2",
        "taker": True,
        "fee": "0.01",
        "fea": "USDC",
        "psz": "0",
        "pep": "0",
        "pnl": "1.25",
        "liq": False,
        "ts": 1751500000000,
        **overrides,
    }


def _expanded_fill(**overrides: object) -> dict[str, object]:
    return {
        "trade_id": 9,
        "order_id": 5,
        "instrument_id": 1,
        "side": "short",
        "price": "100.5",
        "quantity": "2",
        "taker": False,
        "fee": "0.01",
        "fee_asset": "USDC",
        "previous_size": "3",
        "previous_entry_price": "99",
        "pnl": "-1.25",
        "liquidation": False,
        "timestamp": 1751500000000,
        **overrides,
    }


@pytest.mark.parametrize(
    ("model", "expected", "signature_names"),
    [
        (
            PerpsTpSlOrderFields,
            {"trigger_price": Decimal, "armed_quantity": Decimal | None},
            {"trigger_price": "trp", "armed_quantity": "armed_qty"},
        ),
        (
            PerpsOrder,
            {
                "price": Decimal,
                "quantity": Decimal,
                "resting_quantity": Decimal,
                "filled_quantity": Decimal,
                "created_at": datetime,
                "updated_at": datetime,
            },
            {},
        ),
        (
            PerpsFill,
            {
                "price": Decimal,
                "quantity": Decimal,
                "fee": Decimal,
                "previous_size": Decimal,
                "previous_entry_price": Decimal,
                "pnl": Decimal,
                "timestamp": datetime,
                "hash": str | None,
            },
            {},
        ),
    ],
)
def test_annotations_and_signatures_expose_canonical_types(
    model: type[PerpsTpSlOrderFields] | type[PerpsOrder] | type[PerpsFill],
    expected: dict[str, object],
    signature_names: dict[str, str],
) -> None:
    hints = get_type_hints(model, include_extras=True)
    parameters = inspect.signature(model).parameters

    for field, annotation in expected.items():
        assert hints[field] == annotation
        assert model.model_fields[field].annotation == annotation
        assert parameters[signature_names.get(field, field)].annotation == annotation


def test_order_preserves_compact_and_expanded_aliases_and_buy_normalization() -> None:
    compact = PerpsOrder.parse_response(_compact_order())
    expanded = PerpsOrder.parse_response(_expanded_order())

    assert compact.side == "BUY"
    assert expanded.side == "SELL"
    assert compact.price == expanded.price == Decimal("0.5")
    assert compact.created_at == expanded.created_at == datetime(2025, 7, 2, 23, 46, 40, tzinfo=UTC)


def test_order_parses_nested_tpsl_decimals() -> None:
    order = PerpsOrder.parse_response(
        _compact_order(
            tpsl={
                "kind": "tp",
                "scope": "position",
                "trp": 105,
                "armed_qty": 1.5,
            }
        )
    )

    assert order.tp_sl is not None
    assert order.tp_sl.trigger_price == Decimal("105")
    assert order.tp_sl.armed_quantity == Decimal("1.5")


@pytest.mark.parametrize("field", ["trp", "armed_qty"])
def test_tpsl_decimal_fields_reject_bool(field: str) -> None:
    payload: dict[str, object] = {
        "kind": "tp",
        "scope": "position",
        "trp": "105",
        "armed_qty": "1.5",
    }
    payload[field] = True

    with pytest.raises(UnexpectedResponseError):
        PerpsTpSlOrderFields.parse_response(payload)


@pytest.mark.parametrize("field", ["p", "qty", "rest", "fill"])
def test_order_decimal_fields_reject_bool(field: str) -> None:
    with pytest.raises(UnexpectedResponseError):
        PerpsOrder.parse_response(_compact_order(**{field: True}))


@pytest.mark.parametrize("field", ["cts", "uts"])
@pytest.mark.parametrize("value", [True, 1751500000000.0, "1751500000000", None])
def test_order_timestamps_remain_strict_epoch_milliseconds(field: str, value: object) -> None:
    with pytest.raises(UnexpectedResponseError):
        PerpsOrder.parse_response(_compact_order(**{field: value}))


def test_order_rejects_pre_normalized_side_in_buy_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        PerpsOrder.parse_response(_compact_order(buy="BUY"))


def test_order_timestamps_accept_datetime_instances() -> None:
    timestamp = datetime(2025, 7, 2, 23, 46, 40, tzinfo=UTC)
    order = PerpsOrder.parse_response(_compact_order(cts=timestamp, uts=timestamp))

    assert order.created_at is timestamp
    assert order.updated_at is timestamp


def test_fill_preserves_compact_and_expanded_aliases_and_numeric_conversion() -> None:
    compact = PerpsFill.parse_response(_compact_fill(p=100.5, qty=2))
    expanded = PerpsFill.parse_response(_expanded_fill())

    assert compact.price == expanded.price == Decimal("100.5")
    assert compact.quantity == expanded.quantity == Decimal("2")
    assert compact.timestamp == expanded.timestamp == datetime(2025, 7, 2, 23, 46, 40, tzinfo=UTC)


@pytest.mark.parametrize("placeholder", ["", "0x"])
def test_fill_normalizes_placeholder_hashes(placeholder: str) -> None:
    assert PerpsFill.parse_response(_compact_fill(hash=placeholder)).hash is None


def test_fill_preserves_transaction_hash() -> None:
    transaction_hash = "0x" + "1" * 64
    assert PerpsFill.parse_response(_compact_fill(hash=transaction_hash)).hash == transaction_hash


@pytest.mark.parametrize("field", ["p", "qty", "fee", "psz", "pep", "pnl"])
def test_fill_decimal_fields_reject_bool(field: str) -> None:
    with pytest.raises(UnexpectedResponseError):
        PerpsFill.parse_response(_compact_fill(**{field: False}))


@pytest.mark.parametrize("value", [True, 1751500000000.0, "1751500000000", None])
def test_fill_timestamp_remains_strict_epoch_milliseconds(value: object) -> None:
    with pytest.raises(UnexpectedResponseError):
        PerpsFill.parse_response(_compact_fill(ts=value))
