"""Perps account pagination behavior against a mocked transport."""

import asyncio
import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from polymarket._internal.actions.perps import account as perps_account
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UserInputError

_BASE_URL = "https://perps.test"


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> AsyncTransport:
    return AsyncTransport(
        base_url=_BASE_URL,
        client=httpx.AsyncClient(base_url=_BASE_URL, transport=httpx.MockTransport(handler)),
    )


def _cursor(state: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(state, separators=(",", ":")).encode()).decode()


def test_descending_account_paginators_reject_malformed_cursor_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch with a malformed cursor")

    async def run() -> None:
        transport = _transport(handler)
        try:
            fills = perps_account.list_fills(transport)
            bad_fill_cursors: list[dict[str, Any]] = [
                {"kind": "perpsFills", "start_timestamp": 0, "end_timestamp": 1},
                {
                    "kind": "perpsFills",
                    "start_timestamp": 0,
                    "end_timestamp": 1,
                    "seen_keys": [1],
                },
            ]
            for state in bad_fill_cursors:
                with pytest.raises(UserInputError, match="cursor"):
                    await fills.from_cursor(_cursor(state)).first_page()

            deposits = perps_account.list_deposits(transport)
            for deposit_status in ("bogus", "failed"):
                with pytest.raises(UserInputError, match="cursor"):
                    await deposits.from_cursor(
                        _cursor(
                            {
                                "kind": "perpsDeposits",
                                "start_timestamp": 0,
                                "end_timestamp": 1,
                                "seen_keys": [],
                                "deposit_status": deposit_status,
                            }
                        )
                    ).first_page()
        finally:
            await transport.close()

    asyncio.run(run())


def _withdrawal_payload(withdraw_id: int, status: str) -> dict[str, Any]:
    return {
        "withdraw_id": withdraw_id,
        "asset": "USDC",
        "amount": "100.5",
        "fee": "0.5",
        "status": status,
        "to": "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
        "confirmations": 3,
        "required_confirmations": 3,
        "created_timestamp": 1747660800000,
    }


def test_list_withdrawals_parses_failed_and_unknown_statuses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    _withdrawal_payload(1, "failed"),
                    _withdrawal_payload(2, "not-a-status-yet"),
                ],
                "more": False,
            },
        )

    async def run() -> None:
        transport = _transport(handler)
        try:
            page = await perps_account.list_withdrawals(transport).first_page()
            assert [item.status for item in page.items] == ["failed", "not-a-status-yet"]
        finally:
            await transport.close()

    asyncio.run(run())


def test_list_withdrawals_accepts_failed_filter_and_rejects_unknown() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [], "more": False})

    async def run() -> None:
        transport = _transport(handler)
        try:
            await perps_account.list_withdrawals(transport, withdrawal_status="failed").first_page()
            assert captured[0].url.params["withdrawal_status"] == "failed"
            await (
                perps_account.list_withdrawals(transport)
                .from_cursor(
                    _cursor(
                        {
                            "kind": "perpsWithdrawals",
                            "start_timestamp": 0,
                            "end_timestamp": 1,
                            "seen_keys": [],
                            "withdrawal_status": "failed",
                        }
                    )
                )
                .first_page()
            )
            assert captured[1].url.params["withdrawal_status"] == "failed"
            with pytest.raises(UserInputError, match="withdrawal_status"):
                perps_account.list_withdrawals(transport, withdrawal_status="bogus")
        finally:
            await transport.close()

    asyncio.run(run())


def test_ascending_account_paginators_reject_malformed_cursor_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not fetch with a malformed cursor")

    async def run() -> None:
        transport = _transport(handler)
        try:
            pnl = perps_account.list_pnl_history(transport, interval="1h", start=0)
            bad_pnl_cursors: list[dict[str, Any]] = [
                {"kind": "perpsPnlHistory", "interval": "1h", "start_timestamp": 0},
                {
                    "kind": "perpsPnlHistory",
                    "interval": 5,
                    "start_timestamp": 0,
                    "end_timestamp": 1,
                },
            ]
            for state in bad_pnl_cursors:
                with pytest.raises(UserInputError, match="cursor"):
                    await pnl.from_cursor(_cursor(state)).first_page()
        finally:
            await transport.close()

    asyncio.run(run())
