"""Tests for the generic Arrow conversion engine."""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any, NewType

import pyarrow as pa
import pytest
from pydantic import BaseModel

from polymarket.frames import to_arrow
from polymarket.pagination import AsyncPaginator, Page, Paginator


class _Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class _Color(Enum):
    RED = 1
    GREEN = 2


_MarketIdT = NewType("_MarketIdT", str)


class _Scalar(BaseModel):
    id: _MarketIdT
    name: str
    qty: int
    ratio: float
    is_active: bool
    price: Decimal
    side: _Side
    color: _Color
    ts: datetime
    day: date


class _Inner(BaseModel):
    price: Decimal
    size: Decimal


class _WithNested(BaseModel):
    id: str
    children: tuple[_Inner, ...]


class _Optional(BaseModel):
    id: str
    nullable_price: Decimal | None = None


class _AnyPayload(BaseModel):
    payload: Any = None


def test_single_model_yields_one_row_table() -> None:
    m = _Inner(price=Decimal("0.5"), size=Decimal("100"))
    table = to_arrow(m)
    assert table.num_rows == 1
    assert table.column_names == ["price", "size"]


def test_tuple_of_models_yields_n_row_table() -> None:
    items = (
        _Inner(price=Decimal("0.5"), size=Decimal("100")),
        _Inner(price=Decimal("0.51"), size=Decimal("200")),
        _Inner(price=Decimal("0.52"), size=Decimal("300")),
    )
    table = to_arrow(items)
    assert table.num_rows == 3
    assert table.to_pylist() == [
        {"price": Decimal("0.5"), "size": Decimal("100")},
        {"price": Decimal("0.51"), "size": Decimal("200")},
        {"price": Decimal("0.52"), "size": Decimal("300")},
    ]


def test_list_of_models_also_works() -> None:
    items = [
        _Inner(price=Decimal("0.5"), size=Decimal("100")),
        _Inner(price=Decimal("0.51"), size=Decimal("200")),
    ]
    assert to_arrow(items).num_rows == 2


def test_page_delegates_to_its_items() -> None:
    page: Page[_Inner] = Page(
        items=(
            _Inner(price=Decimal("0.5"), size=Decimal("100")),
            _Inner(price=Decimal("0.51"), size=Decimal("200")),
        ),
        has_more=False,
    )
    table = to_arrow(page)
    assert table.num_rows == 2


def test_paginator_is_rejected_with_helpful_message() -> None:
    paginator: Paginator[_Inner] = Paginator(fetch=lambda _c: Page(items=(), has_more=False))
    with pytest.raises(TypeError, match="Paginator"):
        to_arrow(paginator)


def test_async_paginator_is_rejected_with_helpful_message() -> None:
    async def _fetch(_c: str | None) -> Page[_Inner]:
        return Page(items=(), has_more=False)

    paginator: AsyncPaginator[_Inner] = AsyncPaginator(fetch=_fetch)
    with pytest.raises(TypeError, match="AsyncPaginator"):
        to_arrow(paginator)


def test_mixed_sequence_is_rejected() -> None:
    with pytest.raises(TypeError, match="mixed"):
        to_arrow((_Inner(price=Decimal("0.5"), size=Decimal("100")), "not a model"))


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(TypeError, match="does not know how to convert"):
        to_arrow(42)


def test_empty_tuple_returns_empty_table() -> None:
    table = to_arrow(())
    assert table.num_rows == 0
    assert table.num_columns == 0


def test_decimal_type_is_sized_to_actual_values() -> None:
    """Regression: precision/scale used to be hardcoded to (38, 18)."""
    m = _Inner(price=Decimal("0.123"), size=Decimal("1"))
    schema = to_arrow(m).schema
    assert pa.types.is_decimal(schema.field("price").type)
    assert schema.field("price").type.precision == 3
    assert schema.field("price").type.scale == 3


def test_decimal_more_than_18_fractional_digits_preserved() -> None:
    """Regression: hardcoded decimal128(38, 18) lost precision past 18 digits."""
    high_precision = Decimal("0.1234567890123456789")
    m = _Inner(price=high_precision, size=Decimal("1"))
    table = to_arrow(m)
    assert pa.types.is_decimal(table.schema.field("price").type)
    assert table.schema.field("price").type.scale == 19
    assert table["price"][0].as_py() == high_precision


def test_decimal_scientific_notation_small_value_preserved() -> None:
    """Regression: 1E-20 needs scale 20; old hardcoded 18 would truncate."""
    m = _Inner(price=Decimal("1E-20"), size=Decimal("1"))
    table = to_arrow(m)
    assert table.schema.field("price").type.scale == 20
    assert table["price"][0].as_py() == Decimal("1E-20")


def test_decimal_promotes_to_decimal256_above_38_digits() -> None:
    """Regression: 39+ digit integers exceeded decimal128's precision cap."""
    big = Decimal("123456789012345678901234567890123456789")
    m = _Inner(price=big, size=Decimal("1"))
    table = to_arrow(m)
    field_type = table.schema.field("price").type
    assert pa.types.is_decimal256(field_type)
    assert field_type.precision == 39
    assert table["price"][0].as_py() == big


