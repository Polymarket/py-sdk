import asyncio
import logging

import httpx
import pytest

from polymarket import PublicClient, RateLimitUpdate
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import (
    RateLimitError,
    RequestRejectedError,
    TransportError,
    UnexpectedResponseError,
)


def test_sync_transport_returns_json_payload() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"ok": True}, request=request)
            ),
        ),
    )

    assert transport.get_json("/markets/1") == {"ok": True}


def test_sync_transport_maps_rate_limit_response() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(429, request=request)),
        ),
    )

    with pytest.raises(RateLimitError, match="was rate limited"):
        transport.get_json("/markets/1")


def test_sync_transport_maps_rejected_json_error_response() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400,
                    json={"error": "bad market"},
                    request=request,
                )
            ),
        ),
    )

    with pytest.raises(RequestRejectedError, match="bad market") as exc_info:
        transport.get_json("/markets/1")

    assert exc_info.value.status == 400
    assert exc_info.value.retry_after is None
    assert exc_info.value.restriction is None


def test_sync_transport_exposes_retry_after_header_on_rejection() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503,
                    json={"error": "matching engine restarting"},
                    headers={"Retry-After": "30"},
                    request=request,
                )
            ),
        ),
    )

    with pytest.raises(RequestRejectedError, match="matching engine restarting") as exc_info:
        transport.post_json("/order", json={})

    assert exc_info.value.status == 503
    assert exc_info.value.retry_after == 30.0


def test_sync_transport_exposes_retry_after_seconds_from_body() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503,
                    json={"error": "unavailable", "retry_after_seconds": 2.5},
                    request=request,
                )
            ),
        ),
    )

    with pytest.raises(RequestRejectedError) as exc_info:
        transport.get_json("/markets/1")

    assert exc_info.value.retry_after == 2.5
    assert exc_info.value.restriction is None


def test_sync_transport_flags_restarting_restriction_on_425() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(425, request=request)),
        ),
    )

    with pytest.raises(RequestRejectedError) as exc_info:
        transport.post_json("/order", json={})

    assert exc_info.value.status == 425
    assert exc_info.value.restriction == "restarting"


def test_sync_transport_flags_post_only_restriction_with_body_delay() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503,
                    json={
                        "error": "post-only mode: only post-only orders and cancels are allowed",
                        "code": "post_only_mode",
                        "retry_after_seconds": 79,
                    },
                    request=request,
                )
            ),
        ),
    )

    with pytest.raises(RequestRejectedError, match="post-only mode") as exc_info:
        transport.post_json("/order", json={})

    assert exc_info.value.status == 503
    assert exc_info.value.restriction == "post_only"
    assert exc_info.value.retry_after == 79.0


def test_sync_transport_prefers_retry_after_header_over_body_delay() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503,
                    json={
                        "error": "post-only mode: only post-only orders and cancels are allowed",
                        "code": "post_only_mode",
                        "retry_after_seconds": 79,
                    },
                    headers={"Retry-After": "80"},
                    request=request,
                )
            ),
        ),
    )

    with pytest.raises(RequestRejectedError) as exc_info:
        transport.post_json("/order", json={})

    assert exc_info.value.restriction == "post_only"
    assert exc_info.value.retry_after == 80.0


def test_sync_transport_flags_cancel_only_restriction() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503,
                    json={
                        "error": (
                            "Trading is currently cancel-only. "
                            "New orders are not accepted, but cancels are allowed."
                        )
                    },
                    request=request,
                )
            ),
        ),
    )

    with pytest.raises(RequestRejectedError, match="cancel-only") as exc_info:
        transport.post_json("/order", json={})

    assert exc_info.value.status == 503
    assert exc_info.value.restriction == "cancel_only"
    assert exc_info.value.retry_after is None


def _rejected_with_retry_after(
    header: str, status: int = 503, body: dict[str, object] | None = None
) -> RequestRejectedError | RateLimitError:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    status,
                    json={"error": "unavailable"} if body is None else body,
                    headers={"Retry-After": header},
                    request=request,
                )
            ),
        ),
    )
    with pytest.raises((RequestRejectedError, RateLimitError)) as exc_info:
        transport.get_json("/markets/1")
    return exc_info.value


@pytest.mark.parametrize(
    "header,expected",
    [
        ("0", 0.0),
        ("2.5", 2.5),
        ("1e2", 100.0),
        ("-1", None),
        ("invalid", None),
        ("Thu, 10 Sep 2026 06:02:00 GMT", None),
    ],
)
def test_sync_transport_parses_retry_after_as_delay_seconds_only(
    header: str, expected: float | None
) -> None:
    error = _rejected_with_retry_after(header, status=429)
    assert isinstance(error, RateLimitError)
    assert error.retry_after == expected


