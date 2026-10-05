"""Collateral transfer signing and uncertain-submission boundaries."""

import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from polymarket import (
    PerpsInternalTransfer,
    PerpsInternalTransferDirection,
    PerpsKnownInternalTransferType,
)
from polymarket._internal.actions.perps.account import list_internal_transfers
from polymarket._internal.actions.perps.funds import transfer_perps_collateral
from polymarket._internal.actions.perps.paging import encode_perps_cursor
from polymarket._internal.actions.perps.signing import build_perps_op_typed_data
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import (
    RequestRejectedError,
    TransportError,
    UnexpectedResponseError,
    UserInputError,
)

_OWNER = Account.from_key("0x" + "01" * 32)
_TOKEN = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
_RECIPIENT = "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"


@pytest.mark.parametrize("amount", ["001.2300", Decimal("1.2300"), Decimal("1E-8")])
def test_transfer_signs_exact_amount_with_owner_and_keeps_label_unsigned(
    amount: Decimal | str,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "ok", "transfer_id": 2**64 - 1})

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://perps.test", transport=httpx.MockTransport(handler)
        ) as client:
            transport = AsyncTransport(base_url="https://perps.test", client=client)
            transfer_id = await transfer_perps_collateral(
                transport,
                signer=_OWNER,
                chain_id=137,
                token=_TOKEN,
                recipient=_RECIPIENT,
                amount=amount,
                label="rebalance-001",
            )
            assert transfer_id == 2**64 - 1

    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0].url.path == "/v1/account/internal-transfer"
    body = json.loads(calls[0].content)
    amount_string = amount if isinstance(amount, str) else format(amount, "f")
    assert body["op"] == {
        "type": "internalTransfer",
        "args": {
            "account": _OWNER.address,
            "token": _TOKEN,
            "amount": amount_string,
            "to": _RECIPIENT,
        },
    }
    assert body["label"] == "rebalance-001"
    assert 0 <= body["salt"] < 2**32
    assert 10**12 < body["ts"] < 10**14
    payload = build_perps_op_typed_data(
        chain_id=137,
        op=["internalTransfer", [_OWNER.address, _TOKEN, amount_string, _RECIPIENT]],
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
        {"amount": "-1"},
        {"amount": "1e2"},
        {"amount": "+1"},
        {"amount": "1 "},
        {"amount": "NaN"},
        {"amount": "١"},
        {"amount": True},
        {"amount": 1.1},
        {"amount": 1},
        {"amount": Decimal("Infinity")},
        {"recipient": "invalid"},
        {"recipient": _RECIPIENT[2:]},
        {"recipient": _OWNER.address.lower()},
        {"label": ""},
        {"label": "é" * 33},
    ],
)
def test_transfer_validates_before_transport(overrides: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid transfer reached transport")

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://perps.test", transport=httpx.MockTransport(handler)
        ) as client:
            transport = AsyncTransport(base_url="https://perps.test", client=client)
            params: dict[str, Any] = {"recipient": _RECIPIENT, "amount": "1", **overrides}
            with pytest.raises(UserInputError):
                await transfer_perps_collateral(
                    transport,
                    signer=_OWNER,
                    chain_id=137,
                    token=_TOKEN,
                    **params,
                )

    asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        {"status": "ok"},
        {"status": "ok", "transfer_id": True},
        {"status": "ok", "transfer_id": -1},
        {"status": "ok", "transfer_id": 1.0},
        {"status": "ok", "transfer_id": "1"},
        {"status": "err", "transfer_id": 1},
    ],
)
def test_transfer_rejects_malformed_success(response: dict[str, Any]) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://perps.test",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)),
        ) as client:
            with pytest.raises(UnexpectedResponseError):
                await transfer_perps_collateral(
                    AsyncTransport(base_url="https://perps.test", client=client),
                    signer=_OWNER,
                    chain_id=137,
                    token=_TOKEN,
                    recipient=_RECIPIENT,
                    amount="1",
                )

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "server", "rejection"])
def test_transfer_never_retries_uncertain_submission(failure: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "label" not in json.loads(request.content)
        if failure == "timeout":
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(
            503 if failure == "server" else 422,
            json={"status": "err", "error": "transfer rejected"},
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://perps.test", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises((TransportError, RequestRejectedError)):
                await transfer_perps_collateral(
                    AsyncTransport(base_url="https://perps.test", client=client),
                    signer=_OWNER,
                    chain_id=137,
                    token=_TOKEN,
                    recipient=_RECIPIENT,
                    amount="1",
                )

    asyncio.run(run())
    assert len(calls) == 1


def test_history_defaults_and_canonical_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "polymarket._internal.actions.perps.account.time.time", lambda: 2_000_000_000
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [], "more": False})

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://perps.test", transport=httpx.MockTransport(handler)
        ) as client:
            pages = list_internal_transfers(
                AsyncTransport(base_url="https://perps.test", client=client)
            )
            page = await pages.first_page()
            assert page.items == () and not page.has_more

    asyncio.run(run())
    assert dict(captured[0].url.params) == {
        "start_timestamp": str(2_000_000_000_000 - 90 * 86400000),
        "end_timestamp": "2000000000000",
    }
    row = {
        "transfer_id": 2**64 - 1,
        "type": "referral_payout",
        "asset": "pUSD",
        "amount": "123.4500",
        "direction": "in",
        "counterparty": _RECIPIENT,
        "created_timestamp": 2000000000000,
    }
    transfer = PerpsInternalTransfer.parse_response(row)
    assert transfer.transfer_id == 2**64 - 1
    assert transfer.type is PerpsKnownInternalTransferType.REFERRAL_PAYOUT
    assert transfer.direction is PerpsInternalTransferDirection.IN
    assert transfer.label is None
    assert transfer.amount == Decimal("123.4500")
    assert (
        PerpsInternalTransfer.parse_response({**row, "type": "new_classification"}).type
        == "new_classification"
    )
    for invalid in (
        {"type": ""},
        {"direction": "both"},
        {"transfer_id": True},
        {"transfer_id": -1},
        {"transfer_id": 1.0},
        {"created_timestamp": "yesterday"},
    ):
        with pytest.raises(UnexpectedResponseError):
            PerpsInternalTransfer.parse_response({**row, **invalid})


@pytest.mark.parametrize(
    "state",
    [
        {"kind": "perpsWithdrawals", "start_timestamp": 0, "end_timestamp": 1, "seen_keys": []},
        {
            "kind": "perpsInternalTransfers",
            "start_timestamp": True,
            "end_timestamp": 1,
            "seen_keys": [],
        },
        {
            "kind": "perpsInternalTransfers",
            "start_timestamp": 0,
            "end_timestamp": 1,
            "seen_keys": [1],
        },
        {
            "kind": "perpsInternalTransfers",
            "start_timestamp": 0,
            "end_timestamp": -1,
            "seen_keys": [],
        },
    ],
)
def test_history_rejects_invalid_cursor_before_transport(state: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid cursor reached transport")

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://perps.test", transport=httpx.MockTransport(handler)
        ) as client:
            transport = AsyncTransport(base_url="https://perps.test", client=client)
            for cursor in (encode_perps_cursor(state), "not-base64"):
                with pytest.raises(UserInputError):
                    await list_internal_transfers(transport, cursor=cursor).first_page()

    asyncio.run(run())
