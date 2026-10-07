"""Internal transfer history parsing and pagination boundaries."""

import asyncio
from decimal import Decimal
from typing import Any

import httpx
import pytest

from polymarket import (
    PerpsInternalTransfer,
    PerpsInternalTransferDirection,
    PerpsInternalTransferId,
    PerpsKnownInternalTransferType,
)
from polymarket._internal.actions.perps.account import list_internal_transfers
from polymarket._internal.actions.perps.paging import encode_perps_cursor
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import (
    RequestRejectedError,
    UnexpectedResponseError,
    UserInputError,
)

_RECIPIENT = "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"


def _history_response(request: httpx.Request, timestamps_ns: list[int]) -> httpx.Response:
    # The history endpoint uses inclusive nanosecond bounds, a fixed 500-row cap,
    # and floors the returned timestamps to milliseconds.
    start_ns = int(request.url.params["start_timestamp"]) * 1_000_000
    end_ns = int(request.url.params["end_timestamp"]) * 1_000_000
    matches = sorted(
        (
            (timestamp_ns, transfer_id)
            for transfer_id, timestamp_ns in enumerate(timestamps_ns, 1)
            if start_ns <= timestamp_ns <= end_ns
        ),
        reverse=True,
    )
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "transfer_id": transfer_id,
                    "type": "referral_payout",
                    "asset": "pUSD",
                    "amount": "1",
                    "direction": "in",
                    "counterparty": _RECIPIENT,
                    "created_timestamp": timestamp_ns // 1_000_000,
                }
                for timestamp_ns, transfer_id in matches[:500]
            ],
            "more": len(matches) > 500,
        },
    )


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize(
    ("timestamps_ns", "start", "end", "expected_reads"),
    [
        (
            [1_000_000_000 + offset for offset in range(1, 501)] + [999_000_000],
            0,
            2000,
            [(0, 2000), (0, 1001), (1000, 1001), (0, 1000)],
        ),
        (
            [1_000_000_000 + offset for offset in range(1, 499)]
            + [1_001_000_000, 1_000_000_000, 999_000_000, 998_999_999, 1_001_000_001],
            999,
            1001,
            [(999, 1001), (999, 1001), (1000, 1001), (999, 1000)],
        ),
        (
            [1_001_000_000] * 500 + [999_000_000],
            0,
            1001,
            [(0, 1001), (0, 1001), (1000, 1001), (0, 1000)],
        ),
    ],
)
def test_dense_history_continues_without_losing_or_repeating_records(
    timestamps_ns: list[int],
    start: int,
    end: int,
    expected_reads: list[tuple[int, int]],
    resume: bool,
) -> None:
    reads: list[tuple[int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        reads.append(
            (int(request.url.params["start_timestamp"]), int(request.url.params["end_timestamp"]))
        )
        return _history_response(request, timestamps_ns)

    async def run() -> list[PerpsInternalTransferId]:
        async with httpx.AsyncClient(
            base_url="https://perps.test", transport=httpx.MockTransport(handler)
        ) as client:
            transport = AsyncTransport(base_url="https://perps.test", client=client)
            pages = list_internal_transfers(transport, start=start, end=end)
            if resume:
                first = await pages.first_page()
                assert first.next_cursor is not None
                # Existing cursors carry the original bounds and overlap identities.
                pages = list_internal_transfers(transport, cursor=first.next_cursor)
                return [item.transfer_id for item in first.items] + [
                    item.transfer_id async for item in pages.iter_items()
                ]
            return [item.transfer_id async for item in pages.iter_items()]

    assert asyncio.run(run()) == [
        transfer_id
        for timestamp_ns, transfer_id in sorted(
            ((timestamp_ns, index) for index, timestamp_ns in enumerate(timestamps_ns, 1)),
            reverse=True,
        )
        if start * 1_000_000 <= timestamp_ns <= end * 1_000_000
    ]
    assert reads == expected_reads


def test_history_single_millisecond_bounds_are_inclusive_without_a_probe() -> None:
    timestamps_ns = [999_999_999, 1_000_000_000, 1_000_000_001]
    reads: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        reads.append(request)
        return _history_response(request, timestamps_ns)

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://perps.test", transport=httpx.MockTransport(handler)
        ) as client:
            page = await list_internal_transfers(
                AsyncTransport(base_url="https://perps.test", client=client), start=1000, end=1000
            ).first_page()
            assert [item.transfer_id for item in page.items] == [2]
            assert not page.has_more

    asyncio.run(run())
    assert len(reads) == 1


@pytest.mark.parametrize(
    ("probe_fails", "last_at_end"), [(False, False), (False, True), (True, False)]
)
def test_dense_history_never_skips_an_unreadable_bucket(
    probe_fails: bool, last_at_end: bool
) -> None:
    count = 500 if probe_fails else 501
    timestamps_ns = (
        [1_001_000_000] * 500 + [1_000_000_001, 999_000_000]
        if last_at_end
        else [1_000_000_000 + offset for offset in range(1, count + 1)] + [999_000_000]
    )
    reads: list[tuple[int, int]] = []
    emitted: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bounds = (
            int(request.url.params["start_timestamp"]),
            int(request.url.params["end_timestamp"]),
        )
        reads.append(bounds)
        if probe_fails and bounds == (1000, 1001):
            return httpx.Response(400, json={"error": "history unavailable"})
        return _history_response(request, timestamps_ns)

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://perps.test", transport=httpx.MockTransport(handler)
        ) as client:
            pages = list_internal_transfers(
                AsyncTransport(base_url="https://perps.test", client=client), start=0, end=1001
            )
            expected_error = RequestRejectedError if probe_fails else UnexpectedResponseError
            with pytest.raises(expected_error):
                async for item in pages.iter_items():
                    emitted.append(item.transfer_id)

    asyncio.run(run())
    assert len(emitted) == len(set(emitted)) == 500
    assert count + 1 not in emitted
    assert reads == [(0, 1001), (0, 1001), (1000, 1001)]


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
