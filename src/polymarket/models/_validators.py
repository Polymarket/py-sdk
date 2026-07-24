"""Field validators shared across SDK model packages."""

from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

from pydantic import BeforeValidator, PlainSerializer


def parse_decimal_string(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        msg = f"expected decimal string, got {type(value).__name__}"
        raise ValueError(msg)
    return value


def parse_e6_decimal_string(value: object) -> object:
    """Parse a base-unit integer string carrying six implied decimals.

    Only unsigned integer strings are accepted; anything carrying a sign,
    decimal point, or exponent would be silently mis-scaled, so it fails
    loudly.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        msg = f"expected base-unit integer string, got {type(value).__name__}"
        raise ValueError(msg)
    if not value.isdecimal():
        msg = f"invalid base-unit integer string: {value!r}"
        raise ValueError(msg)
    return Decimal(value).scaleb(-6)


def serialize_e6_decimal_string(value: Decimal) -> str:
    """Serialize a scaled amount back to the base-unit integer string the wire carries."""
    return str(int(value.scaleb(6)))


if TYPE_CHECKING:
    DecimalFromString = Decimal
    DecimalFromE6String = Decimal
else:
    DecimalFromString = Annotated[Decimal, BeforeValidator(parse_decimal_string)]
    # JSON dumps write the wire's base-unit integer string so a dumped model
    # re-validates to the same amount instead of being rescaled a second time.
    DecimalFromE6String = Annotated[
        Decimal,
        BeforeValidator(parse_e6_decimal_string),
        PlainSerializer(serialize_e6_decimal_string, return_type=str, when_used="json"),
    ]


__all__ = [
    "DecimalFromE6String",
    "DecimalFromString",
]
