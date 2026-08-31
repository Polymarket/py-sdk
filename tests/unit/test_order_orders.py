from polymarket._internal.actions.orders.orders import (
    create_signed_order,
    create_unsigned_order,
)
from polymarket._internal.actions.orders.types import BYTES32_ZERO, OrderDraft
from polymarket.models.types import TokenId
from polymarket.types import EvmAddress, HexString

SIGNER = EvmAddress("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")
WALLET = EvmAddress("0x7754536ecd85c00b2e0cf9c1aa679340d8550756")
DEPOSIT_WALLET = EvmAddress("0x57ffbc34de23124faeb8387fcd689d314e57accd")
EXCHANGE = EvmAddress("0xE111180000d2663C0091e4f400237545B87B996B")


def _draft(**overrides: object) -> OrderDraft:
    base: dict[str, object] = {
        "chain_id": 137,
        "exchange_address": EXCHANGE,
        "expiration": 0,
        "funder_address": WALLET,
        "offered_amount": 1_000_000,
        "order_type": "GTC",
        "side": "BUY",
        "signer": SIGNER,
        "requested_amount": 500_000,
        "asset_id": TokenId("8501497"),
    }
    base.update(overrides)
    return OrderDraft(**base)  # type: ignore[arg-type]


def test_create_unsigned_order_routes_signer_to_signer_address_for_eoa() -> None:
    order = create_unsigned_order(_draft(), wallet=SIGNER, wallet_type="EOA")
    assert order.signer == SIGNER
    assert order.signature_type == 0


def test_create_unsigned_order_routes_signer_to_signer_address_for_poly_proxy() -> None:
    order = create_unsigned_order(_draft(), wallet=WALLET, wallet_type="POLY_PROXY")
    assert order.signer == SIGNER
    assert order.signature_type == 1


def test_create_unsigned_order_routes_signer_to_wallet_for_deposit_wallet() -> None:
    order = create_unsigned_order(_draft(), wallet=DEPOSIT_WALLET, wallet_type="DEPOSIT_WALLET")
    assert order.signer == DEPOSIT_WALLET
    assert order.signature_type == 3


def test_create_unsigned_order_sets_zero_bytes_for_metadata_and_builder() -> None:
    order = create_unsigned_order(_draft(), wallet=WALLET, wallet_type="POLY_PROXY")
    assert order.metadata == BYTES32_ZERO
    assert order.builder == BYTES32_ZERO


def test_create_unsigned_order_propagates_draft_fields() -> None:
    order = create_unsigned_order(_draft(), wallet=WALLET, wallet_type="POLY_PROXY")
    assert order.chain_id == 137
    assert order.exchange_address == EXCHANGE
    assert order.maker == WALLET
    assert order.maker_amount == 1_000_000
    assert order.taker_amount == 500_000
    assert order.side == "BUY"
    assert order.token_id == TokenId("8501497")


def test_create_unsigned_order_generates_53_bit_salt() -> None:
    order = create_unsigned_order(_draft(), wallet=WALLET, wallet_type="POLY_PROXY")
    assert 0 <= order.salt < (1 << 53)


def test_create_unsigned_order_generates_distinct_salts() -> None:
    seen = {
        create_unsigned_order(_draft(), wallet=WALLET, wallet_type="POLY_PROXY").salt
        for _ in range(50)
    }
    assert len(seen) > 1


def test_create_signed_order_carries_signature_and_post_only_flag() -> None:
    unsigned = create_unsigned_order(_draft(), wallet=WALLET, wallet_type="POLY_PROXY")
    signed = create_signed_order(unsigned, HexString("0xabc"), post_only=True)
    assert signed.signature == "0xabc"
    assert signed.post_only is True
    assert signed.salt == unsigned.salt
    assert signed.maker == unsigned.maker
    assert signed.signer == unsigned.signer
