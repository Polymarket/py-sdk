from decimal import Decimal
from types import SimpleNamespace

import pytest

# pyright: reportPrivateUsage=false
from polymarket._internal.actions.relayer.positions import (
    _derive_binary_position_amounts,
    calculate_max_merge_amount,
    canonicalize_combo_legs,
    decode_combo_outcome_position_id,
    derive_combo_position_context,
    expect_binary_positions,
    expect_negative_risk_flag,
    normalize_market_position_context,
    resolve_binary_positions_condition_id,
    resolve_merge_amount,
)
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.data.portfolio import Position
from polymarket.types import EvmAddress

_CONDITION_ID = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
_COMBO_CONDITION_ID = "0x032def24bfb0c5c57fb236fac08b94236a0000000000000000000000000000"
_ADDRESS = EvmAddress("0x0000000000000000000000000000000000000001")


def _pos(
    *,
    outcome_index: int | None,
    size: Decimal | None = None,
    negative_risk: bool | None = False,
    condition_id: str = _CONDITION_ID,
) -> Position:
    return Position.parse_response(
        {
            "conditionId": condition_id,
            "outcomeIndex": outcome_index,
            "size": str(size) if size is not None else None,
            "negativeRisk": negative_risk,
        }
    )


def test_expect_binary_positions_returns_yes_no_tuple() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("10.5"))
    no_pos = _pos(outcome_index=1, size=Decimal("5.0"))
    yes, no = expect_binary_positions([yes_pos, no_pos])
    assert yes is yes_pos
    assert no is no_pos


@pytest.mark.parametrize(
    ("yes_position_id", "no_position_id", "message"),
    [
        ("101", None, "Incomplete market position IDs"),
        (None, None, "Missing tradeable outcome IDs"),
    ],
)
def test_normalize_market_position_context_distinguishes_v2_id_failures(
    yes_position_id: str | None,
    no_position_id: str | None,
    message: str,
) -> None:
    market = SimpleNamespace(
        id="1",
        condition_id=_CONDITION_ID,
        state=SimpleNamespace(neg_risk=None),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id=None, position_id=yes_position_id),
            no=SimpleNamespace(token_id=None, position_id=no_position_id),
        ),
    )

    with pytest.raises(UnexpectedResponseError, match=message):
        normalize_market_position_context(
            market,  # type: ignore[arg-type]
            context="test market",
            collateral_adapter=_ADDRESS,
            neg_risk_collateral_adapter=_ADDRESS,
            conditional_tokens=_ADDRESS,
            neg_risk_adapter=_ADDRESS,
            position_manager=_ADDRESS,
        )


def test_expect_binary_positions_handles_only_yes() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("10"))
    yes, no = expect_binary_positions([yes_pos])
    assert yes is yes_pos
    assert no is None


def test_expect_binary_positions_handles_only_no() -> None:
    no_pos = _pos(outcome_index=1, size=Decimal("10"))
    yes, no = expect_binary_positions([no_pos])
    assert yes is None
    assert no is no_pos


def test_expect_binary_positions_rejects_empty() -> None:
    with pytest.raises(UserInputError, match="no positions"):
        expect_binary_positions([])


def test_expect_binary_positions_rejects_too_many() -> None:
    with pytest.raises(UnexpectedResponseError, match="at most two"):
        expect_binary_positions(
            [
                _pos(outcome_index=0),
                _pos(outcome_index=1),
                _pos(outcome_index=0),
            ]
        )


def test_expect_binary_positions_rejects_invalid_outcome_index() -> None:
    with pytest.raises(UnexpectedResponseError, match="Unexpected outcomeIndex"):
        expect_binary_positions([_pos(outcome_index=2)])


def test_expect_binary_positions_rejects_duplicate_yes() -> None:
    with pytest.raises(UnexpectedResponseError, match="Duplicate YES"):
        expect_binary_positions([_pos(outcome_index=0), _pos(outcome_index=0)])


def test_expect_negative_risk_flag_returns_flag() -> None:
    yes_pos = _pos(outcome_index=0, negative_risk=True)
    no_pos = _pos(outcome_index=1, negative_risk=True)
    assert expect_negative_risk_flag((yes_pos, no_pos)) is True


def test_expect_negative_risk_flag_works_with_single_position() -> None:
    yes_pos = _pos(outcome_index=0, negative_risk=False)
    assert expect_negative_risk_flag((yes_pos, None)) is False


def test_expect_negative_risk_flag_rejects_missing_flag() -> None:
    yes_pos = _pos(outcome_index=0, negative_risk=None)
    with pytest.raises(UnexpectedResponseError, match="Missing negativeRisk"):
        expect_negative_risk_flag((yes_pos, None))


def test_expect_negative_risk_flag_rejects_mixed_flags() -> None:
    yes_pos = _pos(outcome_index=0, negative_risk=True)
    no_pos = _pos(outcome_index=1, negative_risk=False)
    with pytest.raises(UnexpectedResponseError, match="Mixed negativeRisk"):
        expect_negative_risk_flag((yes_pos, no_pos))


def test_derive_binary_position_amounts_converts_to_base_units() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("111.0"))
    no_pos = _pos(outcome_index=1, size=Decimal("0"))
    amounts = _derive_binary_position_amounts((yes_pos, no_pos))
    assert amounts == (111_000_000, 0)