def test_decimal_too_big_for_decimal256_raises_clean_error() -> None:
    """77+ total digits exceed decimal256 — clear ValueError, not silent loss."""
    too_big = Decimal("1" + "0" * 76)
    m = _Inner(price=too_big, size=Decimal("1"))
    with pytest.raises(ValueError, match="exceeds Arrow's decimal256 maximum"):
        to_arrow(m)


def test_decimal_column_with_mixed_precision_picks_widest() -> None:
    items = (
        _Inner(price=Decimal("0.001"), size=Decimal("1500")),
        _Inner(price=Decimal("999.99999"), size=Decimal("2.5")),
    )
    schema = to_arrow(items).schema
    price_type = schema.field("price").type
    assert price_type.scale == 5
    assert price_type.precision == 8


def test_mixed_int_float_promotes_to_float64() -> None:
    """Regression: int+float column was inferred as int64, truncating floats."""

    class _IntX(BaseModel):
        x: int

    class _FloatX(BaseModel):
        x: float

    table = to_arrow((_IntX(x=1), _FloatX(x=2.2)))
    assert pa.types.is_floating(table.schema.field("x").type)
    assert table["x"].to_pylist() == [1.0, 2.2]


def test_mixed_int_decimal_promotes_to_decimal() -> None:
    class _IntX(BaseModel):
        x: int

    class _DecimalX(BaseModel):
        x: Decimal

    table = to_arrow((_IntX(x=10), _DecimalX(x=Decimal("3.14"))))
    assert pa.types.is_decimal(table.schema.field("x").type)
    assert table["x"].to_pylist() == [Decimal("10.00"), Decimal("3.14")]


def test_mixed_bool_int_promotes_to_int() -> None:
    class _BoolX(BaseModel):
        x: bool

    class _IntX(BaseModel):
        x: int

    table = to_arrow((_BoolX(x=True), _IntX(x=42)))
    assert pa.types.is_integer(table.schema.field("x").type)
    assert table["x"].to_pylist() == [1, 42]


def test_mixed_float_decimal_rejected_as_ambiguous() -> None:
    """No safe promotion — refuse rather than silently coerce."""

    class _FloatX(BaseModel):
        x: float

    class _DecimalX(BaseModel):
        x: Decimal

    with pytest.raises(TypeError, match=r"`float` and `Decimal`"):
        to_arrow((_FloatX(x=1.5), _DecimalX(x=Decimal("3.14"))))


def test_mixed_str_int_rejected() -> None:
    """No safe promotion across categories — refuse to guess."""

    class _StrX(BaseModel):
        x: str

    class _IntX(BaseModel):
        x: int

    with pytest.raises(TypeError, match="incompatible scalar types"):
        to_arrow((_StrX(x="abc"), _IntX(x=1)))


def test_mixed_dict_and_non_dict_raises_clean_typeerror() -> None:
    """Regression: raw pyarrow ArrowTypeError used to leak from the column build."""
    with pytest.raises(TypeError, match=r"dict \(struct\).*str"):
        to_arrow(
            (
                _AnyPayload(payload={"key": "value"}),
                _AnyPayload(payload="just_a_string"),
            )
        )


def test_mixed_dict_with_none_is_ok() -> None:
    table = to_arrow(
        (
            _AnyPayload(payload={"k": "v"}),
            _AnyPayload(payload=None),
            _AnyPayload(payload={"k": "w"}),
        )
    )
    assert table.num_rows == 3
    assert pa.types.is_struct(table.schema.field("payload").type)


def test_mixed_list_and_non_list_raises_clean_typeerror() -> None:
    with pytest.raises(TypeError, match=r"list/tuple.*int"):
        to_arrow(
            (
                _AnyPayload(payload=[1, 2, 3]),
                _AnyPayload(payload=42),
            )
        )


def test_mixed_list_with_none_is_ok() -> None:
    table = to_arrow(
        (
            _AnyPayload(payload=[1, 2, 3]),
            _AnyPayload(payload=None),
            _AnyPayload(payload=[4, 5]),
        )
    )
    assert table.num_rows == 3
    assert pa.types.is_list(table.schema.field("payload").type)


def test_tz_aware_datetime_becomes_utc_timestamp() -> None:
    m = _Scalar(
        id=_MarketIdT("m1"),
        name="x",
        qty=1,
        ratio=1.0,
        is_active=True,
        price=Decimal("1"),
        side=_Side.BUY,
        color=_Color.RED,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        day=date(2026, 1, 1),
    )
    schema = to_arrow(m).schema
    assert pa.types.is_timestamp(schema.field("ts").type)
    assert str(schema.field("ts").type.tz) == "UTC"


def test_naive_datetime_warns_but_works() -> None:
    class _NaiveTs(BaseModel):
        ts: datetime

    m = _NaiveTs(ts=datetime(2026, 1, 1))  # noqa: DTZ001
    with pytest.warns(UserWarning, match="naive datetime"):
        table = to_arrow(m)
    assert pa.types.is_timestamp(table.schema.field("ts").type)


