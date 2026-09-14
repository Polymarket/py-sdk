from typing import Any

from eth_abi.abi import encode as abi_encode
from eth_utils.crypto import keccak

from polymarket._internal.actions.orders.types import BYTES32_ZERO, UnsignedOrder
from polymarket.types import HexString

_PROTOCOL_NAME = "Polymarket CTF Exchange"
_PROTOCOL_VERSION = "2"
_DEPOSIT_WALLET_DOMAIN_NAME = "DepositWallet"
_DEPOSIT_WALLET_DOMAIN_VERSION = "1"
_POLY_1271_SIGNATURE_TYPE = 3

_ORDER_TYPE_STRING = (
    "Order("
    "uint256 salt,"
    "address maker,"
    "address signer,"
    "uint256 tokenId,"
    "uint256 makerAmount,"
    "uint256 takerAmount,"
    "uint8 side,"
    "uint8 signatureType,"
    "uint256 timestamp,"
    "bytes32 metadata,"
    "bytes32 builder"
    ")"
)
_DOMAIN_TYPE_STRING = (
    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)

_ORDER_TYPE_HASH = keccak(_ORDER_TYPE_STRING.encode("utf-8"))
_DOMAIN_TYPE_HASH = keccak(_DOMAIN_TYPE_STRING.encode("utf-8"))
_PROTOCOL_NAME_HASH = keccak(_PROTOCOL_NAME.encode("utf-8"))
_PROTOCOL_VERSION_HASH = keccak(_PROTOCOL_VERSION.encode("utf-8"))

_EIP712_DOMAIN_FIELDS = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]
_ORDER_FIELDS = [
    {"name": "salt", "type": "uint256"},
    {"name": "maker", "type": "address"},
    {"name": "signer", "type": "address"},
    {"name": "tokenId", "type": "uint256"},
    {"name": "makerAmount", "type": "uint256"},
    {"name": "takerAmount", "type": "uint256"},
    {"name": "side", "type": "uint8"},
    {"name": "signatureType", "type": "uint8"},
    {"name": "timestamp", "type": "uint256"},
    {"name": "metadata", "type": "bytes32"},
    {"name": "builder", "type": "bytes32"},
]
_TYPED_DATA_SIGN_FIELDS = [
    {"name": "contents", "type": "Order"},
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
    {"name": "salt", "type": "bytes32"},
]


def build_order_typed_data(
    order: UnsignedOrder, *, protocol_version: str | None = None
) -> dict[str, Any]:
    protocol_version = protocol_version or order.protocol_version
    standard = _build_standard_typed_data(order, protocol_version=protocol_version)
    if order.signature_type != _POLY_1271_SIGNATURE_TYPE:
        return standard
    return {
        "types": {
            "EIP712Domain": _EIP712_DOMAIN_FIELDS,
            "Order": _ORDER_FIELDS,
            "TypedDataSign": _TYPED_DATA_SIGN_FIELDS,
        },
        "primaryType": "TypedDataSign",
        "domain": {
            "name": _PROTOCOL_NAME,
            "version": protocol_version,
            "chainId": order.chain_id,
            "verifyingContract": order.exchange_address,
        },
        "message": {
            "contents": standard["message"],
            "name": _DEPOSIT_WALLET_DOMAIN_NAME,
            "version": _DEPOSIT_WALLET_DOMAIN_VERSION,
            "chainId": order.chain_id,
            "verifyingContract": order.signer,
            "salt": BYTES32_ZERO,
        },
    }


def build_order_signature(
    order: UnsignedOrder,
    signature: HexString,
    *,
    protocol_version: str | None = None,
) -> HexString:
    protocol_version = protocol_version or order.protocol_version
    order_signature = signature
    if order.signature_type == _POLY_1271_SIGNATURE_TYPE:
        app_domain_separator = _app_domain_separator(order, protocol_version=protocol_version)
        contents_hash = _order_contents_hash(order)
        contents_type = _ORDER_TYPE_STRING.encode("utf-8").hex()
        contents_type_length = f"{len(_ORDER_TYPE_STRING):04x}"
        trailer = (
            _strip_0x(app_domain_separator)
            + contents_hash.hex()
            + contents_type
            + contents_type_length
        )
        order_signature = HexString(signature + trailer)

    return order_signature


def _build_standard_typed_data(order: UnsignedOrder, *, protocol_version: str) -> dict[str, Any]:
    return {
        "types": {
            "EIP712Domain": _EIP712_DOMAIN_FIELDS,
            "Order": _ORDER_FIELDS,
        },
        "primaryType": "Order",
        "domain": {
            "name": _PROTOCOL_NAME,
            "version": protocol_version,
            "chainId": order.chain_id,
            "verifyingContract": order.exchange_address,
        },
        "message": _order_message(order),
    }


def _order_message(order: UnsignedOrder) -> dict[str, Any]:
    return {
        "salt": order.salt,
        "maker": order.maker,
        "signer": order.signer,
        "tokenId": int(order.token_id),
        "makerAmount": order.maker_amount,
        "takerAmount": order.taker_amount,
        "side": _encode_side(order.side),
        "signatureType": order.signature_type,
        "timestamp": order.timestamp,
        "metadata": order.metadata,
        "builder": order.builder,
    }


def _app_domain_separator(order: UnsignedOrder, *, protocol_version: str) -> str:
    protocol_version_hash = keccak(protocol_version.encode("utf-8"))
    encoded = abi_encode(
        ["bytes32", "bytes32", "bytes32", "uint256", "address"],
        [
            _DOMAIN_TYPE_HASH,
            _PROTOCOL_NAME_HASH,
            protocol_version_hash,
            order.chain_id,
            order.exchange_address,
        ],
    )
    return "0x" + keccak(encoded).hex()


def _order_contents_hash(order: UnsignedOrder) -> bytes:
    encoded = abi_encode(
        [
            "bytes32",
            "uint256",
            "address",
            "address",
            "uint256",
            "uint256",
            "uint256",
            "uint8",
            "uint8",
            "uint256",
            "bytes32",
            "bytes32",
        ],
        [
            _ORDER_TYPE_HASH,
            order.salt,
            order.maker,
            order.signer,
            int(order.token_id),
            order.maker_amount,
            order.taker_amount,
            _encode_side(order.side),
            order.signature_type,
            order.timestamp,
            bytes.fromhex(_strip_0x(order.metadata)),
            bytes.fromhex(_strip_0x(order.builder)),
        ],
    )
    return keccak(encoded)


def _encode_side(side: str) -> int:
    return 0 if side == "BUY" else 1


def _strip_0x(value: str) -> str:
    return value[2:] if value.startswith(("0x", "0X")) else value


__all__ = ["build_order_signature", "build_order_typed_data"]
