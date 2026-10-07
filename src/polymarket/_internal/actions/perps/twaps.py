"""TWAP command construction and public-input validation."""

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


def create_twap_op(
    *,
    instrument_id: int,
    side: OrderSide,
    quantity: DecimalInput,
    duration_ms: int,
    interval_ms: int | None = None,
    randomize: bool = False,
    slippage_bps: int = 0,
    min_price: DecimalInput | None = None,
    max_price: DecimalInput | None = None,
    reduce_only: bool = False,
    client_order_id: str | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    _integer("instrument_id", instrument_id, 0, 2**32 - 1)
    _integer("duration_ms", duration_ms, 300000, 86400000)
    _integer("slippage_bps", slippage_bps, 0, 10000)
    if side not in ("BUY", "SELL"):
        raise UserInputError("side must be BUY or SELL")
    if not isinstance(randomize, bool) or not isinstance(reduce_only, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("randomize and reduce_only must be bool")
    if interval_ms is not None:
        _integer("interval_ms", interval_ms, 0, duration_ms)
        if interval_ms != 0 and (interval_ms < 30000 or duration_ms % interval_ms):
            raise UserInputError("interval_ms must be >=30000 and divide duration_ms exactly")
    qty = _decimal("quantity", quantity)
    if Decimal(qty) <= 0:
        raise UserInputError("quantity must be positive")
    minimum = None if min_price is None else _decimal("min_price", min_price)
    maximum = None if max_price is None else _decimal("max_price", max_price)
    if (
        minimum is not None
        and maximum is not None
        and Decimal(minimum) != 0
        and Decimal(maximum) != 0
        and Decimal(minimum) >= Decimal(maximum)
    ):
        raise UserInputError("max_price must exceed min_price when both bounds are set")
    if client_order_id is not None:
        validate_client_order_id(client_order_id)
    args = dict(
        iid=instrument_id,
        buy=side == "BUY",
        qty=qty,
        dur=duration_ms,
        ivl=interval_ms,
        rnd=randomize,
        slip_bps=slippage_bps,
        min_px=minimum,
        max_px=maximum,
        ro=reduce_only,
        c=client_order_id,
    )
    return ["createTwap", list(args.values())], {
        "type": "createTwap",
        "args": {key: value for key, value in args.items() if value is not None},
    }


def control_twap_op(
    twap_id: int, action: Literal["pause", "resume"]
) -> tuple[list[Any], dict[str, Any]]:
    _integer("twap_id", twap_id, 1, 2**53 - 1)
    return ["controlTwap", [twap_id, action]], {
        "type": "controlTwap",
        "args": {"twid": twap_id, "act": action},
    }


def cancel_twap_op(twap_id: int) -> tuple[list[Any], dict[str, Any]]:
    _integer("twap_id", twap_id, 1, 2**53 - 1)
    return ["cancelTwap", [twap_id]], {"type": "cancelTwap", "args": {"twid": twap_id}}


class _TwapCommandResponse(BaseModel):
    status: Literal["ok", "err"]
    error: str | None = None


def check_twap_response(response: object) -> None:
    acknowledgement = _TwapCommandResponse.parse_response(response)
    if acknowledgement.status == "err":
        raise RequestRejectedError(
            acknowledgement.error or "Perps TWAP command was rejected", status=200
        )
