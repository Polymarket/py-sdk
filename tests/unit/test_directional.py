from decimal import Decimal
from typing import Any

import pytest
from data_v2_samples import sample

from polymarket import (
    DirectionalInstrumentKind,
    DirectionalSide,
    ThresholdSide,
    UserInputError,
    decode_position_id,
    derive_directional_bucket_positions,
    derive_directional_threshold_positions,
    to_market_condition_id,
)
from polymarket._internal.actions.relayer.directional import (
    directional_pairs_from_balances,
    resolve_directional_amount,
)
from polymarket._internal.directional import (
    bucket_yes_ids,
    normalize_directional_event_id,
    threshold_basket_ids,
    validate_directional_pair,
)
from polymarket._internal.protocol import decode_v2_outcome_position_id, is_v2_position_id
from polymarket.calls import (
    router_compose_threshold_call,
    router_convert_call,
    router_decompose_threshold_call,
    router_horizontal_merge_call,
    router_horizontal_split_call,
    router_merge_directional_call,
    router_split_directional_call,
)
from polymarket.errors import UnexpectedResponseError
from polymarket.models.data.activity import (
    DirectionalMergeActivity,
    DirectionalSplitActivity,
    ThresholdComposeActivity,
    ThresholdDecomposeActivity,
    parse_activity,
)
from polymarket.types import EvmAddress

EVENT = "0x0400112233445566778899aabbccddeeff000400000000000000000102"
ROUTER = EvmAddress("0x12121212006e4CD160D18e3f00711DA5c3372600")


def test_identity_round_trip_and_unordered_pair() -> None:
    low = derive_directional_threshold_positions(event_id=EVENT, line=1)
    high = derive_directional_threshold_positions(event_id=EVENT + "000000", line=3)
    above = decode_position_id(low.above_position_id)
    assert (
        above.module_id,
        above.event_id,
        above.bucket_count,
        above.kind,
        above.index,
        above.side,
    ) == (
        4,
        EVENT,
        4,
        DirectionalInstrumentKind.LINE,
        1,
        DirectionalSide.ABOVE,
    )
    assert validate_directional_pair(
        low.above_position_id, high.below_position_id
    ) == validate_directional_pair(high.below_position_id, low.above_position_id)
    for index in (0, 3, 4):
        bucket = derive_directional_bucket_positions(event_id=EVENT, bucket_index=index)
        decoded = decode_position_id(bucket.no_position_id)
        assert decoded.index == index and decoded.side == DirectionalSide.NO
        assert decoded.kind == (
            DirectionalInstrumentKind.VOID if index == 4 else DirectionalInstrumentKind.BUCKET
        )
        assert is_v2_position_id(bucket.yes_position_id)
        assert (
            decode_v2_outcome_position_id(bucket.no_position_id).condition_id == bucket.condition_id
        )
        assert to_market_condition_id(bucket.condition_id) == bucket.condition_id + "00"


def test_codec_rejects_dirty_padding_reserved_bits_and_illegal_descriptors() -> None:
    for event in [
        EVENT + "000001",
        "0x02" + EVENT[4:],
        EVENT[:40] + "0000000000000001" + EVENT[56:],
        EVENT[:36] + "0001" + EVENT[40:],
    ]:
        with pytest.raises(UserInputError):
            normalize_directional_event_id(event)
    for descriptor in ("8000", "8004", "0005"):
        with pytest.raises(UserInputError):
            decode_position_id(str(int(EVENT + descriptor + "00", 16)))
    for position in ("0xff", "01", "-1", str(1 << 256), str(int(EVENT + "800102", 16))):
        with pytest.raises(UserInputError):
            decode_position_id(position)
    low = derive_directional_threshold_positions(event_id=EVENT, line=1)
    high = derive_directional_threshold_positions(event_id=EVENT, line=3)
    other = derive_directional_threshold_positions(event_id="0x040111" + EVENT[8:], line=3)
    for a, b in [
        (low.above_position_id, low.below_position_id),
        (high.above_position_id, low.below_position_id),
        (low.above_position_id, high.above_position_id),
        (low.above_position_id, other.below_position_id),
    ]:
        with pytest.raises(UserInputError):
            validate_directional_pair(a, b)


