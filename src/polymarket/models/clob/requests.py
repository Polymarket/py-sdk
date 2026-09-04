from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

from polymarket._internal.validation import require_nonempty
from polymarket.errors import UserInputError
from polymarket.models.types import ClobAssetId, OrderSide


@dataclass(frozen=True, slots=True, init=False, eq=False)
class PriceRequest:
    asset_id: ClobAssetId
    side: OrderSide

    def __init__(
        self,
        asset_id: str | None = None,
        side: OrderSide | None = None,
        *,
        token_id: str | None = None,
    ) -> None:
        if asset_id is not None and token_id is not None:
            raise UserInputError("asset_id and token_id are mutually exclusive")
        value = asset_id if asset_id is not None else token_id
        if value is None:
            raise UserInputError("Provide exactly one of asset_id or token_id")
        if side is None:
            raise UserInputError("side is required")
        field = "asset_id" if asset_id is not None else "token_id"
        object.__setattr__(
            self,
            "asset_id",
            cast(ClobAssetId, require_nonempty(field, value)),
        )
        object.__setattr__(self, "side", side)

    def __iter__(self) -> Iterator[ClobAssetId | OrderSide]:
        """Preserve the unpacking behavior of the former named tuple."""

        return iter((self.asset_id, self.side))

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int | slice) -> ClobAssetId | OrderSide | tuple[object, ...]:
        return (self.asset_id, self.side)[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PriceRequest):
            return self.asset_id == other.asset_id and self.side == other.side
        if isinstance(other, tuple):
            return (self.asset_id, self.side) == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.asset_id, self.side))

    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id


__all__ = ["PriceRequest"]
