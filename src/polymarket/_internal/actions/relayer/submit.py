from __future__ import annotations

import re
from typing import NewType

from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import RateLimitError, RequestRejectedError
from polymarket.models.clob.relayer import RelayerExecuteResponse

GASLESS_SUBMIT_RETRY_ATTEMPTS = 10

# A relayer transaction envelope produced by one of the payload builders in
# ``gasless.py``. The NewType keeps arbitrary dicts from reaching a submit
# endpoint without going through a builder.
RelayerEnvelope = NewType("RelayerEnvelope", dict[str, object])

_NONCE_MISMATCH_RE = re.compile(
    r"batch nonce\s+(\d+)\s+does not match on-chain nonce\s+(\d+)", re.IGNORECASE
)
_WALLET_BUSY_RE = re.compile(r"wallet busy.*active action", re.IGNORECASE)
_WALLET_INFLIGHT_RE = re.compile(r"wallet has in-flight action", re.IGNORECASE)


async def submit_gasless(
    relayer: AsyncTransport, *, payload: RelayerEnvelope
) -> RelayerExecuteResponse:
    data = await relayer.post_json("/submit", json=payload)
    return RelayerExecuteResponse.parse_response(data)


def submit_gasless_sync(
    relayer: SyncTransport, *, payload: RelayerEnvelope
) -> RelayerExecuteResponse:
    data = relayer.post_json("/submit", json=payload)
    return RelayerExecuteResponse.parse_response(data)


def is_retryable_submit_error(error: BaseException) -> bool:
    if isinstance(error, RateLimitError):
        return True
    if not isinstance(error, RequestRejectedError) or error.status != 400:
        return False
    msg = str(error)
    if _WALLET_BUSY_RE.search(msg) or _WALLET_INFLIGHT_RE.search(msg):
        return True
    match = _NONCE_MISMATCH_RE.search(msg)
    if match is None:
        return False
    submitted = int(match.group(1))
    on_chain = int(match.group(2))
    return submitted < on_chain


def onchain_nonce_from_submit_error(error: BaseException) -> str | None:
    if not isinstance(error, RequestRejectedError) or error.status != 400:
        return None
    match = _NONCE_MISMATCH_RE.search(str(error))
    if match is None:
        return None
    return match.group(2)


__all__ = [
    "GASLESS_SUBMIT_RETRY_ATTEMPTS",
    "RelayerEnvelope",
    "is_retryable_submit_error",
    "onchain_nonce_from_submit_error",
    "submit_gasless",
    "submit_gasless_sync",
]
