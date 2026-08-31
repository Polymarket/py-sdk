import pytest

from polymarket._internal.actions.clob import build_midpoint_request
from polymarket._internal.actions.orders.context import resolve_order_exchange_address
from polymarket._internal.actions.orders.orders import create_unsigned_order
from polymarket._internal.actions.orders.typed_data import build_order_typed_data
from polymarket._internal.actions.orders.types import OrderDraft
from polymarket._internal.actions.relayer.positions import derive_combo_outcome_position_ids
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket._internal.protocol import decode_v2_outcome_position_id, is_v2_position_id
from polymarket.errors import UserInputError
from polymarket.models.gamma import Market
from polymarket.models.types import PositionId
from polymarket.types import EvmAddress

_ZERO_ADDRESS = EvmAddress("0x0000000000000000000000000000000000000000")
_BINARY_CONDITION_ID = "0x01" + "00" * 30
_YES_POSITION_ID = PositionId(str(int(_BINARY_CONDITION_ID + "00", 16)))


def test_protocol_v2_position_ids_use_reserved_bit_namespace() -> None:
    assert is_v2_position_id(_YES_POSITION_ID)
    assert not is_v2_position_id(str(1 << 40))
    assert not is_v2_position_id("not-an-id")
    assert not is_v2_position_id("1_0")


def test_protocol_v2_position_decoder_supports_all_v2_modules() -> None:
    for module_id in (1, 2, 3):
        condition_id = f"0x{module_id:02x}" + "ab" * 30
        position_id = PositionId(str(int(condition_id + "01", 16)))
        decoded = decode_v2_outcome_position_id(position_id)
        assert decoded.condition_id == condition_id
        assert decoded.outcome_index == 1


def test_v2_outcome_derivation_rejects_bytes32_condition_id() -> None:
    with pytest.raises(UserInputError, match="31-byte"):
        derive_combo_outcome_position_ids("0x" + "ab" * 32)


def test_gamma_market_exposes_position_id_per_outcome() -> None:
    market = Market.parse_response(
        {
            "id": "1",
            "conditionId": _BINARY_CONDITION_ID,
            "outcomes": ["Yes", "No"],
            "outcomePrices": ["0.6", "0.4"],
            "clobTokenIds": [],
            "positionIds": ["11", "12"],
        }
    )
    assert market.outcomes.yes.position_id == "11"
    assert market.outcomes.no.position_id == "12"
    assert market.outcomes.yes.token_id is None


def test_clob_read_accepts_asset_id_and_preserves_wire_parameter() -> None:
    assert build_midpoint_request(asset_id="123") == ("/midpoint", {"token_id": "123"})
    try:
        build_midpoint_request(asset_id="123", token_id="456")
    except UserInputError as error:
        assert "mutually exclusive" in str(error)
    else:
        raise AssertionError("expected mutually exclusive identifier error")


def test_v2_order_uses_exchange_v3_and_eip712_version_3() -> None:
    exchange = resolve_order_exchange_address(
        PRODUCTION_CONFIG, asset_id=_YES_POSITION_ID, neg_risk=False
    )
    draft = OrderDraft(
        chain_id=PRODUCTION_CONFIG.chain_id,
        exchange_address=exchange,
        expiration=0,
        funder_address=_ZERO_ADDRESS,
        offered_amount=1,
        order_type="GTC",
        side="BUY",
        signer=_ZERO_ADDRESS,
        requested_amount=2,
        asset_id=_YES_POSITION_ID,
    )
    unsigned = create_unsigned_order(draft, wallet=_ZERO_ADDRESS, wallet_type="EOA")
    typed_data = build_order_typed_data(unsigned)

    assert exchange == PRODUCTION_CONFIG.exchange_v3
    assert unsigned.protocol_version == "3"
    assert typed_data["domain"]["version"] == "3"
    assert typed_data["domain"]["verifyingContract"] == PRODUCTION_CONFIG.exchange_v3
