from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, Field, computed_field, field_validator

from polymarket._frames_bridge import frames_func as _frames_func
from polymarket.models._validators import parse_decimal_string
from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    _parse_epoch_ms_timestamp,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.types import ClobAssetId, ConditionId

_DecimalMode = Literal["decimal", "float"]


class OrderBookLevel(BaseModel):
    price: Decimal
    size: Decimal

    @field_validator("price", "size", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return parse_decimal_string(value)


class OrderBook(BaseModel):
    market: ConditionId = Field(
        description="Deprecated: use condition_id. Retained for backward compatibility."
    )
    condition_id: ConditionId = Field(
        validation_alias="market",
        description="Condition ID for the market represented by this order book.",
    )
    asset_id: ClobAssetId = Field(validation_alias=AliasChoices("asset_id", "token_id"))
    timestamp: datetime | None = None
    bids: tuple[OrderBookLevel, ...]
    """Ascending price order, lowest bid first."""
    asks: tuple[OrderBookLevel, ...]
    """Descending price order, highest ask first."""
    min_order_size: Decimal
    tick_size: Decimal
    neg_risk: bool
    last_trade_price: Decimal | None = None
    hash: str

    @computed_field
    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value: object) -> object:
        return _parse_epoch_ms_timestamp(value)

    @field_validator("min_order_size", "tick_size", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> object:
        return parse_decimal_string(value)

    @field_validator("last_trade_price", mode="before")
    @classmethod
    def _parse_last_trade_price(cls, value: object) -> object:
        return parse_decimal_string(None if value == "" else value)

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: OrderBook) -> str:
            best_bid = self.bids[-1].price if self.bids else None
            best_ask = self.asks[-1].price if self.asks else None
            spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
            title = (
                f"OrderBook  ·  {truncate_mid(self.market)}  ·  asset {truncate_mid(self.asset_id)}"
            )
            rows: list[tuple[str, str]] = [
                (
                    "bid / ask",
                    f"{best_bid if best_bid is not None else '—'} / "
                    f"{best_ask if best_ask is not None else '—'}",
                ),
                ("spread", str(spread) if spread is not None else "—"),
                ("depth", f"{len(self.bids)} bids / {len(self.asks)} asks"),
            ]
            if self.timestamp is not None:
                rows.append(("timestamp", self.timestamp.isoformat()))
            return card(title, rows=rows, hint="Call .to_pandas() for level data.")

        return render(self)

    def to_arrow(self) -> Any:
        """Flatten this book into ``[side, level, price, size]`` rows."""
        return _frames_func("to_arrow")(self)

    def to_pandas(
        self,
        *,
        decimal: _DecimalMode = "decimal",
        explode: Sequence[str] | None = None,
    ) -> Any:
        return _frames_func("to_pandas")(self, decimal=decimal, explode=explode)

    def to_polars(
        self,
        *,
        explode: Sequence[str] | None = None,
    ) -> Any:
        return _frames_func("to_polars")(self, explode=explode)


__all__ = ["OrderBook", "OrderBookLevel"]