def test_date_becomes_date32() -> None:
    class _OnlyDate(BaseModel):
        day: date

    m = _OnlyDate(day=date(2026, 1, 1))
    assert pa.types.is_date32(to_arrow(m).schema.field("day").type)


def test_bool_is_not_int() -> None:
    """Regression: bool must check before int since bool is a subclass of int."""

    class _Bool(BaseModel):
        flag: bool

    schema = to_arrow(_Bool(flag=True)).schema
    assert pa.types.is_boolean(schema.field("flag").type)
    assert not pa.types.is_integer(schema.field("flag").type)


def test_str_enum_serializes_as_string_value() -> None:
    class _Holder(BaseModel):
        side: _Side

    table = to_arrow(_Holder(side=_Side.BUY))
    assert table.to_pylist() == [{"side": "BUY"}]
    assert pa.types.is_string(table.schema.field("side").type)


def test_int_enum_serializes_as_int_value() -> None:
    class _Holder(BaseModel):
        color: _Color

    table = to_arrow(_Holder(color=_Color.GREEN))
    assert table.to_pylist() == [{"color": 2}]
    assert pa.types.is_integer(table.schema.field("color").type)


def test_newtype_collapses_to_underlying_str() -> None:
    """NewType is transparent at runtime; model_dump returns the str."""

    class _Holder(BaseModel):
        market_id: _MarketIdT

    table = to_arrow(_Holder(market_id=_MarketIdT("m1")))
    assert pa.types.is_string(table.schema.field("market_id").type)


def test_nested_model_becomes_list_of_struct() -> None:
    parent = _WithNested(
        id="x",
        children=(
            _Inner(price=Decimal("0.5"), size=Decimal("100")),
            _Inner(price=Decimal("0.51"), size=Decimal("200")),
        ),
    )
    schema = to_arrow(parent).schema
    children_type = schema.field("children").type
    assert pa.types.is_list(children_type)
    assert pa.types.is_struct(children_type.value_type)


def test_late_list_inner_type_inferred_from_all_rows() -> None:
    """First row has empty list; second row populated. Must still infer struct."""
    items = (
        _WithNested(id="a", children=()),
        _WithNested(
            id="b",
            children=(_Inner(price=Decimal("1"), size=Decimal("1")),),
        ),
    )
    schema = to_arrow(items).schema
    children_type = schema.field("children").type
    assert pa.types.is_list(children_type)
    assert pa.types.is_struct(children_type.value_type)


def test_all_empty_lists_falls_back_to_list_of_string() -> None:
    """Fallback: empty-only lists become list<string> since null roundtrips poorly to pandas."""
    items = (
        _WithNested(id="a", children=()),
        _WithNested(id="b", children=()),
    )
    schema = to_arrow(items).schema
    assert pa.types.is_list(schema.field("children").type)


def test_nullable_column_keeps_type_when_first_row_null() -> None:
    items = (
        _Optional(id="a", nullable_price=None),
        _Optional(id="b", nullable_price=Decimal("1.5")),
    )
    schema = to_arrow(items).schema
    assert pa.types.is_decimal(schema.field("nullable_price").type)


def test_all_null_column_falls_back_to_string() -> None:
    """Fallback: all-None column has no value to infer from; string round-trips."""
    items = (_Optional(id="a"), _Optional(id="b"))
    schema = to_arrow(items).schema
    assert pa.types.is_string(schema.field("nullable_price").type)


def test_heterogeneous_models_union_their_fields() -> None:
    class _A(BaseModel):
        type: str
        a_value: int

    class _B(BaseModel):
        type: str
        b_value: str

    items = (_A(type="a", a_value=1), _B(type="b", b_value="x"))
    table = to_arrow(items)
    assert set(table.column_names) == {"type", "a_value", "b_value"}
    rows = table.to_pylist()
    assert rows[0] == {"type": "a", "a_value": 1, "b_value": None}
    assert rows[1] == {"type": "b", "a_value": None, "b_value": "x"}


def test_sdk_orderbooklevel_round_trips() -> None:
    from polymarket.models import OrderBookLevel

    items = (
        OrderBookLevel.model_validate({"price": "0.5", "size": "100"}),
        OrderBookLevel.model_validate({"price": "0.51", "size": "200"}),
    )
    table = to_arrow(items)
    assert table.num_rows == 2
    assert pa.types.is_decimal(table.schema.field("price").type)


def test_sdk_price_history_point_round_trips() -> None:
    from polymarket.models import PriceHistoryPoint

    items = (
        PriceHistoryPoint.parse_response(
            {"timestamp": 1700000000, "price": 0.5, "resolution_seconds": 60}
        ),
        PriceHistoryPoint.parse_response(
            {"timestamp": 1700000060, "price": 0.51, "resolution_seconds": 60}
        ),
    )
    table = to_arrow(items)
    assert table.num_rows == 2
    assert set(table.column_names) == {"timestamp", "price", "resolution_seconds"}
    assert pa.types.is_timestamp(table.schema.field("timestamp").type)
    assert pa.types.is_decimal(table.schema.field("price").type)
