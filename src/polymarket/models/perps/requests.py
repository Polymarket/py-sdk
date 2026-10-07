"""Perps order request inputs."""

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, overload

from polymarket.errors import UserInputError
from polymarket.models.perps.types import PerpsTimeInForce
from polymarket.models.types import OrderSide

_CLIENT_ORDER_ID = re.compile(r"^[0-9a-f]{32}$")

DecimalInput = Decimal | int | float | str
"""Decimal-valued input accepted for Perps prices and quantities."""


def to_decimal_string(name: str, value: DecimalInput) -> str:
    """Normalize a decimal input into its canonical wire string."""
    if isinstance(value, bool):
        raise UserInputError(f"{name} must be a decimal value, got bool")
    candidate = value if isinstance(value, str) else str(value)
    try:
        parsed = Decimal(candidate)
    except InvalidOperation as error:
        raise UserInputError(f"{name} must be a valid decimal, got {value!r}") from error
    if not parsed.is_finite():
        raise UserInputError(f"{name} must be finite, got {value!r}")
    return candidate


def validate_client_order_id(value: str) -> str:
    if not isinstance(value, str) or not _CLIENT_ORDER_ID.match(value):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("client_order_id must be a 32-character lowercase hex string")
    return value


def validate_gtd_expiry(
    time_in_force: PerpsTimeInForce, value: datetime | int | None
) -> int | None:
    """Validate order lifetime and convert an aware datetime to exact Unix milliseconds."""
    if time_in_force != "gtd":
        if value is not None:
            raise UserInputError("gtd_expiry is only supported for gtd orders")
        return None
    if value is None:
        raise UserInputError("gtd_expiry is required for gtd orders")
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise UserInputError("gtd_expiry must be a timezone-aware datetime")
        delta = value - datetime(1970, 1, 1, tzinfo=UTC)
        expiry_ms = (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000
    elif isinstance(value, bool) or not isinstance(value, int):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("gtd_expiry must be a datetime or epoch-ms int")
    else:
        expiry_ms = value
    if expiry_ms > 18_446_744_073_709:
        raise UserInputError("gtd_expiry must be at most 18446744073709 Unix milliseconds")
    if expiry_ms <= time.time_ns() // 1_000_000:
        raise UserInputError("gtd_expiry must be strictly in the future")
    return expiry_ms


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class PerpsOrderRequest:
    """One Perps order to submit.

    ``gtc`` and ``gtd`` orders require a ``price`` and may set ``post_only``. ``ioc`` and
    ``fok`` orders may omit ``price`` for market-style execution and cannot be
    post-only. Set ``reduce_only`` to prevent the order from increasing exposure.
    ``gtd`` also requires ``gtd_expiry``, separate from the command deadline.
    Builder attribution follows the session's active approved terms.
    """

    instrument_id: int
    """Instrument to trade."""
    side: OrderSide
    """Trade direction."""
    quantity: DecimalInput
    """Order quantity."""
    time_in_force: PerpsTimeInForce
    """Execution mode: ``gtc``, ``gtd``, ``ioc``, or ``fok``."""
    price: DecimalInput | None = None
    """Limit price. Required for ``gtc``/``gtd``; optional for ``ioc``/``fok``."""
    post_only: bool = False
    """Whether the order must rest instead of taking liquidity."""
    reduce_only: bool = False
    """Whether the order may only reduce or close an existing position."""
    client_order_id: str | None = None
    """Optional caller-supplied idempotency identifier."""

    gtd_expiry: datetime | int | None = None
    """GTD order expiration, an aware datetime or Unix-ms int; maximum 18446744073709 ms."""

    @overload
    def __init__(
        self,
        *,
        instrument_id: int,
        side: OrderSide,
        quantity: DecimalInput,
        time_in_force: Literal["gtd"],
        price: DecimalInput,
        gtd_expiry: datetime | int,
        post_only: bool = False,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        instrument_id: int,
        side: OrderSide,
        quantity: DecimalInput,
        time_in_force: Literal["gtc"],
        price: DecimalInput,
        post_only: bool = False,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        instrument_id: int,
        side: OrderSide,
        quantity: DecimalInput,
        time_in_force: Literal["ioc", "fok"],
        price: DecimalInput | None = None,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> None: ...

    def __init__(
        self,
        *,
        instrument_id: int,
        side: OrderSide,
        quantity: DecimalInput,
        time_in_force: PerpsTimeInForce,
        gtd_expiry: datetime | int | None = None,
        price: DecimalInput | None = None,
        post_only: bool = False,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> None:
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "time_in_force", time_in_force)
        object.__setattr__(self, "gtd_expiry", gtd_expiry)
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "post_only", post_only)
        object.__setattr__(self, "reduce_only", reduce_only)
        object.__setattr__(self, "client_order_id", client_order_id)
        self.__post_init__()

    def __post_init__(self) -> None:
        if isinstance(self.instrument_id, bool) or not isinstance(self.instrument_id, int):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise UserInputError("instrument_id must be an int")
        if self.instrument_id < 0:
            raise UserInputError("instrument_id must be non-negative")
        if self.side not in ("BUY", "SELL"):
            raise UserInputError(f"side must be 'BUY' or 'SELL', got {self.side!r}")
        if self.time_in_force not in ("gtc", "ioc", "fok", "gtd"):
            raise UserInputError(
                f"time_in_force must be 'gtc', 'gtd', 'ioc', or 'fok', got {self.time_in_force!r}"
            )
        if not isinstance(self.post_only, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise UserInputError("post_only must be a bool")
        if not isinstance(self.reduce_only, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise UserInputError("reduce_only must be a bool")
        to_decimal_string("quantity", self.quantity)
        validate_gtd_expiry(self.time_in_force, self.gtd_expiry)
        if self.time_in_force in ("gtc", "gtd"):
            if self.price is None:
                raise UserInputError(f"price is required for {self.time_in_force} orders")
        elif self.post_only:
            raise UserInputError("post_only is only supported for gtc or gtd orders")
        if self.price is not None:
            to_decimal_string("price", self.price)
        if self.client_order_id is not None:
            validate_client_order_id(self.client_order_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class PerpsTpSlTrigger:
    """A take-profit or stop-loss trigger attached to an order.

    The trigger leg executes as a market order unless ``limit_price`` is set.
    """

    trigger_price: DecimalInput
    """Mark price at which the trigger arms."""
    limit_price: DecimalInput | None = None
    """Optional limit price for the trigger leg."""

    def __post_init__(self) -> None:
        to_decimal_string("trigger_price", self.trigger_price)
        if self.limit_price is not None:
            to_decimal_string("limit_price", self.limit_price)


@dataclass(frozen=True, slots=True, kw_only=True)
class PerpsPositionTpSlTrigger:
    """A take-profit or stop-loss trigger protecting a full position."""

    trigger_price: DecimalInput
    """Mark price at which the trigger arms."""

    def __post_init__(self) -> None:
        to_decimal_string("trigger_price", self.trigger_price)


__all__ = [
    "DecimalInput",
    "PerpsOrderRequest",
    "PerpsPositionTpSlTrigger",
    "PerpsTpSlTrigger",
    "to_decimal_string",
    "validate_client_order_id",
]
