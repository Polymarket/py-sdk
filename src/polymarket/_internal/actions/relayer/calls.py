from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from eth_abi.abi import decode as abi_decode
from eth_abi.abi import encode as abi_encode
from eth_utils.crypto import keccak
from eth_utils.hexadecimal import decode_hex

from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.types import to_combo_condition_id
from polymarket.types import EvmAddress, HexString

MAX_UINT256 = (1 << 256) - 1


def _selector(signature: str) -> bytes:
    return keccak(signature.encode("ascii"))[:4]


_ERC20_APPROVE_SELECTOR = _selector("approve(address,uint256)")
_DEPOSIT_WALLET_AUTHORIZE_SESSION_SIGNER_SELECTOR = _selector(
    "authorizeSessionSigner(address,uint256)"
)
_DEPOSIT_WALLET_REVOKE_SESSION_SIGNER_SELECTOR = _selector("revokeSessionSigner(address)")
_ERC20_ALLOWANCE_SELECTOR = _selector("allowance(address,address)")
_ERC20_TRANSFER_SELECTOR = _selector("transfer(address,uint256)")
_ERC1155_BALANCE_OF_SELECTOR = _selector("balanceOf(address,uint256)")
_ERC1155_BALANCE_OF_BATCH_SELECTOR = _selector("balanceOfBatch(address[],uint256[])")
_ERC1155_SET_APPROVAL_FOR_ALL_SELECTOR = _selector("setApprovalForAll(address,bool)")
_ERC1155_IS_APPROVED_FOR_ALL_SELECTOR = _selector("isApprovedForAll(address,address)")
_CTF_SPLIT_POSITION_SELECTOR = _selector("splitPosition(address,bytes32,bytes32,uint256[],uint256)")
_CTF_MERGE_POSITIONS_SELECTOR = _selector(
    "mergePositions(address,bytes32,bytes32,uint256[],uint256)"
)
_CTF_REDEEM_POSITIONS_SELECTOR = _selector("redeemPositions(address,bytes32,bytes32,uint256[])")
_ROUTER_SPLIT_SELECTOR = _selector("split(bytes31,uint256)")
_ROUTER_MERGE_SELECTOR = _selector("merge(bytes31,uint256)")
_ROUTER_REDEEM_SELECTOR = _selector("redeem(bytes31,uint256,uint256)")
_COMBINATORIAL_PREPARE_CONDITION_SELECTOR = _selector("prepareCondition(uint256[])")
_SAFE_MULTISEND_SELECTOR = _selector("multiSend(bytes)")
_PROXY_FACTORY_SELECTOR = _selector("proxy((uint8,address,uint256,bytes)[])")
_INNER_OPERATION_CALL = 0
_PROXY_TYPE_CODE_CALL = 1
_ZERO_BYTES32 = b"\x00" * 32
_BINARY_PARTITION = [1, 2]
_BINARY_INDEX_SETS = [1, 2]


@dataclass(frozen=True, slots=True)
class TransactionCall:
    to: EvmAddress
    data: HexString
    value: int = 0


def erc20_approval_call(
    *, token_address: EvmAddress, spender: EvmAddress, amount: int
) -> TransactionCall:
    _expect_uint256(amount, "Approval amount")
    payload = _ERC20_APPROVE_SELECTOR + abi_encode(["address", "uint256"], [str(spender), amount])
    return TransactionCall(
        to=token_address,
        data=cast(HexString, "0x" + payload.hex()),
    )


def authorize_session_signer_call(
    *, wallet_address: EvmAddress, session_signer: EvmAddress, valid_until: int
) -> TransactionCall:
    _expect_uint256(valid_until, "Session key expiry")
    payload = _DEPOSIT_WALLET_AUTHORIZE_SESSION_SIGNER_SELECTOR + abi_encode(
        ["address", "uint256"], [str(session_signer), valid_until]
    )
    return TransactionCall(
        to=wallet_address,
        data=cast(HexString, "0x" + payload.hex()),
    )


def revoke_session_signer_call(
    *, wallet_address: EvmAddress, session_signer: EvmAddress
) -> TransactionCall:
    payload = _DEPOSIT_WALLET_REVOKE_SESSION_SIGNER_SELECTOR + abi_encode(
        ["address"], [str(session_signer)]
    )
    return TransactionCall(
        to=wallet_address,
        data=cast(HexString, "0x" + payload.hex()),
    )


def erc20_allowance_call(
    *, token_address: EvmAddress, owner: EvmAddress, spender: EvmAddress
) -> TransactionCall:
    payload = _ERC20_ALLOWANCE_SELECTOR + abi_encode(
        ["address", "address"], [str(owner), str(spender)]
    )
    return TransactionCall(to=token_address, data=cast(HexString, "0x" + payload.hex()))


def decode_erc20_allowance_result(data: str) -> int:
    return cast(int, _decode_return_data(data, "uint256"))


