from collections.abc import Callable
from functools import partial
from typing import Any

import pytest

from polymarket._internal.actions.relayer.calls import parse_neg_risk_condition_id
from polymarket.calls import (
    MAX_UINT256,
    TransactionCall,
    router_convert_call,
    router_horizontal_merge_call,
    router_horizontal_split_call,
)
from polymarket.errors import UserInputError
from polymarket.types import EvmAddress

_ROUTER = EvmAddress("0x0000000000000000000000000000000000001234")
# module 2, base hash, arity 3, reserved zero, resolution chain 0.
_EVENT_ID = "0x02" + "11" * 16 + "0003" + "00" * 10
_BUILDERS: list[Callable[..., TransactionCall]] = [
    router_horizontal_split_call,
    router_horizontal_merge_call,
    partial(router_convert_call, condition_index=3),
]


@pytest.mark.parametrize("suffix", ["", "000000"])
@pytest.mark.parametrize(
    ("builder", "selector", "index_word"),
    [
        (router_horizontal_split_call, "40657b52", ""),
        (router_horizontal_merge_call, "24f24944", ""),
        (_BUILDERS[2], "9380f1c8", f"{3:064x}"),
    ],
)
def test_router_neg_risk_calldata(
    builder: Callable[..., TransactionCall], selector: str, index_word: str, suffix: str
) -> None:
    call = builder(router=_ROUTER, protocol_event_id=_EVENT_ID + suffix, amount=1_000_000)
    assert call.to == _ROUTER
    assert call.value == 0
    assert (
        call.data == "0x" + selector + _EVENT_ID[2:] + "000000" + index_word + f"{1_000_000:064x}"
    )


@pytest.mark.parametrize("builder", _BUILDERS)
@pytest.mark.parametrize("amount", [0, -1, MAX_UINT256 + 1, True, 1.5, "max"])
def test_router_neg_risk_rejects_invalid_amount(
    builder: Callable[..., TransactionCall], amount: Any
) -> None:
    with pytest.raises(UserInputError):
        builder(router=_ROUTER, protocol_event_id=_EVENT_ID, amount=amount)


@pytest.mark.parametrize("builder", _BUILDERS)
@pytest.mark.parametrize(
    "event_id",
    [
        "1234",
        "0x1234",
        "0x" + "gg" * 29,
        _EVENT_ID + "000001",
        _EVENT_ID + "000100",
        _EVENT_ID + "010000",
        _EVENT_ID + "00",
        "0x01" + _EVENT_ID[4:],
        "0x02" + "11" * 16 + "0001" + "00" * 10,
        "0x02" + "11" * 16 + "0000" + "00" * 10,
        "0x02" + "11" * 16 + "0003" + "01" + "00" * 9,
    ],
)
def test_router_neg_risk_rejects_invalid_event(
    builder: Callable[..., TransactionCall], event_id: str
) -> None:
    with pytest.raises(UserInputError):
        builder(router=_ROUTER, protocol_event_id=event_id, amount=1)


@pytest.mark.parametrize("condition_index", [-1, 4, 65536, True, 1.5, "0"])
def test_router_convert_rejects_invalid_index(condition_index: Any) -> None:
    with pytest.raises(UserInputError):
        router_convert_call(
            router=_ROUTER, protocol_event_id=_EVENT_ID, condition_index=condition_index, amount=1
        )


def test_router_convert_preserves_resolution_chain_and_accepts_other_at_uint16_boundary() -> None:
    event_id = "0x02" + "11" * 16 + "ffff" + "00" * 8 + "0001"
    call = router_convert_call(
        router=_ROUTER, protocol_event_id=event_id, condition_index=65535, amount=MAX_UINT256
    )
    assert call.data[10:74] == event_id[2:] + "000000"
    assert call.data[74:138] == f"{65535:064x}"
    assert call.data[138:] == "ff" * 32


@pytest.mark.parametrize("suffix", ["", "00"])
@pytest.mark.parametrize("condition_index", [0, 2, 3, 65535])
def test_neg_risk_condition_derives_event_and_index(suffix: str, condition_index: int) -> None:
    arity = max(3, condition_index)
    protocol_event_id = "0x02" + "ab" * 16 + f"{arity:04x}" + "00" * 8 + "00ff"
    condition_id = "0x" + (protocol_event_id[2:] + f"{condition_index:04x}" + suffix).upper()
    assert parse_neg_risk_condition_id(condition_id) == (protocol_event_id, condition_index)


@pytest.mark.parametrize(
    "condition_id",
    [
        _EVENT_ID,
        "123",
        "0x01" + _EVENT_ID[4:] + "0002",
        "0x03" + _EVENT_ID[4:] + "0002",
        "0x" + "11" * 32,
        _EVENT_ID + "000201",
        "0x02" + "11" * 16 + "0003" + "00" * 7 + "01" + "0000" + "0002",
        "0x02" + "11" * 16 + "0001" + "00" * 10 + "0000",
        _EVENT_ID + "0004",
        _EVENT_ID + "000g",
        " " + _EVENT_ID + "0002",
        _EVENT_ID + "00  ",
        None,
        123,
    ],
)
def test_neg_risk_condition_rejects_invalid_identity(condition_id: Any) -> None:
    with pytest.raises(UserInputError):
        parse_neg_risk_condition_id(condition_id)
