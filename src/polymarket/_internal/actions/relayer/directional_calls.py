"""Router call builders for directional inventory operations."""

from typing import cast

from eth_abi.abi import encode as abi_encode
from eth_utils.crypto import keccak

from polymarket._internal.actions.relayer.calls import TransactionCall
from polymarket._internal.directional import (
    UINT256_MAX,
    derive_directional_bucket_positions,
    derive_directional_threshold_positions,
    normalize_directional_event_id,
)
from polymarket.errors import UserInputError
from polymarket.models.directional import ThresholdSideInput
from polymarket.types import EvmAddress, HexString


def router_horizontal_split_call(
    *, router: EvmAddress, event_id: str, amount: int
) -> TransactionCall:
    """Split pUSD into every bucket YES, including Void."""
    event = normalize_directional_event_id(event_id)
    _validate_explicit_amount(amount)
    return _encode_call(
        router,
        "horizontalSplit(bytes29,uint256)",
        ["bytes29", "uint256"],
        [bytes.fromhex(event[2:]), amount],
    )


def router_horizontal_merge_call(
    *, router: EvmAddress, event_id: str, amount: int
) -> TransactionCall:
    """Merge every bucket YES, including Void, into pUSD."""
    event = normalize_directional_event_id(event_id)
    _validate_explicit_amount(amount)
    return _encode_call(
        router,
        "horizontalMerge(bytes29,uint256)",
        ["bytes29", "uint256"],
        [bytes.fromhex(event[2:]), amount],
    )


def router_convert_call(
    *, router: EvmAddress, event_id: str, bucket_index: int, amount: int
) -> TransactionCall:
    """Convert a real bucket or Void NO into the other buckets' YES."""
    bucket = derive_directional_bucket_positions(event_id=event_id, bucket_index=bucket_index)
    _validate_explicit_amount(amount)
    return _encode_call(
        router,
        "convert(bytes29,uint16,uint256)",
        ["bytes29", "uint16", "uint256"],
        [bytes.fromhex(bucket.condition_id[2:60]), bucket_index, amount],
    )


def router_compose_threshold_call(
    *, router: EvmAddress, event_id: str, line: int, side: ThresholdSideInput, amount: int
) -> TransactionCall:
    """Combine the bucket basket into one threshold side."""
    threshold = derive_directional_threshold_positions(event_id=event_id, line=line)
    _validate_explicit_amount(amount)
    if side not in ("above", "below"):
        raise UserInputError("side must be 'above' or 'below'")
    return _encode_call(
        router,
        "composeThreshold(bytes29,uint256,uint8,uint256)",
        ["bytes29", "uint256", "uint8", "uint256"],
        [bytes.fromhex(threshold.condition_id[2:60]), line, 0 if side == "above" else 1, amount],
    )


def router_decompose_threshold_call(
    *, router: EvmAddress, event_id: str, line: int, side: ThresholdSideInput, amount: int
) -> TransactionCall:
    """Return the bucket YES basket backing one threshold side."""
    threshold = derive_directional_threshold_positions(event_id=event_id, line=line)
    _validate_explicit_amount(amount)
    if side not in ("above", "below"):
        raise UserInputError("side must be 'above' or 'below'")
    return _encode_call(
        router,
        "decomposeThreshold(bytes29,uint256,uint8,uint256)",
        ["bytes29", "uint256", "uint8", "uint256"],
        [bytes.fromhex(threshold.condition_id[2:60]), line, 0 if side == "above" else 1, amount],
    )


def router_merge_directional_call(
    *, router: EvmAddress, event_id: str, low_line: int, high_line: int, amount: int
) -> TransactionCall:
    """Return pUSD and middle-bucket YES from two threshold wings."""
    low = derive_directional_threshold_positions(event_id=event_id, line=low_line)
    derive_directional_threshold_positions(event_id=event_id, line=high_line)
    if low_line >= high_line:
        raise UserInputError("low_line must be strictly below high_line")
    _validate_explicit_amount(amount)
    return _encode_call(
        router,
        "mergeDirectional(bytes29,uint256,uint256,uint256)",
        ["bytes29", "uint256", "uint256", "uint256"],
        [bytes.fromhex(low.condition_id[2:60]), low_line, high_line, amount],
    )


def router_split_directional_call(
    *, router: EvmAddress, event_id: str, low_line: int, high_line: int, amount: int
) -> TransactionCall:
    """Consume pUSD and middle-bucket YES to restore two threshold wings."""
    low = derive_directional_threshold_positions(event_id=event_id, line=low_line)
    derive_directional_threshold_positions(event_id=event_id, line=high_line)
    if low_line >= high_line:
        raise UserInputError("low_line must be strictly below high_line")
    _validate_explicit_amount(amount)
    return _encode_call(
        router,
        "splitDirectional(bytes29,uint256,uint256,uint256)",
        ["bytes29", "uint256", "uint256", "uint256"],
        [bytes.fromhex(low.condition_id[2:60]), low_line, high_line, amount],
    )


def _encode_call(
    router: EvmAddress, signature: str, types: list[str], values: list[object]
) -> TransactionCall:
    payload = keccak(signature.encode("ascii"))[:4] + abi_encode(types, values)
    return TransactionCall(to=router, data=cast(HexString, "0x" + payload.hex()))


def _validate_explicit_amount(amount: int) -> None:
    if type(amount) is not int or not 0 < amount <= UINT256_MAX:
        raise UserInputError("amount must be a positive uint256 integer in base units")
