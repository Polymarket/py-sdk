"""Per-signer rate-limit state reported by Polymarket responses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitUpdate:
    """Per-signer rate-limit state reported by a response.

    Fields mirror the ``Poly-RateLimit-*`` response headers, as sent with order
    and cancellation responses. Each optional field is populated independently,
    so any subset can be present depending on how the request was evaluated.

    ``remaining`` is the token balance left in the applicable rate-limit bucket
    after the request was accounted for; it can be negative for tiers that
    allow a negative cancellation balance. ``reset`` is the Unix timestamp, in
    seconds, when the current rate-limit wait period ends. ``tier`` is the
    rate-limit tier applied to the request. ``warning`` is ``True`` when the
    limiter runs in warning mode and the request would have been rejected under
    live enforcement; monitor it to adjust request patterns before enforcement
    begins.
    """

    remaining: float | None = None
    reset: float | None = None
    tier: str | None = None
    warning: bool = False


RateLimitUpdateListener: TypeAlias = Callable[[RateLimitUpdate], None]
"""Listener invoked whenever a response reports per-signer rate-limit state."""


__all__ = ["RateLimitUpdate", "RateLimitUpdateListener"]
