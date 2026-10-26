"""TWAP contract regressions: no network or live trading."""

from decimal import Decimal
from typing import Any, cast

import pytest

from polymarket._internal.actions.perps.twaps import create_twap_op
from polymarket.errors import UserInputError
from polymarket.models.perps.twaps import PerpsTwap


def test_twap_signing_defaults_and_precision():
    op, body = create_twap_op(
        instrument_id=1, side="BUY", quantity=Decimal("1.000000000000000001"), duration_ms=300000
    )
    assert op == [
        "createTwap",
        [1, True, "1.000000000000000001", 300000, None, False, 0, None, None, False, None],
    ]
    assert body == {
        "type": "createTwap",
        "args": {
            "iid": 1,
            "buy": True,
            "qty": "1.000000000000000001",
            "dur": 300000,
            "rnd": False,
            "slip_bps": 0,
            "ro": False,
        },
    }


@pytest.mark.parametrize(
    "options",
    [
        {"interval_ms": 31000},
        {"duration_ms": 299999},
        {"randomize": 1},
        {"slippage_bps": 10001},
        {"min_price": "1.000000000000000002", "max_price": "1.000000000000000001"},
        {"quantity": "0"},
    ],
)
def test_twap_rejects_invalid_complete_input(options: dict[str, Any]):
    args: dict[str, Any] = dict(instrument_id=1, side="BUY", quantity="1", duration_ms=300000)
    args.update(options)
    with pytest.raises(UserInputError):
        create_twap_op(**args)


def test_twap_response_types_and_aliases():
    run = PerpsTwap.parse_response(
        dict(
            twid=9007199254740991,
            iid=1,
            buy=True,
            qty="1.000000000000000001",
            fill="0.1",
            dur=300000,
            ivl=30000,
            rnd=False,
            slip_bps=0,
            min_px="0",
            max_px="0",
            ro=False,
            st="paused",
            slices=1,
            slice_count=10,
            sts=1767225600000,
            ets=1767225900000,
            cts=1767225600000,
        )
    )
    assert run.twap_id == 9007199254740991
    assert run.quantity == Decimal("1.000000000000000001")
    assert run.side == "BUY"
    assert run.started_at.year == 2026


def test_twap_default_signing_bytes():
    import msgpack  # pyright: ignore[reportMissingTypeStubs]

    from polymarket._internal.actions.perps.signing import compact_signable_value, hash_perps_op

    op, _ = create_twap_op(
        instrument_id=1, side="BUY", quantity="1.000000000000000001", duration_ms=300000
    )
    packed = cast(bytes, msgpack.packb(compact_signable_value(op)))  # pyright: ignore[reportUnknownMemberType]
    assert packed.hex() == (
        "92aa637265617465547761709701c3b4312e303030303030303030303030303030303031ce000493e0c200c2"
    )
    assert hash_perps_op(op) == "0x68225979ea9c0dda2641be3e25f940f6d515138c2aeb54320ea2be8e5a0b5e25"


def test_twap_full_options_and_decimal_normalization():
    op, body = create_twap_op(
        instrument_id=5,
        side="SELL",
        quantity="1e-8",
        duration_ms=3600000,
        interval_ms=60000,
        randomize=True,
        slippage_bps=10000,
        min_price="1.000000000000000001",
        max_price="1.000000000000000002",
        reduce_only=True,
        client_order_id="a" * 32,
    )
    assert op == [
        "createTwap",
        [
            5,
            False,
            "0.00000001",
            3600000,
            60000,
            True,
            10000,
            "1.000000000000000001",
            "1.000000000000000002",
            True,
            "a" * 32,
        ],
    ]
    assert body["args"]["qty"] == "0.00000001"


@pytest.mark.parametrize(
    "payload", [{"status": "ok", "twid": 1}, {"status": "ok", "twid": 2**53, "ts": 1767225600000}]
)
def test_twap_malformed_receipts_raise_sdk_error(payload: dict[str, Any]):
    from polymarket.errors import UnexpectedResponseError
    from polymarket.models.perps.twaps import PerpsTwapAccepted

    with pytest.raises(UnexpectedResponseError):
        PerpsTwapAccepted.parse_response(payload)
