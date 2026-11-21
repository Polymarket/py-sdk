import asyncio

import httpx
import pytest

from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import OrderHeartbeatMismatchError, RateLimitError, RequestRejectedError


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "status,path,body,error_type",
    [
        (
            400,
            "/v2/value",
            {"error": "invalid user", "code": "invalid_request"},
            RequestRejectedError,
        ),
        (503, "/v2/value", {"error": "unavailable"}, RequestRejectedError),
        (429, "/v2/value", {"error": "slow down"}, RateLimitError),
        (
            400,
            "/v1/heartbeats",
            {"error_msg": "Invalid Heartbeat ID", "heartbeat_id": "expected"},
            OrderHeartbeatMismatchError,
        ),
    ],
)
def test_response_errors_preserve_metadata(
    mode: str, status: int, path: str, body: dict[str, object], error_type: type[Exception]
) -> None:
    payload = {**body, "retryable": False, "trace_id": "body-trace", "parameter": "user"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json=payload, headers={"x-trace-id": "header-trace", "Retry-After": "2"}
        )

    async def run_async() -> None:
        async with httpx.AsyncClient(
            base_url="https://example.test", transport=httpx.MockTransport(handler)
        ) as http:
            await AsyncTransport(base_url="https://example.test", client=http).get_json(path)

    with pytest.raises(error_type) as caught:
        if mode == "sync":
            with httpx.Client(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            ) as http:
                SyncTransport(base_url="https://example.test", client=http).get_json(path)
        else:
            asyncio.run(run_async())
    error = caught.value
    assert isinstance(error, RequestRejectedError | RateLimitError)
    assert error.retryable is False
    assert error.trace_id == "body-trace"
    assert error.parameter == "user"
    if isinstance(error, OrderHeartbeatMismatchError):
        assert error.heartbeat_id == "expected"
    else:
        assert error.retry_after == 2


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "content,content_type,expected",
    [
        (
            b'{"retryable":true,"trace_id":"body","parameter":"user"}',
            "application/json",
            (True, "body", "user"),
        ),
        (
            b'{"retryable":0,"trace_id":42,"parameter":[]}',
            "application/json",
            (None, "header", None),
        ),
        (
            b'{"retryable":"false","trace_id":" ","parameter":""}',
            "application/json",
            (None, "header", None),
        ),
        (
            b'{"retryable":null,"trace_id":null,"parameter":null}',
            "application/json",
            (None, "header", None),
        ),
        (b"{}", "application/json", (None, None, None)),
        (b"[]", "application/json", (None, "header", None)),
        (b"null", "application/json", (None, "header", None)),
        (b"{", "application/json", (None, "header", None)),
        (b'{"retryable":true,"trace_id":"body"}', "text/plain", (None, "header", None)),
    ],
)
def test_error_metadata_validates_types_and_falls_back_to_header(
    mode: str,
    content: bytes,
    content_type: str,
    expected: tuple[bool | None, str | None, str | None],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            content=content,
            headers={
                "Content-Type": content_type,
                **({"X-Trace-ID": "header"} if content != b"{}" else {}),
            },
        )

    async def run_async() -> None:
        async with httpx.AsyncClient(
            base_url="https://example.test", transport=httpx.MockTransport(handler)
        ) as http:
            await AsyncTransport(base_url="https://example.test", client=http).get_json("/v2/value")

    with pytest.raises(RequestRejectedError) as caught:
        if mode == "sync":
            with httpx.Client(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            ) as http:
                SyncTransport(base_url="https://example.test", client=http).get_json("/v2/value")
        else:
            asyncio.run(run_async())
    assert (caught.value.retryable, caught.value.trace_id, caught.value.parameter) == expected