def test_sync_transport_uses_body_delay_for_http_date_header() -> None:
    error = _rejected_with_retry_after(
        "Thu, 10 Sep 2026 06:02:00 GMT",
        body={"error": "post-only mode", "code": "post_only_mode", "retry_after_seconds": 79},
    )
    assert isinstance(error, RequestRejectedError)
    assert error.status == 503
    assert error.code == "post_only_mode"
    assert error.retry_after == 79.0


@pytest.mark.parametrize("header_value", ["1e400", "inf", "nan"])
def test_sync_transport_ignores_non_finite_retry_after_header(header_value: str) -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503,
                    json={"error": "unavailable"},
                    headers={"Retry-After": header_value},
                    request=request,
                )
            ),
        ),
    )

    with pytest.raises(RequestRejectedError) as exc_info:
        transport.get_json("/markets/1")

    assert exc_info.value.retry_after is None


@pytest.mark.parametrize(
    "body",
    [
        b'{"error": "unavailable", "retry_after_seconds": Infinity}',
        b'{"error": "unavailable", "retry_after_seconds": 1e400}',
        b'{"error": "unavailable", "retry_after_seconds": ' + b"9" * 400 + b"}",
    ],
)
def test_sync_transport_ignores_out_of_range_retry_after_seconds_in_body(body: bytes) -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503,
                    content=body,
                    headers={"Content-Type": "application/json"},
                    request=request,
                )
            ),
        ),
    )

    with pytest.raises(RequestRejectedError) as exc_info:
        transport.get_json("/markets/1")

    assert exc_info.value.retry_after is None


def test_sync_transport_exposes_rate_limit_state_on_rate_limit_response() -> None:
    updates: list[RateLimitUpdate] = []
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    429,
                    headers={
                        "Retry-After": "3",
                        "Poly-RateLimit-Remaining": "-2",
                        "Poly-RateLimit-Reset": "1784913054",
                        "Poly-RateLimit-Tier": "standard",
                    },
                    request=request,
                )
            ),
        ),
        on_rate_limit_update=updates.append,
    )

    with pytest.raises(RateLimitError) as exc_info:
        transport.post_json("/order", json={})

    expected = RateLimitUpdate(
        remaining=-2.0,
        reset=1784913054.0,
        tier="standard",
        warning=False,
    )
    assert exc_info.value.retry_after == 3.0
    assert exc_info.value.rate_limit == expected
    assert updates == [expected]


def test_sync_transport_notifies_rate_limit_listener() -> None:
    updates: list[RateLimitUpdate] = []
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"ok": True},
                    headers={
                        "Poly-RateLimit-Remaining": "59",
                        "Poly-RateLimit-Reset": "1784913054",
                        "Poly-RateLimit-Tier": "standard",
                        "Poly-RateLimit-Warning": "true",
                    },
                    request=request,
                )
            ),
        ),
        on_rate_limit_update=updates.append,
    )

    assert transport.post_json("/order", json={}) == {"ok": True}
    assert updates == [
        RateLimitUpdate(
            remaining=59.0,
            reset=1784913054.0,
            tier="standard",
            warning=True,
        )
    ]


def test_sync_transport_skips_rate_limit_listener_without_headers() -> None:
    updates: list[RateLimitUpdate] = []
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"ok": True}, request=request)
            ),
        ),
        on_rate_limit_update=updates.append,
    )

    assert transport.get_json("/markets/1") == {"ok": True}
    assert updates == []


def test_sync_transport_ignores_rate_limit_listener_errors() -> None:
    def explode(update: RateLimitUpdate) -> None:
        raise RuntimeError("listener failure")

    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"ok": True},
                    headers={"Poly-RateLimit-Remaining": "10"},
                    request=request,
                )
            ),
        ),
        on_rate_limit_update=explode,
    )

    assert transport.post_json("/order", json={}) == {"ok": True}


def test_sync_transport_maps_non_json_success_response() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text="not json",
                    request=request,
                    headers={"content-type": "text/plain"},
                )
            ),
        ),
    )

    with pytest.raises(UnexpectedResponseError, match="Received non-JSON response"):
        transport.get_json("/markets/1")


def test_sync_transport_maps_transport_failure() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(fail),
        ),
    )

    with pytest.raises(TransportError, match="connection failed") as exc_info:
        transport.get_json("/markets/1")

    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)


def test_async_transport_returns_json_payload() -> None:
    async def run() -> None:
        transport = AsyncTransport(
            base_url="https://example.test",
            client=httpx.AsyncClient(
                base_url="https://example.test",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"ok": True}, request=request)
                ),
            ),
        )

        assert await transport.get_json("/markets/1") == {"ok": True}

    asyncio.run(run())


