import dataclasses
from typing import cast

from eth_abi.abi import decode as abi_decode

from polymarket._internal.actions.orders.typed_data import (
    build_order_signature,
    build_order_typed_data,
)
from polymarket._internal.actions.orders.types import BYTES32_ZERO, UnsignedOrder
from polymarket._internal.wallet import wrap_deposit_wallet_signature
from polymarket.models.types import TokenId
from polymarket.types import EvmAddress, HexString

EXCHANGE_ADDRESS = EvmAddress("0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e")
DEPOSIT_WALLET_ADDRESS = EvmAddress("0x57ffbc34de23124faeb8387fcd689d314e57accd")
SESSION_SIGNER_ADDRESS = EvmAddress("0x000000000000000000000000000000000000dEaD")
EVM_SIGNATURE = HexString(
    "0x111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111b"
)
ORDER_TYPE_STRING = (
    "Order(uint256 salt,address maker,address signer,uint256 tokenId,"
    "uint256 makerAmount,uint256 takerAmount,uint8 side,uint8 signatureType,"
    "uint256 timestamp,bytes32 metadata,bytes32 builder)"
)
SESSION_SIGNER_MAGIC_BYTES = bytes.fromhex("6492" * 16)


def _fixture(signature_type: int) -> UnsignedOrder:
    return UnsignedOrder(
        builder=BYTES32_ZERO,
        chain_id=137,
        exchange_address=EXCHANGE_ADDRESS,
        expiration=0,
        maker=DEPOSIT_WALLET_ADDRESS,
        maker_amount=1_000_000,
        metadata=BYTES32_ZERO,
        order_type="GTC",
        salt=1,
        side="BUY",
        signature_type=signature_type,
        signer=DEPOSIT_WALLET_ADDRESS,
        taker_amount=500_000,
        timestamp=0,
        token_id=TokenId("1"),
    )


def test_build_order_typed_data_uses_order_primary_type_for_non_1271() -> None:
    payload = build_order_typed_data(_fixture(signature_type=0))
    assert payload["primaryType"] == "Order"
    assert payload["domain"] == {
        "name": "Polymarket CTF Exchange",
        "version": "2",
        "chainId": 137,
        "verifyingContract": EXCHANGE_ADDRESS,
    }
    assert "EIP712Domain" in payload["types"]
    assert "Order" in payload["types"]
    assert "TypedDataSign" not in payload["types"]


def test_build_order_typed_data_wraps_1271_with_typed_data_sign_envelope() -> None:
    payload = build_order_typed_data(_fixture(signature_type=3))
    assert payload["primaryType"] == "TypedDataSign"
    assert payload["domain"] == {
        "name": "Polymarket CTF Exchange",
        "version": "2",
        "chainId": 137,
        "verifyingContract": EXCHANGE_ADDRESS,
    }
    assert payload["message"]["name"] == "DepositWallet"
    assert payload["message"]["version"] == "1"
    assert payload["message"]["chainId"] == 137
    assert payload["message"]["verifyingContract"] == DEPOSIT_WALLET_ADDRESS
    assert payload["message"]["salt"] == BYTES32_ZERO
    assert payload["message"]["contents"]["maker"] == DEPOSIT_WALLET_ADDRESS
    assert payload["message"]["contents"]["side"] == 0


def test_order_message_encodes_buy_as_zero_and_sell_as_one() -> None:
    buy_payload = build_order_typed_data(_fixture(signature_type=0))
    sell_unsigned = dataclasses.replace(_fixture(signature_type=0), side="SELL")
    sell_payload = build_order_typed_data(sell_unsigned)
    assert buy_payload["message"]["side"] == 0
    assert sell_payload["message"]["side"] == 1


def test_build_order_signature_passes_through_for_non_1271() -> None:
    result = build_order_signature(_fixture(signature_type=1), EVM_SIGNATURE)
    assert result == EVM_SIGNATURE


def test_build_order_signature_appends_erc7739_trailer_for_1271() -> None:
    result = build_order_signature(_fixture(signature_type=3), EVM_SIGNATURE)
    assert result != EVM_SIGNATURE
    assert result.startswith(EVM_SIGNATURE)
    contents_type_hex = ORDER_TYPE_STRING.encode("utf-8").hex()
    contents_type_length = f"{len(ORDER_TYPE_STRING):04x}"
    assert result.endswith(contents_type_hex + contents_type_length)
    expected_len = 2 + 65 * 2 + 32 * 2 + 32 * 2 + len(ORDER_TYPE_STRING) * 2 + 2 * 2
    assert len(result) == expected_len


def test_wrap_deposit_wallet_signature_wraps_erc7739_order_signature() -> None:
    order = _fixture(signature_type=3)
    owner_signature = build_order_signature(order, EVM_SIGNATURE)
    result = wrap_deposit_wallet_signature(
        signer=SESSION_SIGNER_ADDRESS,
        signer_type="SESSION_KEY",
        signature=owner_signature,
    )

    raw = bytes.fromhex(result.removeprefix("0x"))
    assert raw[-32:] == SESSION_SIGNER_MAGIC_BYTES
    signer_id, salt, wrapped_signature = cast(
        tuple[bytes, bytes, bytes],
        abi_decode(["bytes32", "bytes32", "bytes"], raw[:-32]),
    )
    assert signer_id == bytes.fromhex(SESSION_SIGNER_ADDRESS[2:]).rjust(32, b"\x00")
    assert salt == b"\x00" * 32
    assert wrapped_signature == bytes.fromhex(owner_signature.removeprefix("0x"))
