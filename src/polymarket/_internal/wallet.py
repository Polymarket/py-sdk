from __future__ import annotations

from typing import Literal, TypeAlias

from eth_abi.abi import encode as abi_encode
from eth_abi.packed import encode_packed
from eth_utils.address import to_checksum_address
from eth_utils.crypto import keccak

from polymarket._internal.environment import WalletDerivationConfig
from polymarket._internal.eoa.rpc import (
    JsonRpcClient,
    SyncJsonRpcClient,
    is_json_rpc_contract_revert,
)
from polymarket.errors import UserInputError

WalletType: TypeAlias = Literal["EOA", "POLY_PROXY", "GNOSIS_SAFE", "DEPOSIT_WALLET"]

_SIGNATURE_TYPE_BY_WALLET: dict[WalletType, int] = {
    "EOA": 0,
    "POLY_PROXY": 1,
    "GNOSIS_SAFE": 2,
    "DEPOSIT_WALLET": 3,
}

_PROXY_BYTECODE_TEMPLATE = (
    "3d3d606380380380913d393d73"
    "{factory}"
    "5af4602a57600080fd5b602d8060366000396000f3363d3d373d3d3d363d73"
    "{impl}"
    "5af43d82803e903d91602b57fd5bf352e831dd"
    "0000000000000000000000000000000000000000000000000000000000000020"
    "0000000000000000000000000000000000000000000000000000000000000000"
)

_ERC1967_CONST1 = bytes.fromhex("cc3735a920a3ca505d382bbc545af43d6000803e6038573d6000fd5b3d6000f3")
_ERC1967_CONST2 = bytes.fromhex("5155f3363d3d373d3d363d7f360894a13ba1a3210667c828492db98dca3e2076")
_ERC1967_PREFIX_BASE = 0x61003D3D8160233D3973

_ERC1967_BEACON_CONST1 = bytes.fromhex(
    "b3582b35133d50545afa5036515af43d6000803e604d573d6000fd5b3d6000f3"
)
_ERC1967_BEACON_CONST2 = bytes.fromhex(
    "1b60e01b36527fa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6c"
)
_ERC1967_BEACON_CONST3 = bytes.fromhex("60195155f3363d3d373d3d363d602036600436635c60da")
_ERC1967_BEACON_PREFIX_BASE = 0x6100523D8160233D3973

_FACTORY_BEACON_SELECTOR = "0x49493a4d"
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def signature_type_for(wallet_type: WalletType) -> int:
    return _SIGNATURE_TYPE_BY_WALLET[wallet_type]


def derive_proxy_wallet_address(signer: str, config: WalletDerivationConfig) -> str:
    bytecode = bytes.fromhex(
        _PROXY_BYTECODE_TEMPLATE.format(
            factory=_strip_0x(config.proxy_factory).lower(),
            impl=_strip_0x(config.proxy_implementation).lower(),
        )
    )
    bytecode_hash = keccak(bytecode)
    salt = keccak(encode_packed(["address"], [signer]))
    return _create2(config.proxy_factory, salt, bytecode_hash)


def derive_safe_wallet_address(signer: str, config: WalletDerivationConfig) -> str:
    bytecode_hash = bytes.fromhex(_strip_0x(config.safe_init_code_hash))
    salt = keccak(abi_encode(["address"], [signer]))
    return _create2(config.safe_factory, salt, bytecode_hash)


def derive_uups_deposit_wallet_address(signer: str, config: WalletDerivationConfig) -> str:
    args = _deposit_wallet_args(signer, config)
    bytecode_hash = _uups_deposit_init_code_hash(config.deposit_wallet_implementation, args)
    salt = keccak(args)
    return _create2(config.deposit_wallet_factory, salt, bytecode_hash)


def derive_beacon_deposit_wallet_address(signer: str, config: WalletDerivationConfig) -> str:
    args = _deposit_wallet_args(signer, config)
    bytecode_hash = _beacon_deposit_init_code_hash(config.deposit_wallet_beacon, args)
    salt = keccak(args)
    return _create2(config.deposit_wallet_factory, salt, bytecode_hash)


async def get_deposit_wallet_factory_beacon(rpc: JsonRpcClient, factory: str) -> str:
    try:
        data = await rpc.eth_call(to=factory, data=_FACTORY_BEACON_SELECTOR)
    except Exception as error:
        if is_json_rpc_contract_revert(error):
            return _ZERO_ADDRESS
        raise
    return _decode_address_return_data(data)


async def is_beacon_deposit_wallet_factory(rpc: JsonRpcClient, factory: str) -> bool:
    beacon = await get_deposit_wallet_factory_beacon(rpc, factory)
    return beacon.lower() != _ZERO_ADDRESS


async def derive_current_deposit_wallet_address(
    rpc: JsonRpcClient, signer: str, config: WalletDerivationConfig
) -> str:
    if await is_beacon_deposit_wallet_factory(rpc, config.deposit_wallet_factory):
        return derive_beacon_deposit_wallet_address(signer, config)
    return derive_uups_deposit_wallet_address(signer, config)


