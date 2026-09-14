"""SDK-object → :class:`pyarrow.Table` engine; the pandas and polars adapters cast on top of it."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from polymarket.frames._errors import MissingOptionalDependencyError
from polymarket.frames._overrides import lookup_override
from polymarket.pagination import AsyncPaginator, Page, Paginator

if TYPE_CHECKING:
    import pyarrow as pa


def to_arrow(value: object) -> pa.Table:
    """Convert a model, sequence of models, or :class:`Page` to a :class:`pyarrow.Table`."""
    pa = _require_pyarrow()

    override = lookup_override(type(value))
    if override is not None:
        return override(value)

    if isinstance(value, Page):
        return to_arrow(tuple(value.items))

    if isinstance(value, Paginator):
        raise TypeError(
            "to_arrow() does not accept Paginator (would silently drain "
            "all pages). Use `paginator.to_arrow(limit=N)` or "
            "`paginator.to_arrow(limit=None)`."
        )
    if isinstance(value, AsyncPaginator):
        raise TypeError(
            "to_arrow() does not accept AsyncPaginator. Use `await paginator.to_arrow(limit=N)`."
        )

    if isinstance(value, BaseModel):
        return _build_table_from_models([value])

    if isinstance(value, (tuple, list)):
        items = list(value)
        if not items:
            return pa.table({})
        # Homogeneous sequence whose element type has an override:
        # hand the whole list to the override so it can emit identity columns.
        types_seen = {type(it) for it in items}
        if len(types_seen) == 1:
            seq_override = lookup_override(next(iter(types_seen)))
            if seq_override is not None:
                return seq_override(items)
        if all(isinstance(item, BaseModel) for item in items):
            return _build_table_from_models(items)
        raise TypeError(
            "to_arrow() expects a sequence of pydantic models; got mixed "
            f"types including {type(items[0]).__name__!r}."
        )

    raise TypeError(
        f"to_arrow() does not know how to convert {type(value).__name__!r}. "
        "Pass a pydantic model, a tuple/list of models, a Page, or use the "
        "method form on a Paginator."
    )


def _build_table_from_models(models: Sequence[BaseModel]) -> pa.Table:
    if not models:
        return _require_pyarrow().table({})
    rows = [m.model_dump(mode="python") for m in models]
    return _build_table_from_rows(rows)


def _build_table_from_rows(rows: Sequence[dict[str, Any]]) -> pa.Table:
    pa = _require_pyarrow()
    if not rows:
        return pa.table({})

    field_names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for name in row:
            if name not in seen:
                seen.add(name)
                field_names.append(name)

    columns: list[pa.Array] = []
    schema_fields: list[pa.Field] = []
    for name in field_names:
        column_values = [row.get(name) for row in rows]
        arrow_type = _infer_column_type(column_values)
        columns.append(_build_column(column_values, arrow_type))
        schema_fields.append(pa.field(name, arrow_type, nullable=True))

    return pa.table(columns, schema=pa.schema(schema_fields))


def _infer_column_type(values: Sequence[object]) -> pa.DataType:
    pa = _require_pyarrow()

    non_null = [v for v in values if v is not None]
    if not non_null:
        return pa.string()

    seed = non_null[0]

    if isinstance(seed, dict):
        _require_homogeneous_nested(non_null, expected_kind=dict, kind_label="dict (struct)")
        return _infer_struct_type([v for v in non_null if isinstance(v, dict)])

    if isinstance(seed, (list, tuple)):
        _require_homogeneous_nested(non_null, expected_kind=(list, tuple), kind_label="list/tuple")
        non_empty: list[object] = []
        for v in non_null:
            if isinstance(v, (list, tuple)) and len(v) > 0:
                non_empty.extend(v)
        if not non_empty:
            return pa.list_(pa.string())
        return pa.list_(_infer_column_type(non_empty))

    return _infer_scalar_column_type(non_null)


def _require_homogeneous_nested(
    values: Sequence[object],
    *,
    expected_kind: type | tuple[type, ...],
    kind_label: str,
) -> None:
    offenders: list[type] = []
    seen: set[type] = set()
    for v in values:
        if not isinstance(v, expected_kind):
            t = type(v)
            if t not in seen:
                seen.add(t)
                offenders.append(t)
    if not offenders:
        return
    raise TypeError(
        f"polymarket.frames cannot mix {kind_label} values with other "
        f"value kinds in one column. Found incompatible types: "
        f"{sorted(t.__name__ for t in offenders)}. Pick a single shape per "
        "field in your model, or split the field into separate fields per "
        "variant."
    )


def _infer_struct_type(struct_rows: Sequence[dict[str, Any]]) -> pa.DataType:
    pa = _require_pyarrow()
    field_names: list[str] = []
    seen: set[str] = set()
    for row in struct_rows:
        for name in row:
            if name not in seen:
                seen.add(name)
                field_names.append(name)
    fields: list[pa.Field] = []
    for name in field_names:
        column_values = [row.get(name) for row in struct_rows]
        fields.append(pa.field(name, _infer_column_type(column_values), nullable=True))
    return pa.struct(fields)


# Arrow decimal128 caps at precision 38; decimal256 at 76.
_DECIMAL128_MAX_PRECISION = 38
_DECIMAL256_MAX_PRECISION = 76


def _infer_scalar_column_type(non_null_values: Sequence[object]) -> pa.DataType:
    pa = _require_pyarrow()

    # Infer the values written to Arrow, so enums can share a column with their primitives.
    non_null_values = [_serialize_value(v) if isinstance(v, Enum) else v for v in non_null_values]

    # bool subclasses int; treat them as distinct categories.
    types_seen = {type(v) for v in non_null_values}

    if len(types_seen) == 1:
        return _single_type_arrow_type(non_null_values, next(iter(types_seen)))

    if types_seen <= {bool, int, float, Decimal}:
        has_float = float in types_seen
        has_decimal = Decimal in types_seen
        if has_float and has_decimal:
            raise TypeError(
                "polymarket.frames cannot mix `float` and `Decimal` values "
                "in the same column — the promotion is ambiguous (preserve "
                "precision vs. allow vectorised math). Pick one type in your "
                "model."
            )
        if has_decimal:
            promoted: list[Decimal] = []
            for v in non_null_values:
                if isinstance(v, Decimal):
                    promoted.append(v)
                elif isinstance(v, bool):
                    promoted.append(Decimal(int(v)))
                elif isinstance(v, int):
                    promoted.append(Decimal(v))
            return _infer_decimal_type(promoted)
        if has_float:
            return pa.float64()
        return pa.int64()

    raise TypeError(
        "polymarket.frames cannot mix incompatible scalar types in one "
        f"column: {sorted(t.__name__ for t in types_seen)}. Pick a single "
        "type in your model or split into separate fields."
    )


def _single_type_arrow_type(values: Sequence[object], cls: type) -> pa.DataType:
    if cls is Decimal:
        return _infer_decimal_type([v for v in values if isinstance(v, Decimal)])
    return _scalar_type_for(values[0])


def _infer_decimal_type(values: Sequence[Decimal]) -> pa.DataType:
    pa = _require_pyarrow()
    if not values:
        return pa.decimal128(1, 0)

    max_scale = 0
    max_integer_digits = 0
    for v in values:
        _, scale, integer_digits = _decimal_dimensions(v)
        max_scale = max(max_scale, scale)
        max_integer_digits = max(max_integer_digits, integer_digits)

    final_precision = max(1, max_integer_digits + max_scale)

    if final_precision <= _DECIMAL128_MAX_PRECISION:
        return pa.decimal128(final_precision, max_scale)
    if final_precision <= _DECIMAL256_MAX_PRECISION:
        return pa.decimal256(final_precision, max_scale)
    raise ValueError(
        f"polymarket.frames: Decimal column requires precision "
        f"{final_precision} (scale {max_scale}), which exceeds Arrow's "
        f"decimal256 maximum of {_DECIMAL256_MAX_PRECISION}. Reduce the "
        "magnitude or precision of the input values."
    )


def _decimal_dimensions(d: Decimal) -> tuple[int, int, int]:
    _, digits, exponent = d.as_tuple()
    if not isinstance(exponent, int):
        # 'F' (Infinity), 'n'/'N' (NaN).
        raise ValueError(f"polymarket.frames cannot represent special Decimal value: {d!r}")

    digit_count = len(digits)

    if exponent >= 0:
        scale = 0
        integer_digits = digit_count + exponent
        precision = max(1, integer_digits)
    else:
        scale = -exponent
        integer_digits = max(0, digit_count - scale)
        precision = max(digit_count, scale)

    return precision, scale, integer_digits


def _scalar_type_for(value: object) -> pa.DataType:
    pa = _require_pyarrow()

    # bool subclasses int, so check it first.
    if isinstance(value, bool):
        return pa.bool_()
    if isinstance(value, int):
        return pa.int64()
    if isinstance(value, float):
        return pa.float64()
    if isinstance(value, Decimal):
        return _infer_decimal_type([value])
    if isinstance(value, datetime):
        if value.tzinfo is None:
            warnings.warn(
                "polymarket.frames received a naive datetime; the SDK is "
                "expected to produce tz-aware (UTC) datetimes. Please report "
                "a bug if you see this from SDK output.",
                stacklevel=4,
            )
            return pa.timestamp("us")
        return pa.timestamp("us", tz="UTC")
    # datetime subclasses date, so check date last.
    if isinstance(value, date):
        return pa.date32()
    if isinstance(value, Enum):
        return _scalar_type_for(value.value)
    if isinstance(value, str):
        return pa.string()
    if isinstance(value, bytes):
        return pa.binary()
    raise TypeError(
        f"polymarket.frames cannot map Python value of type "
        f"{type(value).__name__!r} to an Arrow type."
    )


def _build_column(values: Sequence[object], arrow_type: pa.DataType) -> pa.Array:
    # pa.array refuses to coerce bool→int or int→decimal(scale>0); pre-coerce.
    pa = _require_pyarrow()
    serialized = [_serialize_value(v) for v in values]

    if pa.types.is_integer(arrow_type) and not pa.types.is_boolean(arrow_type):
        serialized = [int(v) if isinstance(v, bool) else v for v in serialized]
    elif pa.types.is_decimal(arrow_type):
        serialized = [_coerce_to_decimal(v) for v in serialized]

    return pa.array(serialized, type=arrow_type)


def _coerce_to_decimal(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return value


def _serialize_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Enum):
        return _serialize_value(value.value)
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return value


def _require_pyarrow():  # noqa: ANN202
    try:
        import pyarrow as pa
    except ImportError as e:  # pragma: no cover
        raise MissingOptionalDependencyError(
            "polymarket.frames requires pyarrow. "
            "Install via `pip install polymarket-client[arrow]` (or "
            "`[pandas]` / `[polars]` / `[quant]`)."
        ) from e
    return pa


__all__ = [
    "to_arrow",
    "_build_table_from_models",
    "_build_table_from_rows",
]