def test_async_transport_notifies_rate_limit_listener() -> None:
    updates: list[RateLimitUpdate] = []

    async def run() -> None:
        transport = AsyncTransport(
            base_url="https://example.test",
            client=httpx.AsyncClient(
                base_url="https://example.test",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        json={"ok": True},
                        headers={
                            "Poly-RateLimit-Remaining": "59",
                            "Poly-RateLimit-Tier": "standard",
                        },
                        request=request,
                    )
                ),
            ),
            on_rate_limit_update=updates.append,
        )

        assert await transport.post_json("/order", json={}) == {"ok": True}

    asyncio.run(run())
    assert updates == [RateLimitUpdate(remaining=59.0, tier="standard")]


def test_client_accepts_logger_and_logs_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("polymarket-test")
    transport = SyncTransport(
        base_url="https://example.test",
        logger=logger,
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"ok": True}, request=request)
            ),
        ),
    )

    with caplog.at_level(logging.DEBUG, logger="polymarket-test"):
        transport.get_json("/markets/1")

    assert any("GET /markets/1 -> 200" in record.message for record in caplog.records)


def test_client_logger_emits_warning_on_transport_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("polymarket-test-fail")

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = SyncTransport(
        base_url="https://example.test",
        logger=logger,
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(fail),
        ),
    )

    with (
        caplog.at_level(logging.WARNING, logger="polymarket-test-fail"),
        pytest.raises(TransportError),
    ):
        transport.get_json("/markets/1")

    assert any("failed" in record.message for record in caplog.records)


def test_environment_property_is_read_only() -> None:
    with PublicClient() as client, pytest.raises(AttributeError):
        client.environment = client.environment  # type: ignore[misc]


def test_close_does_not_close_injected_client() -> None:
    injected = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True}, request=request)
        ),
    )
    transport = SyncTransport(base_url="https://example.test", client=injected)

    transport.close()

    assert transport.get_json("/markets/1") == {"ok": True}
    injected.close()


def test_close_closes_owned_client() -> None:
    transport = SyncTransport(base_url="https://example.test")

    transport.close()

    with pytest.raises(RuntimeError):
        transport.get_json("/markets/1")


def test_get_bytes_returns_response_content() -> None:
    payload = b"\x50\x4b\x03\x04PAYLOAD"
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=payload, request=request)
            ),
        ),
    )

    assert transport.get_bytes("/snapshot") == payload


def test_get_bytes_maps_error_response() -> None:
    transport = SyncTransport(
        base_url="https://example.test",
        client=httpx.Client(
            base_url="https://example.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(429, request=request)),
        ),
    )

    with pytest.raises(RateLimitError):
        transport.get_bytes("/snapshot")


def test_async_get_bytes_returns_response_content() -> None:
    payload = b"\x50\x4b\x03\x04PAYLOAD"

    async def run() -> bytes:
        transport = AsyncTransport(
            base_url="https://example.test",
            client=httpx.AsyncClient(
                base_url="https://example.test",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, content=payload, request=request)
                ),
            ),
        )
        return await transport.get_bytes("/snapshot")

    assert asyncio.run(run()) == payload


def test_async_close_does_not_close_injected_client() -> None:
    async def run() -> None:
        injected = httpx.AsyncClient(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"ok": True}, request=request)
            ),
        )
        transport = AsyncTransport(base_url="https://example.test", client=injected)

        await transport.close()

        assert await transport.get_json("/markets/1") == {"ok": True}
        await injected.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("base_url", ["https://clob.test", "https://clob.test/prefix/"])
@pytest.mark.parametrize("path,expected", [("/v1/heartbeats", True), ("/other-route", False)])
@pytest.mark.parametrize("heartbeat_id", ["expected-id", ""])
def test_order_heartbeat_rejection_preserves_id_without_retry(
    path: str, expected: bool, heartbeat_id: str, base_url: str
) -> None:
    from polymarket.errors import OrderHeartbeatMismatchError

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            400,
            json={"error_msg": "Invalid Heartbeat ID", "heartbeat_id": heartbeat_id},
            request=request,
        )

    transport = SyncTransport(
        base_url=base_url,
        client=httpx.Client(base_url=base_url, transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RequestRejectedError) as error:
        transport.post_json(path, json={"heartbeat_id": "stale-id"})
    assert isinstance(error.value, OrderHeartbeatMismatchError) is expected
    if isinstance(error.value, OrderHeartbeatMismatchError):
        assert error.value.heartbeat_id == heartbeat_id
    assert len(calls) == 1


@pytest.mark.parametrize("base_url", ["https://clob.test", "https://clob.test/prefix/"])
def test_invalid_heartbeat_payload_has_no_recovery_id(base_url: str) -> None:
    from polymarket.errors import OrderHeartbeatMismatchError

    transport = SyncTransport(
        base_url=base_url,
        client=httpx.Client(
            base_url=base_url,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400, json={"error": "Invalid payload"}, request=request
                )
            ),
        ),
    )
    with pytest.raises(RequestRejectedError, match="Invalid payload") as error:
        transport.post_json("/v1/heartbeats")
    assert not isinstance(error.value, OrderHeartbeatMismatchError)
