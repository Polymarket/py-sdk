"""Internal transfer history parsing and pagination boundaries."""

import asyncio
from decimal import Decimal
from typing import Any

import httpx
import pytest

from polymarket import (
    PerpsInternalTransfer,
    PerpsInternalTransferDirection,
    PerpsKnownInternalTransferType,
)
from polymarket._internal.actions.perps.account import list_internal_transfers
from polymarket._internal.actions.perps.paging import encode_perps_cursor
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import (
    UnexpectedResponseError,
    UserInputError,
)

_RECIPIENT = "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"


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
