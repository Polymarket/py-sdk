import asyncio
import threading
import time
from collections.abc import Callable

import pytest
from _bearer import fake_access_token

from polymarket import BearerCredentials
from polymarket._internal.actions.identity import IssuedTokens
from polymarket._internal.auth_session import AsyncAuthSession, SyncAuthSession
from polymarket.errors import RequestRejectedError, TransportError, UnexpectedResponseError

SIGNER = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"
WALLET = "0x00000000000000000000000000000000000000aa"


class FakeClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class RecordedTimers:
    """Capture renewal timers instead of starting threads."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self.callbacks: list[Callable[[], None]] = []

    def __call__(self, delay: float, callback: Callable[[], None]) -> "RecordedTimers":
        self.delays.append(delay)
        self.callbacks.append(callback)
        return self

    def cancel(self) -> None:
        pass


def _token(clock: FakeClock, lifetime: int, **claims: object) -> str:
    return fake_access_token(
        sub=SIGNER,
        wallet=WALLET,
        clob_api_key="trading-key",
        exp=int(clock.now) + lifetime,
        **claims,
    )


def _credentials(clock: FakeClock, lifetime: int = 900) -> BearerCredentials:
    return BearerCredentials(access_token=_token(clock, lifetime), refresh_token="refresh")


def _issued(clock: FakeClock, lifetime: int = 900, **claims: object) -> IssuedTokens:
    return IssuedTokens(
        access_token=_token(clock, lifetime, **claims),
        refresh_token="refresh",
        expires_in=lifetime,
    )


def test_renewal_is_scheduled_from_the_server_lifetime_not_the_local_clock() -> None:
    server = FakeClock()
    # The device clock runs 10 minutes fast relative to the token's ``exp``.
    local = FakeClock(server.now + 600)
    timers = RecordedTimers()
    session = SyncAuthSession(
        credentials=_credentials(server, lifetime=900),
        expires_in=900,
        refresh=lambda _: _issued(server),
        clock=local,
        timer_factory=timers,
    )

    session.start()

    assert len(timers.delays) == 1
    assert abs(timers.delays[0] - 870) < 1e-6


def test_requests_use_the_current_token_until_renewal_is_due() -> None:
    clock = FakeClock()
    calls: list[BearerCredentials] = []
    session = SyncAuthSession(
        credentials=_credentials(clock),
        expires_in=900,
        refresh=lambda current: calls.append(current) or _issued(clock),
        clock=clock,
        timer_factory=RecordedTimers(),
    )
    first = session.ready()
    assert calls == []

    clock.now += 900 - 20
    renewed = session.ready()

    assert len(calls) == 1
    assert renewed != first
    assert session.credentials == renewed


def test_concurrent_callers_share_one_renewal() -> None:
    clock = FakeClock()
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def refresh(_: BearerCredentials) -> IssuedTokens:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(5)
        return _issued(clock)

    session = SyncAuthSession(
        credentials=_credentials(clock),
        expires_in=900,
        refresh=refresh,
        clock=clock,
        timer_factory=RecordedTimers(),
    )
    results: list[BearerCredentials] = []
    threads = [threading.Thread(target=lambda: results.append(session.refresh())) for _ in range(4)]
    threads[0].start()
    started.wait(5)
    for thread in threads[1:]:
        thread.start()
    time.sleep(0.05)
    release.set()
    for thread in threads:
        thread.join(5)

    assert calls == 1
    assert len(results) == 4
    assert len(set(results)) == 1


def test_transient_failures_keep_the_session_and_retry_later() -> None:
    clock = FakeClock()
    timers = RecordedTimers()

    def refresh(_: BearerCredentials) -> IssuedTokens:
        raise RequestRejectedError("unavailable", status=503, retry_after=10)

    session = SyncAuthSession(
        credentials=_credentials(clock),
        expires_in=900,
        refresh=refresh,
        clock=clock,
        timer_factory=timers,
    )
    current = session.credentials

    with pytest.raises(RequestRejectedError):
        session.refresh()

    # The server asked for a longer delay than the inline backoff allows.
    assert timers.delays[-1] == 10
    assert session.ready() == current


def test_rejected_refresh_token_ends_the_session() -> None:
    clock = FakeClock()
    rejection = RequestRejectedError("rejected", status=401, code="invalid_refresh_token")
    changes: list[BearerCredentials] = []

    def refresh(_: BearerCredentials) -> IssuedTokens:
        raise rejection

    session = SyncAuthSession(
        credentials=_credentials(clock),
        expires_in=900,
        refresh=refresh,
        on_credentials_changed=changes.append,
        clock=clock,
        timer_factory=RecordedTimers(),
    )

    with pytest.raises(RequestRejectedError):
        session.refresh()

    with pytest.raises(RequestRejectedError) as error:
        session.ready()
    assert error.value is rejection
    assert changes == []


def test_renewal_for_another_identity_ends_the_session() -> None:
    clock = FakeClock()
    session = SyncAuthSession(
        credentials=_credentials(clock),
        expires_in=900,
        refresh=lambda _: _issued(clock, client_id="other-application"),
        clock=clock,
        timer_factory=RecordedTimers(),
    )

    with pytest.raises(UnexpectedResponseError, match="different identity"):
        session.refresh()
    with pytest.raises(UnexpectedResponseError):
        session.ready()


def test_listener_failures_are_ignored_and_listeners_may_renew_again() -> None:
    clock = FakeClock()
    seen: list[BearerCredentials] = []
    session: SyncAuthSession | None = None

    def listener(credentials: BearerCredentials) -> None:
        seen.append(credentials)
        if len(seen) == 1:
            assert session is not None
            session.refresh()
        raise OSError("disk full")

    session = SyncAuthSession(
        credentials=_credentials(clock),
        expires_in=900,
        refresh=lambda _: _issued(clock),
        on_credentials_changed=listener,
        clock=clock,
        timer_factory=RecordedTimers(),
    )

    renewed = session.refresh()

    assert len(seen) == 2
    assert session.credentials == seen[-1]
    assert renewed == seen[0]


def test_logout_renews_an_expired_token_only_to_revoke_it() -> None:
    clock = FakeClock()
    changes: list[BearerCredentials] = []
    revoked: list[str] = []
    renewal = _issued(clock)
    session = SyncAuthSession(
        credentials=_credentials(clock),
        expires_in=900,
        refresh=lambda _: renewal,
        on_credentials_changed=changes.append,
        clock=clock,
        timer_factory=RecordedTimers(),
    )
    clock.now += 1000

    session.logout(revoked.append)

    assert revoked == [renewal.access_token]
    assert changes == []
    with pytest.raises(TransportError, match="closed"):
        session.ready()


def test_logout_replays_once_after_an_expired_token_rejection() -> None:
    clock = FakeClock()
    renewal = _issued(clock)
    attempts: list[str] = []

    def revoke(access_token: str) -> None:
        attempts.append(access_token)
        if len(attempts) == 1:
            raise RequestRejectedError("expired", status=401, code="expired_access_token")

    session = SyncAuthSession(
        credentials=_credentials(clock),
        expires_in=900,
        refresh=lambda _: renewal,
        clock=clock,
        timer_factory=RecordedTimers(),
    )
    original = session.credentials.access_token

    session.logout(revoke)

    assert attempts == [original, renewal.access_token]


def test_async_concurrent_callers_share_one_renewal_and_failures_reach_listeners() -> None:
    async def run() -> tuple[int, list[BaseException]]:
        clock = FakeClock()
        calls = 0
        failures: list[BaseException] = []

        async def refresh(_: BearerCredentials) -> IssuedTokens:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            if calls > 1:
                raise RequestRejectedError("rejected", status=401, code="invalid_refresh_token")
            return _issued(clock)

        session = AsyncAuthSession(
            credentials=_credentials(clock), expires_in=900, refresh=refresh, clock=clock
        )
        session.on_failure(failures.append)
        results = await asyncio.gather(*(session.refresh() for _ in range(5)))
        assert len(set(results)) == 1
        with pytest.raises(RequestRejectedError):
            await session.refresh()
        session.close()
        return calls, failures

    calls, failures = asyncio.run(run())

    assert calls == 2
    assert [type(error) for error in failures] == [RequestRejectedError]
