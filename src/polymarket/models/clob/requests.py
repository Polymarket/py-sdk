from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from polymarket.models.types import ClobAssetId, OrderSide


@dataclass(frozen=True, slots=True, init=False)
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
            raise ValueError("asset_id and token_id are mutually exclusive")
        value = asset_id if asset_id is not None else token_id
        if value is None:
            raise ValueError("Provide exactly one of asset_id or token_id")
        if side is None:
            raise TypeError("side is required")
        object.__setattr__(self, "asset_id", cast(ClobAssetId, value))
        object.__setattr__(self, "side", side)

    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id


__all__ = ["PriceRequest"]
