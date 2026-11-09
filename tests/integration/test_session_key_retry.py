from unittest.mock import AsyncMock

import pytest
from _session_keys import run_session_key_operation_when_ready

from polymarket import RequestRejectedError

pytestmark = pytest.mark.anyio


def test_parallel_workers_cannot_mutate_shared_wallet(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    with pytest.raises(pytest.fail.Exception, match="Run live session-key tests serially"):
        request.getfixturevalue("serial_session_key_wallet")


async def test_waits_for_previous_wallet_action(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("_session_keys.asyncio.sleep", sleep)
    operation = AsyncMock(
        side_effect=[RequestRejectedError("wallet has in-flight action", status=400), "authorized"]
    )

    assert await run_session_key_operation_when_ready(operation) == "authorized"
    assert operation.await_count == 2
    sleep.assert_awaited_once_with(2)


async def test_busy_wallet_eventually_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("_session_keys.asyncio.sleep", sleep)
    monkeypatch.setattr("_session_keys._WALLET_ACTION_MAX_ATTEMPTS", 3)
    error = RequestRejectedError("wallet has in-flight action", status=400)
    operation = AsyncMock(side_effect=error)

    with pytest.raises(RequestRejectedError) as caught:
        await run_session_key_operation_when_ready(operation)
    assert caught.value is error
    assert operation.await_count == 3
    assert sleep.await_count == 2


async def test_other_rejections_fail_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("_session_keys.asyncio.sleep", sleep)
    error = RequestRejectedError("unauthorized", status=401)
    operation = AsyncMock(side_effect=error)

    with pytest.raises(RequestRejectedError) as caught:
        await run_session_key_operation_when_ready(operation)
    assert caught.value is error
    operation.assert_awaited_once()
    sleep.assert_not_awaited()
