"""Compatibility helpers for canonical CLOB asset identifiers."""

from collections.abc import Sequence
from typing import cast

from polymarket._internal.validation import require_nonempty
from polymarket.errors import UserInputError
from polymarket.models.types import ClobAssetId


def resolve_asset_id(
    *,
    asset_id: str | None,
    token_id: str | None,
) -> ClobAssetId:
    if asset_id is not None and token_id is not None:
        raise UserInputError("asset_id and token_id are mutually exclusive")
    value = asset_id if asset_id is not None else token_id
    if value is None:
        raise UserInputError("Provide exactly one of asset_id or token_id")
    field = "asset_id" if asset_id is not None else "token_id"
    return cast(ClobAssetId, require_nonempty(field, value))


def resolve_optional_asset_id(
    *,
    asset_id: str | None,
    token_id: str | None,
) -> ClobAssetId | None:
    if asset_id is not None and token_id is not None:
        raise UserInputError("asset_id and token_id are mutually exclusive")
    if asset_id is None and token_id is None:
        return None
    return resolve_asset_id(asset_id=asset_id, token_id=token_id)


def resolve_asset_ids(
    *,
    asset_ids: Sequence[str] | None,
    token_ids: Sequence[str] | None,
) -> tuple[ClobAssetId, ...]:
    if asset_ids is not None and token_ids is not None:
        raise UserInputError("asset_ids and token_ids are mutually exclusive")
    values = asset_ids if asset_ids is not None else token_ids
    if values is None:
        raise UserInputError("Provide exactly one of asset_ids or token_ids")
    field = "asset_ids" if asset_ids is not None else "token_ids"
    if isinstance(values, str | bytes):
        raise UserInputError(f"{field} must be a sequence of strings, not a single string")
    if not values:
        raise UserInputError(f"{field} must be a non-empty sequence")
    return tuple(
        cast(ClobAssetId, require_nonempty(f"{field}[{index}]", value))
        for index, value in enumerate(values)
    )


__all__ = ["resolve_asset_id", "resolve_asset_ids", "resolve_optional_asset_id"]