def test_void_baskets_and_balance_limiting_assets() -> None:
    event = normalize_directional_event_id(EVENT)
    assert [decode_position_id(p).index for p in bucket_yes_ids(event, 0, 5)] == [0, 1, 2, 3, 4]
    assert [decode_position_id(p).index for p in threshold_basket_ids(event, 2, "above")] == [2, 3]
    assert [decode_position_id(p).index for p in threshold_basket_ids(event, 2, "below")] == [
        0,
        1,
        4,
    ]
    assert (
        resolve_directional_amount(
            ["bucket 1", "bucket 2", "pUSD"], [3_000_000, 2_000_000, 500_000], "max"
        )
        == 500_000
    )
    with pytest.raises(UserInputError, match="pUSD"):
        resolve_directional_amount(["bucket 1", "pUSD"], [1_000_000, 500_000], 1_000_000)
    with pytest.raises(UserInputError, match="bucket 2"):
        resolve_directional_amount(["bucket 1", "bucket 2"], [1_000_000, 0], "max")
    bad_amounts: tuple[Any, ...] = (True, 1.5, 0, -1, 1 << 256, None, "1")
    for amount in bad_amounts:
        with pytest.raises(UserInputError):
            resolve_directional_amount(["wing"], [1_000_000], amount)


def test_pairs_do_not_cross_events_or_reverse_the_wings() -> None:
    low = derive_directional_threshold_positions(event_id=EVENT, line=1)
    high = derive_directional_threshold_positions(event_id=EVENT, line=3)
    other = derive_directional_threshold_positions(event_id="0x040111" + EVENT[8:], line=3)
    pairs = directional_pairs_from_balances(
        [
            low.above_position_id,
            low.below_position_id,
            high.above_position_id,
            high.below_position_id,
            other.below_position_id,
        ],
        [5, 9, 9, 3, 9],
    )
    assert len(pairs) == 1
    assert (pairs[0].low_line, pairs[0].high_line, pairs[0].amount, pairs[0].expected_pusd) == (
        1,
        3,
        3,
        3,
    )


def test_router_vectors_match_compiled_typescript_abi() -> None:
    calls = [
        ("0x40657b52", router_horizontal_split_call(router=ROUTER, event_id=EVENT, amount=1)),
        ("0x24f24944", router_horizontal_merge_call(router=ROUTER, event_id=EVENT, amount=1)),
        (
            "0x9380f1c8",
            router_convert_call(router=ROUTER, event_id=EVENT, bucket_index=4, amount=1),
        ),
        (
            "0xc66feac2",
            router_compose_threshold_call(
                router=ROUTER, event_id=EVENT, line=2, side="above", amount=1
            ),
        ),
        (
            "0xb34170d6",
            router_decompose_threshold_call(
                router=ROUTER, event_id=EVENT, line=2, side="below", amount=1
            ),
        ),
        (
            "0x77b72427",
            router_merge_directional_call(
                router=ROUTER, event_id=EVENT, low_line=1, high_line=3, amount=(1 << 256) - 1
            ),
        ),
        (
            "0xba860eec",
            router_split_directional_call(
                router=ROUTER, event_id=EVENT, low_line=1, high_line=3, amount=1
            ),
        ),
    ]
    for selector, call in calls:
        assert call.to == ROUTER and call.data[:10] == selector
        assert call.data[10:74] == EVENT[2:].ljust(64, "0")
    assert calls[-2][1].data[-64:] == "f" * 64


def test_directional_activities_preserve_economics_with_missing_metadata() -> None:
    base: dict[str, Any] = {
        **sample("activity")[0],
        "title": "",
        "slug": "",
        "event_slug": "",
        "outcome_index": 999,
        "size": "12.5",
        "usdc_size": "12.5",
    }
    for kind, cls in [
        ("DIRECTIONAL_MERGE", DirectionalMergeActivity),
        ("DIRECTIONAL_SPLIT", DirectionalSplitActivity),
    ]:
        row = parse_activity({**base, "type": kind, "condition_id": EVENT})
        assert isinstance(row, cls)
        assert isinstance(row, (DirectionalMergeActivity, DirectionalSplitActivity))
        assert row.event_id == EVENT and row.pairs == Decimal("12.5")
        assert row.amount == Decimal("12.5") and row.title is None
    for kind, cls in [
        ("THRESHOLD_COMPOSE", ThresholdComposeActivity),
        ("THRESHOLD_DECOMPOSE", ThresholdDecomposeActivity),
    ]:
        for outcome, side in [(0, ThresholdSide.ABOVE), (1, ThresholdSide.BELOW)]:
            row = parse_activity(
                {
                    **base,
                    "type": kind,
                    "condition_id": EVENT + "8002",
                    "outcome_index": outcome,
                    "usdc_size": 0,
                }
            )
            assert isinstance(row, cls)
            assert isinstance(row, (ThresholdComposeActivity, ThresholdDecomposeActivity))
            assert (row.event_id, row.line, row.side, row.shares, row.amount) == (
                EVENT,
                2,
                side,
                Decimal("12.5"),
                Decimal(0),
            )
        with pytest.raises(UnexpectedResponseError):
            parse_activity({**base, "type": kind, "condition_id": EVENT + "0002"})
