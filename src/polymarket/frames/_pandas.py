"""pandas adapter for :mod:`polymarket.frames`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

from polymarket.frames._arrow import to_arrow
from polymarket.frames._errors import MissingOptionalDependencyError

if TYPE_CHECKING:
    import pandas as pd


DecimalMode = Literal["decimal", "float"]


def to_pandas(
    value: object,
    *,
    decimal: DecimalMode = "decimal",
    explode: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Convert SDK objects to a pandas DataFrame.

    ``decimal="float"`` casts only top-level Arrow decimal columns to
    ``float64``. Decimal values nested inside struct/list columns stay
    precision-preserving; explode or normalize those columns first if you
    want to cast them explicitly.
    """
    pa, pd = _require_pandas_stack()

    if decimal not in ("decimal", "float"):
        raise TypeError(f"decimal must be 'decimal' or 'float'; got {decimal!r}")

    table = to_arrow(value)

    if decimal == "float":
        table = _cast_decimal_to_float(table, pa)

    df = _arrow_table_to_pandas(table, pa, pd, decimal=decimal)

    if explode:
        df = df.explode(list(explode))

    metadata = table.schema.metadata or {}
    if metadata.get(b"polymarket_truncated") == b"true":
        df.attrs["polymarket_truncated"] = True
    if metadata.get(b"polymarket_limit_reached") == b"true":
        df.attrs["polymarket_limit_reached"] = True

    return df


def _arrow_table_to_pandas(
    table,  # type: ignore[no-untyped-def]
    pa,  # type: ignore[no-untyped-def]  # noqa: ARG001
    pd,  # type: ignore[no-untyped-def]
    *,
    decimal: DecimalMode,
):  # noqa: ANN202
    if decimal == "decimal":
        return table.to_pandas(types_mapper=pd.ArrowDtype)
    return table.to_pandas()


def _cast_decimal_to_float(table, pa):  # type: ignore[no-untyped-def] # noqa: ANN202
    if not any(pa.types.is_decimal(field.type) for field in table.schema):
        return table

    new_arrays = []
    new_fields = []
    for i, field in enumerate(table.schema):
        column = table.column(i)
        if pa.types.is_decimal(field.type):
            column = column.cast(pa.float64())
            field = pa.field(field.name, pa.float64(), nullable=field.nullable)
        new_arrays.append(column)
        new_fields.append(field)
    return pa.Table.from_arrays(
        new_arrays, schema=pa.schema(new_fields, metadata=table.schema.metadata)
    )


def _require_pandas_stack():  # noqa: ANN202
    try:
        import pyarrow as pa
    except ImportError as e:  # pragma: no cover
        raise MissingOptionalDependencyError(
            "polymarket.frames.to_pandas() requires pyarrow. "
            "Install via `pip install polymarket-client[pandas]`."
        ) from e
    try:
        import pandas as pd
    except ImportError as e:  # pragma: no cover
        raise MissingOptionalDependencyError(
            "polymarket.frames.to_pandas() requires pandas. "
            "Install via `pip install polymarket-client[pandas]`."
        ) from e
    return pa, pd


__all__ = ["DecimalMode", "to_pandas"]
