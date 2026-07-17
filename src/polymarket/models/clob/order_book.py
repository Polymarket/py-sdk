from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import Field, field_validator

from polymarket._frames_bridge import frames_func as _frames_func
from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    EpochMsTimestamp,
    _DecimalFromString,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.types import CtfConditionId, TokenId

_DecimalMode = Literal["decimal", "float"]


class OrderBookLevel(BaseModel):
    price: _DecimalFromString
    size: _DecimalFromString


class OrderBook(BaseModel):
    market: CtfConditionId = Field(
        description="Deprecated: use condition_id. Retained for backward compatibility."
    )
    condition_id: CtfConditionId = Field(
        validation_alias="market",
        description="CTF condition id for the market represented by this order book.",
    )
    token_id: TokenId = Field(validation_alias="asset_id")
    timestamp: EpochMsTimestamp = None
    bids: tuple[OrderBookLevel, ...]
    """Ascending price order, lowest bid first."""
    asks: tuple[OrderBookLevel, ...]
    """Descending price order, highest ask first."""
    min_order_size: _DecimalFromString
    tick_size: _DecimalFromString
    neg_risk: bool
    last_trade_price: _DecimalFromString | None = None
    hash: str

    @field_validator("last_trade_price", mode="before")
    @classmethod
    def _parse_last_trade_price(cls, value: object) -> object:
        return None if value in (None, "") else value

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: OrderBook) -> str:
            best_bid = self.bids[-1].price if self.bids else None
            best_ask = self.asks[-1].price if self.asks else None
            spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
            title = (
                f"OrderBook  ·  {truncate_mid(self.market)}  ·  token {truncate_mid(self.token_id)}"
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
