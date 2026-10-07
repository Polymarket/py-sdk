# pyright: reportPrivateUsage=false
"""Perps collateral movement construction tests."""

import asyncio
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
import respx
from eth_account import Account
from eth_account.messages import encode_typed_data

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.perps.funds import perps_deposit_call, withdraw_from_perps
from polymarket._internal.actions.perps.signing import (
    build_perps_op_typed_data,
    build_perps_withdraw_typed_data,
)
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import RequestRejectedError, UserInputError
from polymarket.types import EvmAddress

_BASE_URL = "https://perps.test"
_OWNER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
_OWNER = Account.from_key(_OWNER_KEY)

_DEPOSIT_CONTRACT = "0xDCa4af75705dbB50f62437045afF9921947917d2"
_COLLATERAL = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"

# Pinned against the TypeScript SDK encoder for the same arguments.
_DEPOSIT_CALLDATA = (
    "0xf45346dc"
    "000000000000000000000000c011a7e12a19f7b1f670d46f03b03f3342e82dfb"
    "0000000000000000000000000000000000000000000000000000000000989680"
    "000000000000000000000000f39fd6e51aad88f6f4ce6ab8827279cfffb92266"
)


def test_perps_deposit_call_matches_typescript_encoding() -> None:
    call = perps_deposit_call(
        deposit_contract=cast(EvmAddress, _DEPOSIT_CONTRACT),
        token=cast(EvmAddress, _COLLATERAL),
        amount=10_000_000,
        to=cast(EvmAddress, "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"),
    )
    assert call.to == _DEPOSIT_CONTRACT
    assert call.data == _DEPOSIT_CALLDATA


def test_perps_deposit_call_rejects_non_positive_amounts() -> None:
    for amount in (0, -1):
        with pytest.raises(UserInputError, match="positive"):
            perps_deposit_call(
                deposit_contract=cast(EvmAddress, _DEPOSIT_CONTRACT),
                token=cast(EvmAddress, _COLLATERAL),
                amount=amount,
                to=cast(EvmAddress, _OWNER.address),
            )


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> AsyncTransport:
    return AsyncTransport(
        base_url=_BASE_URL,
        client=httpx.AsyncClient(base_url=_BASE_URL, transport=httpx.MockTransport(handler)),
    )


def test_withdraw_sends_signed_request_and_returns_withdrawal_id() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"status": "ok", "withdraw_id": 314})

    async def run() -> int:
        transport = _transport(handler)
        try:
            return await withdraw_from_perps(
                transport,
                signer=_OWNER,
                chain_id=137,
                deposit_contract=_DEPOSIT_CONTRACT,
                token=_COLLATERAL,
                amount=10_000_000,
                to="0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
            )
        finally:
            await transport.close()

    withdrawal_id = asyncio.run(run())
    assert withdrawal_id == 314

    body = json.loads(captured[0].content)
    assert body["op"] == {
        "type": "withdraw",
        "args": {
            "account": _OWNER.address,
            "token": _COLLATERAL,
            "amount": "10000000",
            "to": "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
        },
    }
    # The withdrawal timestamp is expressed in seconds, not milliseconds.
    assert body["ts"] < 10**11
    payload = build_perps_withdraw_typed_data(
        chain_id=137,
        deposit_contract=_DEPOSIT_CONTRACT,
        account=_OWNER.address,
        token=_COLLATERAL,
        amount=10_000_000,
        to="0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
        salt=body["salt"],
        timestamp_s=body["ts"],
    )
    recovered = Account.recover_message(
        encode_typed_data(full_message=payload), signature=body["sig"]
    )
    assert recovered == _OWNER.address


def test_withdraw_maps_err_status_and_missing_id() -> None:
    def err_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "err", "error": "insufficient balance"})

    def missing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    async def run() -> None:
        err = _transport(err_handler)
        missing = _transport(missing_handler)
        try:
            with pytest.raises(RequestRejectedError, match="insufficient balance"):
                await withdraw_from_perps(
                    err,
                    signer=_OWNER,
                    chain_id=137,
                    deposit_contract=_DEPOSIT_CONTRACT,
                    token=_COLLATERAL,
                    amount=1,
                    to=_OWNER.address,
                )
            from polymarket.errors import UnexpectedResponseError

            with pytest.raises(UnexpectedResponseError, match="withdrawal ID"):
                await withdraw_from_perps(
                    missing,
                    signer=_OWNER,
                    chain_id=137,
                    deposit_contract=_DEPOSIT_CONTRACT,
                    token=_COLLATERAL,
                    amount=1,
                    to=_OWNER.address,
                )
        finally:
            await err.close()
            await missing.close()

    asyncio.run(run())


@pytest.mark.parametrize("amount", ["001.2300", Decimal("1.2300")])
@pytest.mark.parametrize("status", [200, 503])
def test_transfer_signs_exact_amount_and_submits_once(
    respx_mock: respx.MockRouter, amount: Decimal | str, status: int
) -> None:
    recipient = "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"
    route = respx_mock.post(PRODUCTION_CONFIG.perps_url + "/v1/account/internal-transfer").respond(
        status, json={"status": "ok", "transfer_id": 42}
    )

    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=_OWNER_KEY,
            wallet=_OWNER.address,
            validate_credentials=False,
            credentials=ApiKeyCreds(key="key", passphrase="pass", secret="c2VjcmV0"),
        )
        async with client:
            if status == 503:
                with pytest.raises(RequestRejectedError):
                    await client.transfer_perps_collateral(recipient=recipient, amount=amount)
            else:
                assert (
                    await client.transfer_perps_collateral(
                        recipient=recipient, amount=amount, label="rebalance"
                    )
                    == 42
                )

    asyncio.run(run())
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    amount_string = amount if isinstance(amount, str) else format(amount, "f")
    assert body["op"] == {
        "type": "internalTransfer",
        "args": {
            "account": _OWNER.address,
            "token": PRODUCTION_CONFIG.collateral_token,
            "amount": amount_string,
            "to": recipient,
        },
    }
    assert body.get("label") == ("rebalance" if status == 200 else None)
    assert 0 <= body["salt"] < 2**32 and 10**12 < body["ts"] < 10**14
    payload = build_perps_op_typed_data(
        chain_id=PRODUCTION_CONFIG.chain_id,
        op=[
            "internalTransfer",
            [_OWNER.address, PRODUCTION_CONFIG.collateral_token, amount_string, recipient],
        ],
        salt=body["salt"],
        timestamp_ms=body["ts"],
    )
    assert (
        Account.recover_message(encode_typed_data(full_message=payload), signature=body["sig"])
        == _OWNER.address
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": "0"},
        {"amount": 1.1},
        {"recipient": _OWNER.address},
        {"recipient": "invalid"},
        {"label": "é" * 33},
        {},
    ],
)
def test_transfer_rejects_invalid_inputs_and_session_signers(
    respx_mock: respx.MockRouter, overrides: dict[str, Any]
) -> None:
    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=_OWNER_KEY,
            validate_credentials=False,
            wallet=_OWNER.address if overrides else "0x0000000000000000000000000000000000000002",
            credentials=ApiKeyCreds(key="key", passphrase="pass", secret="c2VjcmV0"),
        )
        async with client:
            with pytest.raises(UserInputError):
                await client.transfer_perps_collateral(
                    **{
                        "recipient": "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
                        "amount": "1",
                        **overrides,
                    }
                )

    asyncio.run(run())
    assert not respx_mock.calls
