import asyncio
from typing import Any

import httpx
import pytest

from polymarket._internal.actions.relayer.poll import poll_until_terminal
from polymarket._internal.actions.relayer.submit import (
    RelayerEnvelope,
    is_retryable_submit_error,
    onchain_nonce_from_submit_error,
    submit_gasless,
)
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import (
    RateLimitError,
    RequestRejectedError,
    TimeoutError,
    TransactionFailedError,
    UnexpectedResponseError,
)
from polymarket.models.clob.relayer import (
    GaslessTransaction,
    RelayerExecuteParams,
    RelayerExecuteResponse,
    RelayerTransactionState,
)


def _transport(handler: httpx.MockTransport) -> AsyncTransport:
    return AsyncTransport(
        base_url="https://relayer.test",
        client=httpx.AsyncClient(base_url="https://relayer.test", transport=handler),
    )


def test_submit_returns_parsed_response_on_success() -> None:
    async def run() -> RelayerExecuteResponse:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-1",
                },
                request=request,
            )

        t = _transport(httpx.MockTransport(handler))
        try:
            return await submit_gasless(t, payload=RelayerEnvelope({"type": "WALLET"}))
        finally:
            await t.close()

    resp = asyncio.run(run())
    assert resp.state == RelayerTransactionState.NEW
    assert resp.transaction_id == "tx-1"
    assert resp.transaction_hash is None


def test_submit_does_not_retry_internally() -> None:
    attempts = 0

    async def run() -> None:
        nonlocal attempts

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                400,
                json={"error": "batch nonce 5 does not match on-chain nonce 7"},
                request=request,
            )

        t = _transport(httpx.MockTransport(handler))
        try:
            await submit_gasless(t, payload=RelayerEnvelope({"type": "WALLET"}))
        finally:
            await t.close()

    with pytest.raises(RequestRejectedError):
        asyncio.run(run())
    assert attempts == 1


def test_is_retryable_submit_error_classification() -> None:
    nonce_behind = RequestRejectedError("batch nonce 5 does not match on-chain nonce 7", status=400)
    assert is_retryable_submit_error(nonce_behind)

    nonce_ahead = RequestRejectedError("batch nonce 9 does not match on-chain nonce 7", status=400)
    assert not is_retryable_submit_error(nonce_ahead)

    wallet_busy = RequestRejectedError("wallet busy: active action in flight", status=400)
    assert is_retryable_submit_error(wallet_busy)

    wallet_inflight = RequestRejectedError("wallet has in-flight action queued", status=400)
    assert is_retryable_submit_error(wallet_inflight)

    unrelated = RequestRejectedError("totally unrelated", status=400)
    assert not is_retryable_submit_error(unrelated)

    server_error = RequestRejectedError("internal", status=500)
    assert not is_retryable_submit_error(server_error)

    assert is_retryable_submit_error(RateLimitError("slow down"))
    assert not is_retryable_submit_error(UnexpectedResponseError("bad json"))


def test_onchain_nonce_from_submit_error_extraction() -> None:
    behind = RequestRejectedError("batch nonce 5 does not match on-chain nonce 7", status=400)
    assert onchain_nonce_from_submit_error(behind) == "7"

    ahead = RequestRejectedError("batch nonce 9 does not match on-chain nonce 7", status=400)
    assert onchain_nonce_from_submit_error(ahead) == "7"

    unrelated = RequestRejectedError("totally unrelated", status=400)
    assert onchain_nonce_from_submit_error(unrelated) is None

    server_error = RequestRejectedError("batch nonce 5 does not match on-chain nonce 7", status=500)
    assert onchain_nonce_from_submit_error(server_error) is None

    assert onchain_nonce_from_submit_error(RateLimitError("slow down")) is None


def test_execute_params_rejects_empty_nonce() -> None:
    with pytest.raises(UnexpectedResponseError, match="RelayerExecuteParams"):
        RelayerExecuteParams.parse_response(
            {"address": "0x0000000000000000000000000000000000000001", "nonce": ""}
        )


def test_execute_params_rejects_non_digit_nonce() -> None:
    with pytest.raises(UnexpectedResponseError, match="RelayerExecuteParams"):
        RelayerExecuteParams.parse_response(
            {"address": "0x0000000000000000000000000000000000000001", "nonce": "abc"}
        )


