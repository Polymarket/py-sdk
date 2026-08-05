"""Field validators shared across SDK model packages."""

from decimal import Decimal


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
