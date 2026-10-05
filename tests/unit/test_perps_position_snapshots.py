# pyright: reportPrivateUsage=false
import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from polymarket import AsyncPublicClient
from polymarket._internal.actions.perps.position_snapshots import (
    build_position_snapshot_selection,
    fetch_own_position_snapshots,
)
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import RequestRejectedError, UnexpectedResponseError, UserInputError
from polymarket.models.perps.position_snapshots import (
    PerpsPositionSnapshotFill,
    PerpsPositionSnapshots,
)


def test_snapshot_precision_order_and_discriminator() -> None:
    snapshot = dict(
        position_cycle_id="opaque:cycle",
        side="long",
        started_at=0,
        as_of_at=1234,
        is_closed=True,
        size_after="0",
        entry_price="100.000000000000000001",
        as_of_price="120",
        pnl="20.000000000000000001",
        pnl_percent=None,
        leverage=None,
        chart={"candles": [], "markers": []},
    )
    statuses = [
        "not_found",
        "history_pending",
        "history_limit",
        "resource_limit",
        "temporarily_unavailable",
        "unavailable",
    ]
    response = PerpsPositionSnapshots.parse_response(
        dict(
            history_as_of_at=1234,
            active=[dict(instrument_id=i, status=status) for i, status in enumerate(statuses)],
            history=[
                dict(
                    instrument_id=7, trade_id="18446744073709551615", status="ok", snapshot=snapshot
                )
            ],
        )
    )
    assert [item.status for item in response.active] == statuses
    selected = response.history[0]
    assert selected.status == "ok"
    assert selected.snapshot.pnl == Decimal("20.000000000000000001")
    assert selected.snapshot.started_at == datetime(1970, 1, 1, tzinfo=UTC)
    assert selected.trade_id == "18446744073709551615"
    assert selected.snapshot.leverage is None
    for item in [
        dict(instrument_id=7, trade_id="1", status="ok"),
        dict(instrument_id=7, trade_id="1", status="not_found", snapshot=snapshot),
        dict(instrument_id=7, trade_id="01", status="ok", snapshot=snapshot),
    ]:
        with pytest.raises(UnexpectedResponseError):
            PerpsPositionSnapshots.parse_response(
                dict(history_as_of_at=0, active=[], history=[item])
            )


def test_selection_bounds_and_numeric_duplicate_identity() -> None:
    first = PerpsPositionSnapshotFill(instrument_id=7, trade_id="1", timestamp=0)
    duplicate = PerpsPositionSnapshotFill(instrument_id=7, trade_id="01", timestamp=1)
    with pytest.raises(UserInputError):
        build_position_snapshot_selection(history_fills=(first, duplicate))
    with pytest.raises(UserInputError):
        build_position_snapshot_selection()
    with pytest.raises(UserInputError):
        build_position_snapshot_selection(active_instrument_ids=(1, 1))
    with pytest.raises(UserInputError):
        build_position_snapshot_selection(active_instrument_ids=tuple(range(21)))
    assert build_position_snapshot_selection(
        active_instrument_ids=(4294967295, 0), history_fills=(first,)
    ) == {
        "active_instrument_ids": [4294967295, 0],
        "history_fills": [{"instrument_id": 7, "trade_id": "1", "timestamp": 0}],
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"active_instrument_ids": None},
        {"history_fills": None},
        {"active_instrument_ids": [True]},
        {"active_instrument_ids": [4294967296]},
        {
            "history_fills": [
                PerpsPositionSnapshotFill(
                    instrument_id=1, trade_id="18446744073709551616", timestamp=0
                )
            ]
        },
        {"history_fills": [PerpsPositionSnapshotFill(instrument_id=1, trade_id="+1", timestamp=0)]},
        {
            "history_fills": [
                PerpsPositionSnapshotFill(instrument_id=1, trade_id="1", timestamp=18446744073710)
            ]
        },
        {
            "history_fills": [
                PerpsPositionSnapshotFill(
                    instrument_id=1, trade_id="1", timestamp=datetime(2026, 1, 1)
                )
            ]
        },
    ],
)
def test_invalid_selection(kwargs: dict[str, Any]) -> None:
    with pytest.raises(UserInputError):
        build_position_snapshot_selection(**kwargs)


async def _test_public_client_request_is_anonymous_and_preserves_order() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert "POLYMARKET-PROXY" not in request.headers
        assert "POLYMARKET-SECRET" not in request.headers
        assert request.method == "POST"
        assert request.url.path == "/v1/info/position-snapshots"
        assert json.loads(request.content) == {
            "address": "0x1111111111111111111111111111111111111111",
            "active_instrument_ids": [9, 0],
            "history_fills": [
                {
                    "instrument_id": 7,
                    "trade_id": "18446744073709551615",
                    "timestamp": 18446744073709,
                }
            ],
        }
        return httpx.Response(200, json={"active": [], "history": [], "history_as_of_at": 0})

    async with (
        httpx.AsyncClient(
            base_url="https://perps.test", transport=httpx.MockTransport(handler)
        ) as http,
        AsyncPublicClient() as client,
    ):
        await client._ctx.perps.close()
        client._ctx = replace(
            client._ctx, perps=AsyncTransport(base_url="https://perps.test", client=http)
        )
        await client.fetch_perps_position_snapshots(
            address="0x1111111111111111111111111111111111111111",
            active_instrument_ids=(9, 0),
            history_fills=(
                PerpsPositionSnapshotFill(
                    instrument_id=7, trade_id="18446744073709551615", timestamp=18446744073709
                ),
            ),
        )
    assert len(captured) == 1


async def _test_owner_resolution_and_invalid_auth_do_not_fall_back_to_anonymous() -> None:
    paths: list[str] = []
    denied = False

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["POLYMARKET-PROXY"] == "proxy"
        assert request.headers["POLYMARKET-SECRET"] == "secret"
        if request.url.path == "/v1/account/credentials":
            if denied:
                return httpx.Response(401, json={"error": "invalid credentials"})
            return httpx.Response(
                200, json={"address": "0x1111111111111111111111111111111111111111", "keys": []}
            )
        assert (
            json.loads(request.content)["address"] == "0x1111111111111111111111111111111111111111"
        )
        return httpx.Response(200, json={"active": [], "history": [], "history_as_of_at": 0})

    async def headers(method: str, path: str, body: str | None) -> dict[str, str]:
        return {"POLYMARKET-PROXY": "proxy", "POLYMARKET-SECRET": "secret"}

    async with httpx.AsyncClient(
        base_url="https://perps.test", transport=httpx.MockTransport(handler)
    ) as http:
        api = AsyncTransport(base_url="https://perps.test", client=http, header_resolver=headers)
        with pytest.raises(UserInputError):
            await fetch_own_position_snapshots(api)
        assert paths == []
        await fetch_own_position_snapshots(api, active_instrument_ids=(7,))
        assert paths == ["/v1/account/credentials", "/v1/info/position-snapshots"]
        denied = True
        with pytest.raises(RequestRejectedError):
            await fetch_own_position_snapshots(api, active_instrument_ids=(7,))
        assert paths[-1] == "/v1/account/credentials"
        assert len(paths) == 3


def test_public_client_request_is_anonymous_and_preserves_order() -> None:
    asyncio.run(_test_public_client_request_is_anonymous_and_preserves_order())


def test_owner_resolution_and_invalid_auth_do_not_fall_back_to_anonymous() -> None:
    asyncio.run(_test_owner_resolution_and_invalid_auth_do_not_fall_back_to_anonymous())