def test_execute_params_rejects_missing_nonce_key() -> None:
    with pytest.raises(UnexpectedResponseError, match="RelayerExecuteParams"):
        RelayerExecuteParams.parse_response(
            {"address": "0x0000000000000000000000000000000000000001"}
        )


def test_execute_params_accepts_valid_nonce() -> None:
    p = RelayerExecuteParams.parse_response(
        {"address": "0x0000000000000000000000000000000000000001", "nonce": "42"}
    )
    assert p.nonce == "42"


def test_execute_response_parses_missing_transaction_hash_as_none() -> None:
    resp = RelayerExecuteResponse.parse_response({"state": "STATE_NEW", "transactionID": "tx"})
    assert resp.transaction_hash is None
    assert resp.transaction_id == "tx"


def test_gasless_transaction_rejects_missing_transaction_hash_key() -> None:
    with pytest.raises(UnexpectedResponseError, match="GaslessTransaction"):
        GaslessTransaction.parse_response({"state": "STATE_NEW", "transaction_id": "tx"})


def test_gasless_transaction_normalizes_empty_transaction_hash_to_none() -> None:
    tx = GaslessTransaction.parse_response(
        {"state": "STATE_NEW", "transaction_id": "tx", "transaction_hash": ""}
    )
    assert tx.transaction_hash is None


def test_gasless_transaction_preserves_present_transaction_hash() -> None:
    expected = "0x" + "ab" * 32
    tx = GaslessTransaction.parse_response(
        {"state": "STATE_MINED", "transaction_id": "tx", "transaction_hash": expected}
    )
    assert tx.transaction_hash == expected


def test_poll_until_terminal_waits_for_confirmed_after_mined() -> None:
    polls = 0

    async def run() -> Any:
        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal polls
            polls += 1

            return httpx.Response(
                200,
                json={
                    "state": "STATE_MINED" if polls == 1 else "STATE_CONFIRMED",
                    "transaction_hash": "0x" + "ab" * 32,
                    "transaction_id": "tx-7",
                },
                request=request,
            )

        t = _transport(httpx.MockTransport(handler))
        try:
            return await poll_until_terminal(
                t,
                transaction_id="tx-7",
                fallback_hash=None,
                max_polls=3,
                poll_delay_s=0.01,
            )
        finally:
            await t.close()

    outcome = asyncio.run(run())
    assert outcome.transaction_id == "tx-7"
    assert outcome.transaction_hash == "0x" + "ab" * 32
    assert polls == 2


def test_poll_until_terminal_raises_on_failed_state() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "state": "STATE_FAILED",
                    "transaction_hash": "",
                    "transaction_id": "tx-bad",
                    "error_msg": "execution reverted",
                },
                request=request,
            )

        t = _transport(httpx.MockTransport(handler))
        try:
            await poll_until_terminal(
                t,
                transaction_id="tx-bad",
                fallback_hash=None,
                max_polls=3,
                poll_delay_s=0.01,
            )
        finally:
            await t.close()

    with pytest.raises(TransactionFailedError, match="execution reverted"):
        asyncio.run(run())


def test_poll_until_terminal_times_out_after_max_polls() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transaction_hash": "",
                    "transaction_id": "tx-pending",
                },
                request=request,
            )

        t = _transport(httpx.MockTransport(handler))
        try:
            await poll_until_terminal(
                t,
                transaction_id="tx-pending",
                fallback_hash=None,
                max_polls=2,
                poll_delay_s=0.01,
            )
        finally:
            await t.close()

    with pytest.raises(TimeoutError, match="tx-pending"):
        asyncio.run(run())


def test_poll_falls_back_to_submit_hash_when_response_hash_missing() -> None:
    async def run() -> Any:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": "",
                    "transaction_id": "tx-9",
                },
                request=request,
            )

        t = _transport(httpx.MockTransport(handler))
        try:
            return await poll_until_terminal(
                t,
                transaction_id="tx-9",
                fallback_hash="0x" + "cd" * 32,
                max_polls=3,
                poll_delay_s=0.01,
            )
        finally:
            await t.close()

    outcome = asyncio.run(run())
    assert outcome.transaction_hash == "0x" + "cd" * 32
