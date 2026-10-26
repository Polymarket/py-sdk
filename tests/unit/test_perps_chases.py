"""Chase input, compact signing and response boundaries."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polymarket._internal.actions.perps.chases import build_cancel_chase_op, build_create_chase_op
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.perps.chases import PerpsChase


def test_chase_compact_order_and_precision() -> None:
    op, body = build_create_chase_op(instrument_id=1, side="BUY", quantity="1.000000000000000001")
    assert op == [
        "createChase",
        [1, True, "1.000000000000000001", None, None, None, True, False, None],
    ]
    assert body == {
        "type": "createChase",
        "args": {"iid": 1, "buy": True, "qty": "1.000000000000000001", "po": True, "ro": False},
    }
    op, body = build_create_chase_op(
        instrument_id=1,
        side="SELL",
        quantity=1e-8,
        limit_price="1.000000000000000001",
        max_distance="0",
        max_distance_bps=1000,
        post_only=False,
        reduce_only=True,
        client_order_id="a" * 32,
    )
    assert op == [
        "createChase",
        [1, False, "0.00000001", "1.000000000000000001", "0", 1000, False, True, "a" * 32],
    ]
    assert build_cancel_chase_op(2**53 - 1) == (
        ["cancelChase", [2**53 - 1]],
        {"type": "cancelChase", "args": {"chid": 2**53 - 1}},
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"quantity": "0"},
        {"quantity": "NaN"},
        {"quantity": "1e-29"},
        {"quantity": "79228162514264337593543950336"},
        {"limit_price": "-1"},
        {"max_distance": "1", "max_distance_bps": 5},
        {"max_distance_bps": 0},
        {"max_distance_bps": 1001},
        {"max_distance_bps": True},
        {"post_only": 1},
        {"instrument_id": 2**32},
        {"side": "buy"},
        {"client_order_id": "a" * 33},
    ],
)
def test_invalid_chase_input(invalid: dict[str, object]) -> None:
    with pytest.raises(UserInputError):
        build_create_chase_op(**({"instrument_id": 1, "side": "BUY", "quantity": "1"} | invalid))  # type: ignore[arg-type]


def test_chase_models() -> None:
    raw = dict(
        chid=2**53 - 1,
        iid=1,
        buy=True,
        qty="1.000000000000000001",
        fill="0",
        lim="0",
        max_dist="0",
        max_dist_bps=50,
        po=True,
        ro=False,
        reference_price="100.000000000000000001",
        reprices=3,
        post_only_rejections=0,
        cts=1767225600000,
        oid=42,
    )
    chase = PerpsChase.parse_response(raw)
    assert chase.quantity == Decimal("1.000000000000000001")
    assert chase.reference_price == Decimal("100.000000000000000001")
    assert chase.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert chase.order_id == 42
    assert chase.chase_id == 2**53 - 1
    for invalid in [0, -1, 1.5, True, 2**53]:
        with pytest.raises(UnexpectedResponseError):
            PerpsChase.parse_response(raw | {"chid": invalid})


def test_chase_signing_vectors() -> None:
    from polymarket._internal.actions.perps.signing import hash_perps_op

    assert (
        hash_perps_op(
            ["createChase", [1, True, "1.000000000000000001", None, None, None, True, False, None]]
        )
        == "0x49bb16d14842595245b19ddc957a9d56fe389bebbb419a8ba384ddcefbbdc100"
    )
    assert (
        hash_perps_op(
            [
                "createChase",
                [1, False, "0.00000001", "1.000000000000000001", "0", 1000, False, True, "a" * 32],
            ]
        )
        == "0xcaed1e7545bd77ee7256f65e289acb851dafca4c3d52cee69cc999f31042f7b6"
    )
    assert (
        hash_perps_op(["cancelChase", [2**53 - 1]])
        == "0x3b3837a3a14b632e535a82702b5580b38fe6a54b3414d1da739e2ac520e76592"
    )
