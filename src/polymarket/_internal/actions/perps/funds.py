"""Perps collateral movement helpers."""

import re
import time
from decimal import Decimal
from typing import cast

from eth_abi.abi import encode as abi_encode
from eth_account.signers.local import LocalAccount
from eth_utils.crypto import keccak

from polymarket._internal.actions.perps.builders import validate_address
from polymarket._internal.actions.perps.paging import as_json_dict
from polymarket._internal.actions.perps.signing import (
    build_perps_op_typed_data,
    build_perps_withdraw_typed_data,
    now_ms,
    random_perps_salt,
    sign_owner_typed_data,
)
from polymarket._internal.actions.relayer.calls import MAX_UINT256, TransactionCall
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import (
    RequestRejectedError,
    UnexpectedResponseError,
    UserInputError,
)
from polymarket.models.perps.requests import DecimalInput, to_decimal_string
from polymarket.models.perps.types import PerpsInternalTransferId, PerpsWithdrawalId
from polymarket.types import EvmAddress, HexString

_PERPS_DEPOSIT_SELECTOR = keccak(b"deposit(address,uint256,address)")[:4]


def perps_deposit_call(
    *,
    deposit_contract: EvmAddress,
    token: EvmAddress,
    amount: int,
    to: EvmAddress,
) -> TransactionCall:
    if isinstance(amount, bool) or not isinstance(amount, int):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("Perps deposit amount must be an int")
    if amount <= 0:
        raise UserInputError("Perps deposit amount must be positive")
    if amount > MAX_UINT256:
        raise UserInputError("Perps deposit amount exceeds uint256 range")
    payload = _PERPS_DEPOSIT_SELECTOR + abi_encode(
        ["address", "uint256", "address"], [str(token), amount, str(to)]
    )
    return TransactionCall(
        to=deposit_contract,
        data=cast(HexString, "0x" + payload.hex()),
    )


async def withdraw_from_perps(
    perps: AsyncTransport,
    *,
    signer: LocalAccount,
    chain_id: int,
    deposit_contract: str,
    token: str,
    amount: int,
    to: str,
) -> PerpsWithdrawalId:
    if isinstance(amount, bool) or not isinstance(amount, int):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise UserInputError("Perps withdrawal amount must be an int")
    if amount <= 0:
        raise UserInputError("Perps withdrawal amount must be positive")
    if amount > MAX_UINT256:
        raise UserInputError("Perps withdrawal amount exceeds uint256 range")
    timestamp_s = int(time.time())
    salt = random_perps_salt()
    signature = sign_owner_typed_data(
        signer,
        build_perps_withdraw_typed_data(
            chain_id=chain_id,
            deposit_contract=deposit_contract,
            account=signer.address,
            token=token,
            amount=amount,
            to=to,
            salt=salt,
            timestamp_s=timestamp_s,
        ),
        what="Perps withdrawal request",
    )
    response = as_json_dict(
        await perps.post_json(
            "/v1/account/withdraw",
            json={
                "op": {
                    "type": "withdraw",
                    "args": {
                        "account": signer.address,
                        "token": token,
                        "amount": str(amount),
                        "to": to,
                    },
                },
                "salt": salt,
                "sig": signature,
                "ts": timestamp_s,
            },
        )
    )
    if response is None or response.get("status") not in ("ok", "err"):
        raise UnexpectedResponseError("Perps withdrawal response did not match expected shape")
    if response["status"] == "err":
        error = response.get("error")
        raise RequestRejectedError(
            str(error) if error else "Perps withdrawal was rejected.", status=200
        )
    withdrawal_id = response.get("withdraw_id")
    if isinstance(withdrawal_id, bool) or not isinstance(withdrawal_id, int):
        raise UnexpectedResponseError("Perps withdrawal response did not include a withdrawal ID.")
    return PerpsWithdrawalId(withdrawal_id)


async def transfer_perps_collateral(
    perps: AsyncTransport,
    *,
    signer: LocalAccount,
    chain_id: int,
    token: str,
    recipient: str,
    amount: DecimalInput,
    label: str | None = None,
) -> PerpsInternalTransferId:
    recipient = validate_address("recipient", recipient)
    if recipient.lower() == signer.address.lower():
        raise UserInputError("Perps collateral cannot be transferred to the authenticated account")
    amount_string = to_decimal_string("amount", amount)
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", amount_string) or Decimal(amount_string) <= 0:
        raise UserInputError("amount must be a positive fixed-point decimal")
    if label is not None and (
        not isinstance(label, str)  # pyright: ignore[reportUnnecessaryIsInstance]
        or not label
        or len(label.encode("utf-8")) > 64
    ):
        raise UserInputError("label must contain 1 to 64 UTF-8 bytes")
    timestamp = now_ms()
    salt = random_perps_salt()
    signature = sign_owner_typed_data(
        signer,
        build_perps_op_typed_data(
            chain_id=chain_id,
            op=["internalTransfer", [signer.address, token, amount_string, recipient]],
            salt=salt,
            timestamp_ms=timestamp,
        ),
        what="Perps internal transfer request",
    )
    body: dict[str, object] = {
        "op": {
            "type": "internalTransfer",
            "args": {
                "account": signer.address,
                "token": token,
                "amount": amount_string,
                "to": recipient,
            },
        },
        "salt": salt,
        "sig": signature,
        "ts": timestamp,
    }
    if label is not None:
        body["label"] = label
    response = as_json_dict(await perps.post_json("/v1/account/internal-transfer", json=body))
    if response is None or response.get("status") not in ("ok", "err"):
        raise UnexpectedResponseError(
            "Perps internal-transfer response did not match expected shape"
        )
    if response["status"] == "err":
        error = response.get("error")
        raise RequestRejectedError(
            str(error) if error else "Perps internal transfer was rejected.", status=200
        )
    transfer_id = response.get("transfer_id")
    if isinstance(transfer_id, bool) or not isinstance(transfer_id, int) or transfer_id < 0:
        raise UnexpectedResponseError(
            "Perps internal-transfer response did not include a transfer ID"
        )
    return PerpsInternalTransferId(transfer_id)


__all__ = ["perps_deposit_call", "withdraw_from_perps", "transfer_perps_collateral"]
