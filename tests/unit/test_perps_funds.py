# pyright: reportPrivateUsage=false
"""Perps collateral movement construction tests."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import cast

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.perps.funds import perps_deposit_call, withdraw_from_perps
from polymarket._internal.actions.perps.signing import build_perps_withdraw_typed_data
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


@pytest.mark.parametrize("label", [None, "treasury", "é" * 32])
def test_internal_transfer_signs_exact_amount_and_keeps_label_unsigned(
    monkeypatch: pytest.MonkeyPatch, label: str | None
) -> None:
    from polymarket._internal.actions.perps.funds import transfer_perps_collateral
    from polymarket._internal.actions.perps.signing import build_perps_op_typed_data

    monkeypatch.setattr("polymarket._internal.actions.perps.funds.now_ms", lambda: 1751500000123)
    monkeypatch.setattr("polymarket._internal.actions.perps.funds.random_perps_salt", lambda: 12345)
    recipient = "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok", "transfer_id": 2**64 - 1})

    async def run() -> int:
        transport = _transport(handler)
        try:
            return await transfer_perps_collateral(
                transport,
                signer=_OWNER,
                chain_id=137,
                token=_COLLATERAL,
                recipient=recipient,
                amount="123.450000000000000001",
                label=label,
            )
        finally:
            await transport.close()

    assert asyncio.run(run()) == 2**64 - 1
    assert len(requests) == 1 and requests[0].url.path == "/v1/account/internal-transfer"
    body = json.loads(requests[0].content)
    assert body["op"] == {
        "type": "internalTransfer",
        "args": {
            "account": _OWNER.address,
            "token": _COLLATERAL,
            "amount": "123.450000000000000001",
            "to": recipient,
        },
    }
    assert body["ts"] == 1751500000123 and body["salt"] == 12345
    assert ("label" in body) == (label is not None)
    if label is not None:
        assert body["label"] == label
    signed = build_perps_op_typed_data(
        chain_id=137,
        op=["internalTransfer", [_OWNER.address, _COLLATERAL, "123.450000000000000001", recipient]],
        salt=12345,
        timestamp_ms=1751500000123,
    )
    # Offline vector from the TypeScript SDK owner-op signer, using this suite's fixture key.
    assert (
        signed["message"]["data"]
        == "0x2a42bdb37738a5139a8ebb6795dd36b1db6d072a07f5f95f9e240828dcc2f84e"
    )
    assert body["sig"] == (
        "0xbc8e4b361f5cc6c1b24b0a995bd70f36ae299280d856050fcd4b9fc3ec68d95f6"
        "77d782de375a514e36c56193d71add524b985ee73545420e1b5d1df8666c6a21c"
    )
    recovered = Account.recover_message(
        encode_typed_data(full_message=signed), signature=body["sig"]
    )
    assert recovered == _OWNER.address


@pytest.mark.parametrize(
    "amount,expected",
    [
        (1e-6, "0.000001"),
        (Decimal("1E-7"), "0.0000001"),
        (Decimal("1E+2"), "100"),
        (1e20, "100000000000000000000"),
    ],
)
def test_public_internal_transfer_numeric_and_string_amounts_sign_identically(
    monkeypatch: pytest.MonkeyPatch, amount: Decimal | float, expected: str
) -> None:
    from polymarket._internal.actions.perps.signing import build_perps_op_typed_data

    monkeypatch.setattr("polymarket._internal.actions.perps.funds.now_ms", lambda: 1751500000123)
    monkeypatch.setattr("polymarket._internal.actions.perps.funds.random_perps_salt", lambda: 12345)
    recipient = "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok", "transfer_id": 42})

    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=_OWNER_KEY,
            wallet=_OWNER.address,
            credentials=ApiKeyCreds(
                key="test-key", passphrase="test-passphrase", secret="dGVzdA=="
            ),
            validate_credentials=False,
        )
        async with (
            client,
            httpx.AsyncClient(base_url=_BASE_URL, transport=httpx.MockTransport(handler)) as http,
        ):
            await client._ctx.perps.close()
            client._ctx = replace(
                client._ctx, perps=AsyncTransport(base_url=_BASE_URL, client=http)
            )
            assert await client.transfer_perps_collateral(recipient=recipient, amount=amount) == 42
            assert (
                await client.transfer_perps_collateral(recipient=recipient, amount=expected) == 42
            )

    asyncio.run(run())
    assert len(requests) == 2
    body = json.loads(requests[0].content)
    assert body == json.loads(requests[1].content)
    assert body["op"]["args"]["amount"] == expected
    signed = build_perps_op_typed_data(
        chain_id=137,
        op=["internalTransfer", [_OWNER.address, _COLLATERAL, expected, recipient]],
        salt=12345,
        timestamp_ms=1751500000123,
    )
    assert (
        Account.recover_message(encode_typed_data(full_message=signed), signature=body["sig"])
        == _OWNER.address
    )


@pytest.mark.parametrize(
    "amount,recipient,label",
    [
        ("0", "0x" + "1" * 40, None),
        ("-1", "0x" + "1" * 40, None),
        ("NaN", "0x" + "1" * 40, None),
        ("1e2", "0x" + "1" * 40, None),
        (True, "0x" + "1" * 40, None),
        ("1", "invalid", None),
        ("1", _OWNER.address.lower(), None),
        ("1", "0x" + "1" * 40, ""),
        ("1", "0x" + "1" * 40, "é" * 33),
    ],
)
def test_internal_transfer_validates_before_signing_or_submission(
    monkeypatch: pytest.MonkeyPatch, amount: object, recipient: str, label: str | None
) -> None:
    from typing import Any

    from polymarket._internal.actions.perps.funds import transfer_perps_collateral

    def unexpected_sign(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid transfer reached signing")

    monkeypatch.setattr(
        "polymarket._internal.actions.perps.funds.sign_owner_typed_data", unexpected_sign
    )

    async def run() -> None:
        transport = _transport(lambda _: pytest.fail("invalid transfer reached transport"))
        try:
            with pytest.raises(UserInputError):
                await transfer_perps_collateral(
                    transport,
                    signer=_OWNER,
                    chain_id=137,
                    token=_COLLATERAL,
                    recipient=recipient,
                    amount=cast(Any, amount),
                    label=label,
                )
        finally:
            await transport.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "ok"},
        {"status": "ok", "transfer_id": True},
        {"status": "ok", "transfer_id": -1},
    ],
)
def test_internal_transfer_rejects_malformed_acceptance(payload: object) -> None:
    from polymarket._internal.actions.perps.funds import transfer_perps_collateral
    from polymarket.errors import UnexpectedResponseError

    async def run() -> None:
        transport = _transport(lambda _: httpx.Response(200, json=payload))
        try:
            with pytest.raises(UnexpectedResponseError):
                await transfer_perps_collateral(
                    transport,
                    signer=_OWNER,
                    chain_id=137,
                    token=_COLLATERAL,
                    recipient="0x" + "1" * 40,
                    amount="1",
                )
        finally:
            await transport.close()

    asyncio.run(run())


@pytest.mark.parametrize("status", [422, 503, 0])
def test_internal_transfer_does_not_retry_rejections_or_uncertain_failures(status: int) -> None:
    from polymarket._internal.actions.perps.funds import transfer_perps_collateral
    from polymarket.errors import PolymarketError

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if status == 0:
            raise httpx.ReadTimeout("offline timeout", request=request)
        return httpx.Response(status, json={"status": "err", "error": "transfer_rejected"})

    async def run() -> None:
        transport = _transport(handler)
        try:
            with pytest.raises(PolymarketError):
                await transfer_perps_collateral(
                    transport,
                    signer=_OWNER,
                    chain_id=137,
                    token=_COLLATERAL,
                    recipient="0x" + "1" * 40,
                    amount="1",
                )
        finally:
            await transport.close()

    asyncio.run(run())
    assert attempts == 1