def erc20_transfer_call(
    *, token_address: EvmAddress, recipient: EvmAddress, amount: int
) -> TransactionCall:
    _expect_uint256(amount, "Transfer amount")
    payload = _ERC20_TRANSFER_SELECTOR + abi_encode(
        ["address", "uint256"], [str(recipient), amount]
    )
    return TransactionCall(
        to=token_address,
        data=cast(HexString, "0x" + payload.hex()),
    )


def erc1155_set_approval_for_all_call(
    *, token_address: EvmAddress, operator: EvmAddress, approved: bool = True
) -> TransactionCall:
    payload = _ERC1155_SET_APPROVAL_FOR_ALL_SELECTOR + abi_encode(
        ["address", "bool"], [str(operator), approved]
    )
    return TransactionCall(
        to=token_address,
        data=cast(HexString, "0x" + payload.hex()),
    )


def erc1155_balance_of_call(
    *, token_address: EvmAddress, owner: EvmAddress, token_id: str
) -> TransactionCall:
    payload = _ERC1155_BALANCE_OF_SELECTOR + abi_encode(
        ["address", "uint256"], [str(owner), _position_id_uint256(token_id)]
    )
    return TransactionCall(to=token_address, data=cast(HexString, "0x" + payload.hex()))


def decode_erc1155_balance_of_result(data: str) -> int:
    return cast(int, _decode_return_data(data, "uint256"))


def erc1155_balance_of_batch_call(
    *, token_address: EvmAddress, owners: list[EvmAddress], token_ids: list[str]
) -> TransactionCall:
    if len(owners) != len(token_ids):
        raise UserInputError("owners and token_ids must have the same length")
    payload = _ERC1155_BALANCE_OF_BATCH_SELECTOR + abi_encode(
        ["address[]", "uint256[]"],
        [[str(owner) for owner in owners], [_position_id_uint256(item) for item in token_ids]],
    )
    return TransactionCall(to=token_address, data=cast(HexString, "0x" + payload.hex()))


def decode_erc1155_balance_of_batch_result(data: str) -> tuple[int, ...]:
    values = _decode_return_data(data, "uint256[]")
    if not isinstance(values, tuple):
        raise UnexpectedResponseError("ERC1155 balanceOfBatch did not return uint256[]")
    return cast(tuple[int, ...], values)


def erc1155_is_approved_for_all_call(
    *, token_address: EvmAddress, owner: EvmAddress, operator: EvmAddress
) -> TransactionCall:
    payload = _ERC1155_IS_APPROVED_FOR_ALL_SELECTOR + abi_encode(
        ["address", "address"], [str(owner), str(operator)]
    )
    return TransactionCall(to=token_address, data=cast(HexString, "0x" + payload.hex()))


def decode_erc1155_is_approved_for_all_result(data: str) -> bool:
    return cast(bool, _decode_return_data(data, "bool"))


def split_position_call(
    *,
    target: EvmAddress,
    collateral: EvmAddress,
    condition_id: str,
    amount: int,
) -> TransactionCall:
    _expect_uint256(amount, "Split amount")
    payload = _CTF_SPLIT_POSITION_SELECTOR + abi_encode(
        ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
        [
            str(collateral),
            _ZERO_BYTES32,
            _condition_id_bytes(condition_id),
            list(_BINARY_PARTITION),
            amount,
        ],
    )
    return TransactionCall(to=target, data=cast(HexString, "0x" + payload.hex()))


def merge_positions_call(
    *,
    target: EvmAddress,
    collateral: EvmAddress,
    condition_id: str,
    amount: int,
) -> TransactionCall:
    _expect_uint256(amount, "Merge amount")
    payload = _CTF_MERGE_POSITIONS_SELECTOR + abi_encode(
        ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
        [
            str(collateral),
            _ZERO_BYTES32,
            _condition_id_bytes(condition_id),
            list(_BINARY_PARTITION),
            amount,
        ],
    )
    return TransactionCall(to=target, data=cast(HexString, "0x" + payload.hex()))


def ctf_redeem_positions_call(
    *,
    ctf: EvmAddress,
    collateral: EvmAddress,
    condition_id: str,
) -> TransactionCall:
    payload = _CTF_REDEEM_POSITIONS_SELECTOR + abi_encode(
        ["address", "bytes32", "bytes32", "uint256[]"],
        [
            str(collateral),
            _ZERO_BYTES32,
            _condition_id_bytes(condition_id),
            list(_BINARY_INDEX_SETS),
        ],
    )
    return TransactionCall(to=ctf, data=cast(HexString, "0x" + payload.hex()))


def split_v2_call(*, router: EvmAddress, condition_id: str, amount: int) -> TransactionCall:
    _expect_uint256(amount, "Split amount")
    payload = _ROUTER_SPLIT_SELECTOR + abi_encode(
        ["bytes31", "uint256"], [_protocol_v2_condition_id_bytes(condition_id), amount]
    )
    return TransactionCall(to=router, data=cast(HexString, "0x" + payload.hex()))


def merge_v2_call(*, router: EvmAddress, condition_id: str, amount: int) -> TransactionCall:
    _expect_uint256(amount, "Merge amount")
    payload = _ROUTER_MERGE_SELECTOR + abi_encode(
        ["bytes31", "uint256"], [_protocol_v2_condition_id_bytes(condition_id), amount]
    )
    return TransactionCall(to=router, data=cast(HexString, "0x" + payload.hex()))


