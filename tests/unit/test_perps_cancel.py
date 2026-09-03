# pyright: reportPrivateUsage=false
"""Typed Perps cancellation and bounded retry behavior."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from polymarket import (
    PerpsCancelOrderErrorCode,
    PerpsCancelOrderRejection,
    PerpsCancelOrderSuccess,
    PerpsCancelRetryOptions,
)
from polymarket._internal import perps_session
from polymarket._internal.perps_session import PerpsSession
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.perps.credentials import PerpsCredentials

_PRIVATE_KEY = "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_PROXY = "0x14791697260E4c9A71f18484C9f997B308e59325"
_CLIENT_ORDER_ID_A = "aabbccddeeff00112233445566778899"
_CLIENT_ORDER_ID_B = "00112233445566778899aabbccddeeff"

_CREDENTIALS = PerpsCredentials(
    proxy=_PROXY,
    private_key=_PRIVATE_KEY,
    secret="session-secret",
    expires_at=datetime(2030, 1, 1, tzinfo=UTC),
)


def _session() -> PerpsSession:
    return PerpsSession(
        chain_id=137,
        credentials=_CREDENTIALS,
        rest_url="https://perps.test",
        ws_url="ws://127.0.0.1:9",
    )


def _stub_cancel_responses(
    monkeypatch: pytest.MonkeyPatch,
    session: PerpsSession,
    responses: list[list[dict[str, object]]],
) -> list[list[Any]]:
    commands: list[list[Any]] = []
    response_index = 0

    async def send_signed_command(
        op: list[Any],
        *,
        parse: Callable[[object], Any],
        timeout_message: str,
        expires_at: datetime | int | None = None,
    ) -> Any:
        nonlocal response_index
        del timeout_message, expires_at
        commands.append(op)
        if response_index >= len(responses):
            raise AssertionError("unexpected Perps cancellation attempt")
        response = responses[response_index]
        response_index += 1
        return parse(response)

    monkeypatch.setattr(session, "_send_signed_command", send_signed_command)
    return commands


def _no_delay(attempt: int, *, base_s: float, max_s: float) -> float:
    del attempt, base_s, max_s
    return 0.0


def test_cancel_rejections_require_a_known_error_code() -> None:
    with pytest.raises(UnexpectedResponseError):
        perps_session._parse_cancel_results([{"status": "err", "error": "new"}])


def test_cancel_results_require_a_list_response() -> None:
    with pytest.raises(UnexpectedResponseError):
        perps_session._parse_cancel_results({"status": "ok"})


def test_retries_only_in_flight_batch_results_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(perps_session, "jittered_backoff", _no_delay)

    async def run() -> None:
        session = _session()
        commands = _stub_cancel_responses(
            monkeypatch,
            session,
            [
                [
                    {"status": "err", "oid": 1, "error": "order_in_flight"},
                    {"status": "err", "oid": 2, "error": "order_not_found"},
                    {"status": "ok", "oid": 3},
                ],
                [{"status": "ok", "oid": 1}],
            ],
        )
        try:
            results = await session.cancel_orders(
                order_ids=[1, 2, 3],
                retry=PerpsCancelRetryOptions(max_attempts=2, max_elapsed_s=10),
            )
        finally:
            await session.close()

        assert commands == [
            ["cancelOrders", [1, 2, 3]],
            ["cancelOrders", [1]],
        ]
        assert isinstance(results[0], PerpsCancelOrderSuccess)
        assert isinstance(results[1], PerpsCancelOrderRejection)
        assert results[1].error is PerpsCancelOrderErrorCode.ORDER_NOT_FOUND
        assert isinstance(results[2], PerpsCancelOrderSuccess)

    asyncio.run(run())


def test_retry_false_makes_one_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        session = _session()
        commands = _stub_cancel_responses(
            monkeypatch,
            session,
            [[{"status": "err", "oid": 1, "error": "order_in_flight"}]],
        )
        try:
            [result] = await session.cancel_orders(order_ids=[1], retry=False)
        finally:
            await session.close()

        assert isinstance(result, PerpsCancelOrderRejection)
        assert result.error is PerpsCancelOrderErrorCode.ORDER_IN_FLIGHT
        assert len(commands) == 1

    asyncio.run(run())


def test_attempt_limit_returns_the_latest_in_flight_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(perps_session, "jittered_backoff", _no_delay)

    async def run() -> None:
        session = _session()
        commands = _stub_cancel_responses(
            monkeypatch,
            session,
            [
                [{"status": "err", "error": "order_in_flight"}],
                [{"status": "err", "error": "order_in_flight"}],
                [{"status": "err", "oid": 1, "error": "order_in_flight"}],
            ],
        )
        try:
            [result] = await session.cancel_orders(
                order_ids=[1],
                retry=PerpsCancelRetryOptions(max_attempts=3, max_elapsed_s=10),
            )
        finally:
            await session.close()

        assert isinstance(result, PerpsCancelOrderRejection)
        assert result.order_id == 1
        assert len(commands) == 3

    asyncio.run(run())


def test_elapsed_budget_prevents_another_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    def delay(attempt: int, *, base_s: float, max_s: float) -> float:
        del attempt, base_s, max_s
        return 0.1

    monkeypatch.setattr(perps_session, "jittered_backoff", delay)

    async def run() -> None:
        session = _session()
        commands = _stub_cancel_responses(
            monkeypatch,
            session,
            [[{"status": "err", "oid": 1, "error": "order_in_flight"}]],
        )
        try:
            [result] = await session.cancel_orders(
                order_ids=[1],
                retry=PerpsCancelRetryOptions(max_attempts=4, max_elapsed_s=0.05),
            )
        finally:
            await session.close()

        assert isinstance(result, PerpsCancelOrderRejection)
        assert len(commands) == 1

    asyncio.run(run())


def test_expiration_deadline_prevents_another_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(perps_session, "jittered_backoff", _no_delay)

    async def run() -> None:
        session = _session()
        commands = _stub_cancel_responses(
            monkeypatch,
            session,
            [[{"status": "err", "oid": 1, "error": "order_in_flight"}]],
        )
        try:
            [result] = await session.cancel_orders(
                order_ids=[1],
                expires_at=perps_session.now_ms(),
            )
        finally:
            await session.close()

        assert isinstance(result, PerpsCancelOrderRejection)
        assert len(commands) == 1

    asyncio.run(run())


def test_client_order_id_retries_only_the_transient_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(perps_session, "jittered_backoff", _no_delay)

    async def run() -> None:
        session = _session()
        commands = _stub_cancel_responses(
            monkeypatch,
            session,
            [
                [
                    {"status": "err", "coid": _CLIENT_ORDER_ID_A, "error": "order_not_found"},
                    {"status": "err", "coid": _CLIENT_ORDER_ID_B, "error": "order_in_flight"},
                ],
                [{"status": "ok", "coid": _CLIENT_ORDER_ID_B}],
            ],
        )
        try:
            results = await session.cancel_orders(
                client_order_ids=[_CLIENT_ORDER_ID_A, _CLIENT_ORDER_ID_B],
                retry=PerpsCancelRetryOptions(max_attempts=2, max_elapsed_s=10),
            )
        finally:
            await session.close()

        assert commands == [
            ["cancelOrdersCOID", [_CLIENT_ORDER_ID_A, _CLIENT_ORDER_ID_B]],
            ["cancelOrdersCOID", [_CLIENT_ORDER_ID_B]],
        ]
        assert isinstance(results[0], PerpsCancelOrderRejection)
        assert isinstance(results[1], PerpsCancelOrderSuccess)

    asyncio.run(run())


def test_cancel_response_cardinality_must_match_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        session = _session()
        _stub_cancel_responses(
            monkeypatch,
            session,
            [[{"status": "ok", "oid": 1}]],
        )
        try:
            with pytest.raises(UnexpectedResponseError, match="one result per requested order"):
                await session.cancel_orders(order_ids=[1, 2], retry=False)
        finally:
            await session.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "options",
    [
        {"max_attempts": True},
        {"max_attempts": 0},
        {"max_elapsed_s": True},
        {"max_elapsed_s": 0},
        {"max_elapsed_s": float("inf")},
    ],
)
def test_retry_options_reject_invalid_bounds(options: dict[str, object]) -> None:
    with pytest.raises(UserInputError):
        PerpsCancelRetryOptions(**options)  # type: ignore[arg-type]