def get_deposit_wallet_factory_beacon_sync(rpc: SyncJsonRpcClient, factory: str) -> str:
    try:
        data = rpc.eth_call(to=factory, data=_FACTORY_BEACON_SELECTOR)
    except Exception as error:
        if is_json_rpc_contract_revert(error):
            return _ZERO_ADDRESS
        raise
    return _decode_address_return_data(data)


def is_beacon_deposit_wallet_factory_sync(rpc: SyncJsonRpcClient, factory: str) -> bool:
    beacon = get_deposit_wallet_factory_beacon_sync(rpc, factory)
    return beacon.lower() != _ZERO_ADDRESS


def derive_current_deposit_wallet_address_sync(
    rpc: SyncJsonRpcClient, signer: str, config: WalletDerivationConfig
) -> str:
    if is_beacon_deposit_wallet_factory_sync(rpc, config.deposit_wallet_factory):
        return derive_beacon_deposit_wallet_address(signer, config)
    return derive_uups_deposit_wallet_address(signer, config)


def classify_wallet_type(*, signer: str, wallet: str, config: WalletDerivationConfig) -> WalletType:
    try:
        signer_checksum = to_checksum_address(signer)
    except ValueError as error:
        raise UserInputError(f"Invalid signer address: {error}") from error
    try:
        wallet_checksum = to_checksum_address(wallet)
    except ValueError as error:
        raise UserInputError(f"Invalid wallet address: {error}") from error

    if wallet_checksum == signer_checksum:
        return "EOA"
    if wallet_checksum == derive_beacon_deposit_wallet_address(signer_checksum, config):
        return "DEPOSIT_WALLET"
    if wallet_checksum == derive_uups_deposit_wallet_address(signer_checksum, config):
        return "DEPOSIT_WALLET"
    if wallet_checksum == derive_proxy_wallet_address(signer_checksum, config):
        return "POLY_PROXY"
    if wallet_checksum == derive_safe_wallet_address(signer_checksum, config):
        return "GNOSIS_SAFE"

    raise UserInputError(
        f"Wallet {wallet_checksum} does not match the signer {signer_checksum} "
        "or any supported deterministic wallet address."
    )


def _deposit_wallet_args(signer: str, config: WalletDerivationConfig) -> bytes:
    signer_bytes = bytes.fromhex(_strip_0x(signer))
    wallet_id = signer_bytes.rjust(32, b"\x00")
    return abi_encode(["address", "bytes32"], [config.deposit_wallet_factory, wallet_id])


def _create2(factory: str, salt: bytes, bytecode_hash: bytes) -> str:
    factory_bytes = bytes.fromhex(_strip_0x(factory))
    raw = b"\xff" + factory_bytes + salt + bytecode_hash
    return to_checksum_address("0x" + keccak(raw)[12:].hex())


def _uups_deposit_init_code_hash(implementation: str, args: bytes) -> bytes:
    args_byte_length = len(args)
    prefix = _ERC1967_PREFIX_BASE + (args_byte_length << 56)
    prefix_bytes = prefix.to_bytes(10, "big")
    impl_bytes = bytes.fromhex(_strip_0x(implementation))
    bytecode = (
        prefix_bytes + impl_bytes + bytes.fromhex("6009") + _ERC1967_CONST2 + _ERC1967_CONST1 + args
    )
    return keccak(bytecode)


def _beacon_deposit_init_code_hash(beacon: str, args: bytes) -> bytes:
    args_byte_length = len(args)
    prefix = _ERC1967_BEACON_PREFIX_BASE + (args_byte_length << 56)
    prefix_bytes = prefix.to_bytes(10, "big")
    beacon_bytes = bytes.fromhex(_strip_0x(beacon))
    bytecode = (
        prefix_bytes
        + beacon_bytes
        + _ERC1967_BEACON_CONST3
        + _ERC1967_BEACON_CONST2
        + _ERC1967_BEACON_CONST1
        + args
    )
    return keccak(bytecode)


def _decode_address_return_data(data: str) -> str:
    if len(data) < 66:
        return _ZERO_ADDRESS
    try:
        return to_checksum_address("0x" + data[-40:])
    except ValueError:
        return _ZERO_ADDRESS


def _strip_0x(value: str) -> str:
    return value[2:] if value.startswith(("0x", "0X")) else value


__all__ = [
    "WalletType",
    "classify_wallet_type",
    "derive_beacon_deposit_wallet_address",
    "derive_current_deposit_wallet_address",
    "derive_current_deposit_wallet_address_sync",
    "derive_proxy_wallet_address",
    "derive_safe_wallet_address",
    "derive_uups_deposit_wallet_address",
    "get_deposit_wallet_factory_beacon",
    "get_deposit_wallet_factory_beacon_sync",
    "is_beacon_deposit_wallet_factory",
    "is_beacon_deposit_wallet_factory_sync",
    "signature_type_for",
]
