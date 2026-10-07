"""Chase command construction and public-input validation."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from polymarket.errors import RequestRejectedError, UserInputError
from polymarket.models.base import BaseModel
from polymarket.models.perps.requests import (
    DecimalInput,
    to_decimal_string,
    validate_client_order_id,
)
from polymarket.models.types import OrderSide

from .paging import to_epoch_ms


def _integer(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def _decimal(name: str, value: DecimalInput) -> str:
    decimal = Decimal(to_decimal_string(name, value))
    if decimal < 0:
        raise UserInputError(f"{name} must be nonnegative")
    exponent = decimal.as_tuple().exponent
    if decimal.adjusted() > 28 or not isinstance(exponent, int) or exponent < -100:
        raise UserInputError(f"{name} exceeds supported decimal precision")
    text = format(decimal, "f")
    # Strip insignificant fractional zeros without Decimal.normalize's context rounding.
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    whole, _, fraction = text.partition(".")
    if len(fraction) > 28 or int(whole + fraction) > 79228162514264337593543950335:
        raise UserInputError(f"{name} exceeds supported decimal precision")
    return text


def build_create_chase_op(
    *,
    instrument_id: int,
    side: OrderSide,
    quantity: DecimalInput,
    limit_price: DecimalInput | None = None,
    max_distance: DecimalInput | None = None,
    max_distance_bps: int | None = None,
    post_only: bool = True,
    reduce_only: bool = False,
    client_order_id: str | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    _integer("instrument_id", instrument_id, 0, 2**32 - 1)
    if side not in ("BUY", "SELL"):
        raise UserInputError("side must be BUY or SELL")
    if not isinstance(post_only, bool) or not isinstance(reduce_only, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("post_only and reduce_only must be bool")
    qty = _decimal("quantity", quantity)
    if Decimal(qty) <= 0:
        raise UserInputError("quantity must be positive")
    limit = None if limit_price is None else _decimal("limit_price", limit_price)
    distance = None if max_distance is None else _decimal("max_distance", max_distance)
    if max_distance_bps is not None:
        _integer("max_distance_bps", max_distance_bps, 1, 1000)
        if distance is not None and Decimal(distance) != 0:
            raise UserInputError("Use max_distance or max_distance_bps, not both")
    if client_order_id is not None:
        validate_client_order_id(client_order_id)
    args = dict(
        iid=instrument_id,
        buy=side == "BUY",
        qty=qty,
        lim=limit,
        max_dist=distance,
        max_dist_bps=max_distance_bps,
        po=post_only,
        ro=reduce_only,
        c=client_order_id,
    )
    return ["createChase", list(args.values())], {
        "type": "createChase",
        "args": {key: value for key, value in args.items() if value is not None},
    }


def build_cancel_chase_op(chase_id: int) -> tuple[list[Any], dict[str, Any]]:
    _integer("chase_id", chase_id, 1, 2**53 - 1)
    return ["cancelChase", [chase_id]], {"type": "cancelChase", "args": {"chid": chase_id}}


def validate_chase_deadline(expires_at: datetime | int | None) -> None:
    deadline = to_epoch_ms("expires_at", expires_at)
    if deadline is not None:
        _integer("expires_at", deadline, 1, 2**53 - 1)


class _ChaseCommandResponse(BaseModel):
    status: Literal["ok", "err"]
    error: str | None = None


def check_chase_response(response: object) -> None:
    acknowledgement = _ChaseCommandResponse.parse_response(response)
    if acknowledgement.status == "err":
        raise RequestRejectedError(
            acknowledgement.error or "Perps chase command was rejected", status=200
        )
