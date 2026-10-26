"""polars adapter for :mod:`polymarket.frames`."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from polymarket.frames._arrow import to_arrow
from polymarket.frames._errors import MissingOptionalDependencyError

if TYPE_CHECKING:
    import polars as pl


def to_polars(
    value: object,
    *,
    explode: Sequence[str] | None = None,
) -> pl.DataFrame:
    pl = _require_polars()
    table = to_arrow(value)
    _reject_unsupported_polars_types(table.schema)

    df = pl.from_arrow(table)
    assert isinstance(df, pl.DataFrame)

    if explode:
        df = df.explode(list(explode))

    if (table.schema.metadata or {}).get(b"polymarket_limit_reached") == b"true":
        warnings.warn(
            "Reached the supported pagination depth limit; completeness is unknown. "
            "Polars cannot retain this marker; use page.limit_reached or pandas/Arrow metadata.",
            stacklevel=2,
        )

    return df


def _reject_unsupported_polars_types(schema: Any) -> None:
    # pl.from_arrow panics in Rust on decimal256; raise a clean Python error first.
    import pyarrow as pa  # noqa: PLC0415

    bad = _find_decimal256_paths(schema, pa, prefix="")
    if bad:
        raise TypeError(
            "polymarket.frames.to_polars() cannot convert columns whose "
            f"Arrow type is decimal256: {', '.join(bad)}. polars's native "
            "Decimal maxes out at precision 38. Use "
            "polymarket.frames.to_arrow() or to_pandas() for higher precision, "
            "or reduce the input precision."
        )


def _find_decimal256_paths(node: Any, pa: Any, *, prefix: str) -> list[str]:
    paths: list[str] = []

    if isinstance(node, pa.Schema):  # type: ignore[attr-defined]
        for field in node:
            paths.extend(_find_decimal256_paths(field.type, pa, prefix=field.name))
        return paths

    arrow_type = node

    if pa.types.is_decimal256(arrow_type):  # type: ignore[attr-defined]
        paths.append(prefix or "(root)")
        return paths

    if pa.types.is_struct(arrow_type):  # type: ignore[attr-defined]
        for field in arrow_type:
            child = f"{prefix}.{field.name}" if prefix else field.name
            paths.extend(_find_decimal256_paths(field.type, pa, prefix=child))
        return paths

    if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type):  # type: ignore[attr-defined]
        child = f"{prefix}[]"
        paths.extend(_find_decimal256_paths(arrow_type.value_type, pa, prefix=child))
        return paths

    return paths


def _require_polars():  # noqa: ANN202
    try:
        import pyarrow  # noqa: F401  # pyright: ignore[reportUnusedImport]
    except ImportError as e:  # pragma: no cover
        raise MissingOptionalDependencyError(
            "polymarket.frames.to_polars() requires pyarrow. "
            "Install via `pip install polymarket-client[polars]`."
        ) from e
    try:
        import polars as pl
    except ImportError as e:  # pragma: no cover
        raise MissingOptionalDependencyError(
            "polymarket.frames.to_polars() requires polars. "
            "Install via `pip install polymarket-client[polars]`."
        ) from e
    return pl


__all__ = ["to_polars"]