def redeem_v2_call(
    *, router: EvmAddress, condition_id: str, outcome_index: int, amount: int
) -> TransactionCall:
    if outcome_index not in (0, 1):
        raise UserInputError("Protocol v2 outcome index must be 0 or 1")
    _expect_uint256(amount, "Redeem amount")
    payload = _ROUTER_REDEEM_SELECTOR + abi_encode(
        ["bytes31", "uint256", "uint256"],
        [_protocol_v2_condition_id_bytes(condition_id), outcome_index, amount],
    )
    return TransactionCall(to=router, data=cast(HexString, "0x" + payload.hex()))


def combinatorial_prepare_condition_call(
    *, combinatorial_module: EvmAddress, legs: list[int]
) -> TransactionCall:
    for leg in legs:
        _expect_uint256(leg, "Leg position ID")
    payload = _COMBINATORIAL_PREPARE_CONDITION_SELECTOR + abi_encode(["uint256[]"], [legs])
    return TransactionCall(
        to=combinatorial_module,
        data=cast(HexString, "0x" + payload.hex()),
    )


def _expect_uint256(amount: int, label: str) -> None:
    if not isinstance(amount, int) or isinstance(amount, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError(f"{label} must be an int")
    if amount < 0:
        raise UserInputError(f"{label} must be non-negative")
    if amount > MAX_UINT256:
        raise UserInputError(f"{label} exceeds uint256 range")


def _condition_id_bytes(condition_id: str) -> bytes:
    s = condition_id[2:] if condition_id.startswith(("0x", "0X")) else condition_id
    try:
        raw = bytes.fromhex(s)
    except ValueError as error:
        raise UserInputError(f"condition_id is not valid hex: {error}") from error
    if len(raw) != 32:
        raise UserInputError(f"condition_id must be a 32-byte hex string, got {len(raw)} bytes")
    return raw


def _protocol_v2_condition_id_bytes(condition_id: str) -> bytes:
    try:
        return bytes.fromhex(to_combo_condition_id(condition_id)[2:])
    except TypeError as error:
        raise UserInputError(str(error)) from error


def _position_id_uint256(position_id: str) -> int:
    try:
        value = int(position_id)
    except ValueError as error:
        raise UserInputError("Position ID must be a uint256 value") from error
    _expect_uint256(value, "Position ID")
    return value


def _decode_return_data(data: str, abi_type: str) -> object:
    try:
        values = abi_decode([abi_type], decode_hex(data))
    except Exception as error:
        raise UnexpectedResponseError(
            f"Could not decode {abi_type} return data: {error}"
        ) from error
    if len(values) != 1:
        raise UnexpectedResponseError(f"Expected one {abi_type} return value, got {len(values)}")
    return values[0]


def encode_proxy_call(calls: list[TransactionCall]) -> HexString:
    if not calls:
        raise UserInputError("encode_proxy_call requires at least one call")
    tuples = [
        (_PROXY_TYPE_CODE_CALL, str(call.to), call.value, decode_hex(call.data)) for call in calls
    ]
    encoded_args = abi_encode(
        ["(uint8,address,uint256,bytes)[]"],
        [tuples],
    )
    return cast(HexString, "0x" + (_PROXY_FACTORY_SELECTOR + encoded_args).hex())


def encode_safe_multisend_call(calls: list[TransactionCall]) -> HexString:
    if not calls:
        raise UserInputError("encode_safe_multisend_call requires at least one call")
    inner = b""
    for call in calls:
        to_bytes = decode_hex(str(call.to))
        if len(to_bytes) != 20:
            raise UserInputError(f"Expected 20-byte address, got {len(to_bytes)} bytes")
        data_bytes = decode_hex(call.data)
        inner += bytes([_INNER_OPERATION_CALL])
        inner += to_bytes
        inner += call.value.to_bytes(32, "big")
        inner += len(data_bytes).to_bytes(32, "big")
        inner += data_bytes
    payload = _SAFE_MULTISEND_SELECTOR + abi_encode(["bytes"], [inner])
    return cast(HexString, "0x" + payload.hex())


__all__ = [
    "MAX_UINT256",
    "TransactionCall",
    "authorize_session_signer_call",
    "combinatorial_prepare_condition_call",
    "ctf_redeem_positions_call",
    "decode_erc1155_balance_of_batch_result",
    "decode_erc1155_balance_of_result",
    "decode_erc1155_is_approved_for_all_result",
    "decode_erc20_allowance_result",
    "encode_proxy_call",
    "encode_safe_multisend_call",
    "erc1155_is_approved_for_all_call",
    "erc1155_balance_of_batch_call",
    "erc1155_balance_of_call",
    "erc1155_set_approval_for_all_call",
    "erc20_allowance_call",
    "erc20_approval_call",
    "erc20_transfer_call",
    "merge_positions_call",
    "merge_v2_call",
    "redeem_v2_call",
    "revoke_session_signer_call",
    "split_position_call",
    "split_v2_call",
]
