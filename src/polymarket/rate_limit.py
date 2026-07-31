"""Per-signer rate-limit state reported by Polymarket responses."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

import httpx


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


def parse_rate_limit_headers(headers: httpx.Headers) -> RateLimitUpdate | None:
    """Parse the ``Poly-RateLimit-*`` response headers.

    Returns ``None`` when the response carries none of them.
    """
    remaining = _parse_numeric_header(headers.get("Poly-RateLimit-Remaining"))
    reset = _parse_numeric_header(headers.get("Poly-RateLimit-Reset"))
    tier = _parse_text_header(headers.get("Poly-RateLimit-Tier"))
    warning_header = _parse_text_header(headers.get("Poly-RateLimit-Warning"))
    warning = warning_header is not None and warning_header.lower() == "true"

    if remaining is None and reset is None and tier is None and not warning:
        return None

    return RateLimitUpdate(remaining=remaining, reset=reset, tier=tier, warning=warning)


def _parse_numeric_header(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value.strip())
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_text_header(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


__all__ = ["RateLimitUpdate", "RateLimitUpdateListener"]
