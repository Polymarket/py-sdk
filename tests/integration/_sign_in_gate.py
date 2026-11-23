"""Test-only sign-in gate for live integration tests.

After a login, the API rejects a new sign-in challenge for the same signer and
nonce with ``409 challenge_consumed`` for a short window, whatever the wallet.
Live tests reuse one test signer across files, so back-to-back sign-ins would
fail. The gate wraps ``httpx`` sends to space those challenges out and resends a
challenge that is still rejected. The SDK itself never retries sign-in.

It is installed below any ``send`` patch a test adds, so those still observe
exactly one challenge per sign-in.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from typing import Any, cast

import httpx
import pytest

# Time to wait after a login before requesting another challenge for the same
# signer and nonce.
SIGN_IN_COOLDOWN_S = 2.0
# Delay before resending a challenge that is still rejected, unless the API
# sends Retry-After.
_RETRY_DELAY_S = 0.5
# How long to keep resending a rejected challenge before letting it through.
_MAX_RETRY_WINDOW_S = 10.0

_CHALLENGE_PATH = "/v1/auth/challenge"
_LOGIN_PATH = "/v1/auth/login"


class _SignInGate:
    def __init__(self) -> None:
        # Signer and nonce of each challenge this gate let through.
        self._challenge_keys: dict[str, str] = {}
        # Last successful login per signer and nonce.
        self._sign_ins: dict[str, float] = {}

    def wrap_sync(self, send: Callable[..., httpx.Response]) -> Callable[..., httpx.Response]:
        gate = self

        def gated_send(
            client: httpx.Client, request: httpx.Request, *args: Any, **kwargs: Any
        ) -> httpx.Response:
            key = gate._challenge_key(request)
            if key is not None:
                time.sleep(gate._remaining_cooldown(key))
                deadline = time.monotonic() + _MAX_RETRY_WINDOW_S
                while True:
                    response = send(client, request, *args, **kwargs)
                    wait = gate._resend_delay(response, key, deadline)
                    if wait is None:
                        return response
                    time.sleep(wait)
            response = send(client, request, *args, **kwargs)
            gate._record_login(request, response)
            return response

        return gated_send

    def wrap_async(
        self, send: Callable[..., Awaitable[httpx.Response]]
    ) -> Callable[..., Awaitable[httpx.Response]]:
        gate = self

        async def gated_send(
            client: httpx.AsyncClient, request: httpx.Request, *args: Any, **kwargs: Any
        ) -> httpx.Response:
            key = gate._challenge_key(request)
            if key is not None:
                await asyncio.sleep(gate._remaining_cooldown(key))
                deadline = time.monotonic() + _MAX_RETRY_WINDOW_S
                while True:
                    response = await send(client, request, *args, **kwargs)
                    wait = gate._resend_delay(response, key, deadline)
                    if wait is None:
                        return response
                    await asyncio.sleep(wait)
            response = await send(client, request, *args, **kwargs)
            gate._record_login(request, response)
            return response

        return gated_send

    def _challenge_key(self, request: httpx.Request) -> str | None:
        if request.method != "POST" or not request.url.path.endswith(_CHALLENGE_PATH):
            return None
        body = _json(request.content)
        signer = body.get("signer")
        if not isinstance(signer, str):
            return None
        # An omitted nonce is nonce 0.
        nonce = body.get("nonce", 0)
        return f"{signer.lower()}:{nonce}"

    def _remaining_cooldown(self, key: str) -> float:
        last = self._sign_ins.get(key)
        if last is None:
            return 0.0
        return max(0.0, last + SIGN_IN_COOLDOWN_S - time.monotonic())

    def _resend_delay(self, response: httpx.Response, key: str, deadline: float) -> float | None:
        """Delay before resending the challenge, or ``None`` to return the response."""
        if response.is_success:
            challenge_id = _json(response.content).get("challenge_id")
            if isinstance(challenge_id, str):
                self._challenge_keys[challenge_id] = key
            return None
        if response.status_code != 409 or _json(response.content).get("code") != (
            "challenge_consumed"
        ):
            return None
        wait = _retry_after(response)
        wait = _RETRY_DELAY_S if wait is None else wait
        if time.monotonic() + wait > deadline:
            return None
        return wait

    def _record_login(self, request: httpx.Request, response: httpx.Response) -> None:
        if request.method != "POST" or not request.url.path.endswith(_LOGIN_PATH):
            return
        if not response.is_success:
            return
        ownership: object = _json(request.content).get("ownership")
        challenge_id: object = (
            cast(dict[str, object], ownership).get("challenge_id")
            if isinstance(ownership, dict)
            else None
        )
        key = self._challenge_keys.get(challenge_id) if isinstance(challenge_id, str) else None
        if key is not None:
            self._sign_ins[key] = time.monotonic()


def _json(content: bytes) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return {}
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


@contextmanager
def install_sign_in_gate() -> Generator[None, None, None]:
    """Gate sign-ins for the duration of the block."""
    gate = _SignInGate()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx.Client, "send", gate.wrap_sync(httpx.Client.send))
        patch.setattr(httpx.AsyncClient, "send", gate.wrap_async(httpx.AsyncClient.send))
        yield
