from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import BeforeValidator, Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    ExpirationTimestamp,
    RequiredEpochOrIsoTimestamp,
    _DecimalFromString,  # pyright: ignore[reportPrivateUsage]
)
from polymarket.models.types import CtfConditionId, OrderSide, TokenId

AssetType: TypeAlias = Literal["COLLATERAL", "CONDITIONAL"]

TradeStatus: TypeAlias = Literal[
    "MATCHED",
    "MATCHED_NOT_BROADCASTED",
    "MINED",
    "CONFIRMED",
    "RETRYING",
    "FAILED",
]
"""Lifecycle status of a trade, from creation through on-chain settlement.

``CONFIRMED`` and ``FAILED`` are the terminal states.
``MATCHED_NOT_BROADCASTED`` currently appears only on trades read via
account trade listings, not on user stream trade events.
"""


def _normalize_trade_status(value: object) -> object:
    # Trade statuses arrive in two wire forms: REST endpoints serialize the
    # raw prefixed constants ("TRADE_STATUS_CONFIRMED") while stream events
    # use plain values ("CONFIRMED"). Normalize both to the plain form.
    if isinstance(value, str) and value.startswith("TRADE_STATUS_"):
        return value[len("TRADE_STATUS_") :]
    return value


TradeStatusField = Annotated[TradeStatus, BeforeValidator(_normalize_trade_status)]


class OpenOrder(BaseModel):
    """Open order owned by an account."""

    id: str
    market: CtfConditionId = Field(
        description="Deprecated: use condition_id. Retained for backward compatibility."
    )
    condition_id: CtfConditionId = Field(
        validation_alias="market",
        description="CTF condition id for the market associated with this order.",
    )
    token_id: TokenId = Field(validation_alias="asset_id")
    owner: str
    maker_address: str = Field(validation_alias="maker_address")
    side: OrderSide
    price: _DecimalFromString
    original_size: _DecimalFromString = Field(validation_alias="original_size")
    size_matched: _DecimalFromString = Field(validation_alias="size_matched")
    outcome: str
    order_type: str = Field(validation_alias="order_type")
    status: str
    associate_trades: tuple[str, ...] = Field(default=(), validation_alias="associate_trades")
    created_at: RequiredEpochOrIsoTimestamp = Field(validation_alias="created_at")
    expires_at: ExpirationTimestamp = Field(default=None, validation_alias="expiration")

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: OpenOrder) -> str:
            title = f"OpenOrder  ·  {self.side}  ·  {self.status}"
            rows: list[tuple[str, str]] = [
                ("id", truncate_mid(self.id)),
                ("price", str(self.price)),
                ("size", str(self.original_size)),
                ("matched", str(self.size_matched)),
                ("market", truncate_mid(self.market)),
            ]
            return card(title, rows=rows)

        return render(self)


class MakerOrder(BaseModel):
    """Maker-side fill information attached to a trade."""

    order_id: str = Field(validation_alias="order_id")
    token_id: TokenId = Field(validation_alias="asset_id")
    maker_address: str = Field(validation_alias="maker_address")
    owner: str
    side: OrderSide
    price: _DecimalFromString
    matched_amount: _DecimalFromString = Field(validation_alias="matched_amount")
    outcome: str
    fee_rate_bps: _DecimalFromString | None = Field(default=None, validation_alias="fee_rate_bps")

    @field_validator("fee_rate_bps", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        return None if value == "" else value


class ClobTrade(BaseModel):
    """Executed trade for an account or market."""

    id: str
    market: CtfConditionId = Field(
        description="Deprecated: use condition_id. Retained for backward compatibility."
    )
    condition_id: CtfConditionId = Field(
        validation_alias="market",
        description="CTF condition id for the market associated with this trade.",
    )
    token_id: TokenId = Field(validation_alias="asset_id")
    owner: str
    maker_address: str = Field(validation_alias="maker_address")
    taker_order_id: str = Field(validation_alias="taker_order_id")
    side: OrderSide
    trader_side: Literal["TAKER", "MAKER"] = Field(validation_alias="trader_side")
    price: _DecimalFromString
    size: _DecimalFromString
    outcome: str
    status: TradeStatusField
    fee_rate_bps: _DecimalFromString = Field(validation_alias="fee_rate_bps")
    bucket_index: int = Field(validation_alias="bucket_index")
    transaction_hash: str = Field(validation_alias="transaction_hash")
    maker_orders: tuple[MakerOrder, ...] = Field(validation_alias="maker_orders")
    matched_at: RequiredEpochOrIsoTimestamp = Field(validation_alias="match_time")
    updated_at: RequiredEpochOrIsoTimestamp = Field(validation_alias="last_update")

    def _repr_html_(self) -> str:
        from polymarket._jupyter import card, safe_html_repr, truncate_mid

        @safe_html_repr
        def render(self: ClobTrade) -> str:
            title = f"Trade  ·  {self.side}  ·  {self.matched_at.isoformat()}"
            rows: list[tuple[str, str]] = [
                ("price", str(self.price)),
                ("size", str(self.size)),
                ("market", truncate_mid(self.market)),
                ("id", truncate_mid(self.id)),
            ]
            return card(title, rows=rows)

        return render(self)


class Notification(BaseModel):
    """Account notification."""

    id: int
    owner: str
    type: int
    payload: Any = None
    timestamp: RequiredEpochOrIsoTimestamp

    @field_validator("id", mode="before")
    @classmethod
    def _parse_id(cls, value: object) -> int:
        if isinstance(value, bool):
            msg = f"notification id must be an integer, got bool {value!r}"
            raise ValueError(msg)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and (
            value.isdigit() or (value.startswith("-") and value[1:].isdigit())
        ):
            return int(value)
        msg = f"notification id must be an integer or numeric string, got {type(value).__name__}"
        raise ValueError(msg)


class BalanceAllowance(BaseModel):
    """Balance and allowance values for an asset in base units."""

    balance: int
    allowances: dict[str, int]

    @field_validator("balance", mode="before")
    @classmethod
    def _parse_balance(cls, value: object) -> int:
        return _parse_base_units(value, "balance")

    @field_validator("allowances", mode="before")
    @classmethod
    def _parse_allowances(cls, value: object) -> object:
        if not isinstance(value, dict):
            msg = f"allowances must be a mapping, got {type(value).__name__}"
            raise ValueError(msg)
        items = cast(dict[object, object], value).items()
        result: dict[str, int] = {}
        for key, raw in items:
            if not isinstance(key, str):
                msg = f"allowances key must be a string, got {type(key).__name__}"
                raise ValueError(msg)
            result[key] = _parse_base_units(raw, f"allowances[{key}]")
        return result


def _parse_base_units(value: object, name: str) -> int:
    if isinstance(value, bool):
        msg = f"{name} must be an integer, got bool"
        raise ValueError(msg)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as error:
            msg = f"{name} must be a base-units integer, got {value!r}"
            raise ValueError(msg) from error
    msg = f"{name} must be an integer or numeric string, got {type(value).__name__}"
    raise ValueError(msg)


__all__ = [
    "AssetType",
    "BalanceAllowance",
    "ClobTrade",
    "MakerOrder",
    "Notification",
    "OpenOrder",
]