def test_derive_binary_position_amounts_none_size_is_zero() -> None:
    yes_pos = _pos(outcome_index=0, size=None)
    no_pos = _pos(outcome_index=1, size=Decimal("3.5"))
    amounts = _derive_binary_position_amounts((yes_pos, no_pos))
    assert amounts == (0, 3_500_000)


def test_derive_binary_position_amounts_missing_outcome_is_zero() -> None:
    no_pos = _pos(outcome_index=1, size=Decimal("3.5"))
    amounts = _derive_binary_position_amounts((None, no_pos))
    assert amounts == (0, 3_500_000)


def test_calculate_max_merge_amount_takes_min() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("100"))
    no_pos = _pos(outcome_index=1, size=Decimal("60"))
    assert calculate_max_merge_amount((yes_pos, no_pos)) == 60_000_000


def test_calculate_max_merge_amount_zero_when_single_side() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("100"))
    assert calculate_max_merge_amount((yes_pos, None)) == 0


def test_resolve_merge_amount_max_returns_max() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("100"))
    no_pos = _pos(outcome_index=1, size=Decimal("60"))
    assert resolve_merge_amount((yes_pos, no_pos), "max") == 60_000_000


def test_resolve_merge_amount_accepts_value_below_max() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("100"))
    no_pos = _pos(outcome_index=1, size=Decimal("60"))
    assert resolve_merge_amount((yes_pos, no_pos), 30_000_000) == 30_000_000


def test_resolve_merge_amount_rejects_above_max() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("100"))
    no_pos = _pos(outcome_index=1, size=Decimal("60"))
    with pytest.raises(UserInputError, match="exceeds the maximum"):
        resolve_merge_amount((yes_pos, no_pos), 70_000_000)


def test_resolve_merge_amount_rejects_zero() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("100"))
    no_pos = _pos(outcome_index=1, size=Decimal("60"))
    with pytest.raises(UserInputError, match="positive"):
        resolve_merge_amount((yes_pos, no_pos), 0)


def test_resolve_merge_amount_rejects_when_no_complementary() -> None:
    yes_pos = _pos(outcome_index=0, size=Decimal("100"))
    with pytest.raises(UserInputError, match="no complementary"):
        resolve_merge_amount((yes_pos, None), "max")


def test_resolve_binary_positions_condition_id_returns_first_present() -> None:
    no_pos = _pos(outcome_index=1, condition_id=_CONDITION_ID)
    assert resolve_binary_positions_condition_id((None, no_pos)) == _CONDITION_ID


def test_derive_binary_position_amounts_rejects_non_finite_size() -> None:
    yes_pos = Position.model_construct(
        condition_id=_CONDITION_ID,
        outcome_index=0,
        size=Decimal("NaN"),
        negative_risk=True,
    )
    no_pos = _pos(outcome_index=1, size=Decimal("0"), negative_risk=True)
    with pytest.raises(UnexpectedResponseError, match="finite number"):
        _derive_binary_position_amounts((yes_pos, no_pos))


def test_derive_binary_position_amounts_rejects_infinity() -> None:
    yes_pos = Position.model_construct(
        condition_id=_CONDITION_ID,
        outcome_index=0,
        size=Decimal("Infinity"),
        negative_risk=True,
    )
    no_pos = _pos(outcome_index=1, size=Decimal("0"), negative_risk=True)
    with pytest.raises(UnexpectedResponseError, match="finite number"):
        _derive_binary_position_amounts((yes_pos, no_pos))


def test_canonicalize_combo_legs_sorts_unordered_legs() -> None:
    legs = canonicalize_combo_legs([_leg_position(2, 1), _leg_position(1, 0)])

    assert tuple(str(leg) for leg in legs) == (_leg_position(1, 0), _leg_position(2, 1))


def test_canonicalize_combo_legs_rejects_both_outcomes() -> None:
    with pytest.raises(UserInputError, match="both outcomes"):
        canonicalize_combo_legs([_leg_position(1, 0), _leg_position(1, 1)])


def test_derive_combo_position_context_matches_ts_golden() -> None:
    context = derive_combo_position_context((int(_leg_position(1, 0)), int(_leg_position(2, 1))))

    assert context.condition_id == _COMBO_CONDITION_ID
    assert context.position_ids == (
        _combo_position(_COMBO_CONDITION_ID, 0),
        _combo_position(_COMBO_CONDITION_ID, 1),
    )


def test_decode_combo_outcome_position_id() -> None:
    decoded = decode_combo_outcome_position_id(_combo_position(_COMBO_CONDITION_ID, 1))

    assert decoded.condition_id == _COMBO_CONDITION_ID
    assert decoded.outcome_index == 1


def test_deprecated_combo_decoder_accepts_any_v2_module() -> None:
    decoded = decode_combo_outcome_position_id(_leg_position(1, 0))

    assert decoded.condition_id == f"0x01{'00' * 29}01"
    assert decoded.outcome_index == 0


def _leg_position(marker: int, outcome: int) -> str:
    raw = bytearray(32)
    raw[0] = 1
    raw[30] = marker
    raw[31] = outcome
    return str(int("0x" + raw.hex(), 16))


def _combo_position(condition_id: str, outcome: int) -> str:
    return str(int(f"{condition_id}{outcome:02x}", 16))
