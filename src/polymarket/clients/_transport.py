from __future__ import annotations

import json as _json
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeAlias

import httpx
from httpx import USE_CLIENT_DEFAULT

from polymarket._internal.request import QueryParamValue
from polymarket.errors import (
    OrderHeartbeatMismatchError,
    RateLimitError,
    RequestRejectedError,
    TradingRestriction,
    TransportError,
    UnexpectedResponseError,
)
from polymarket.models.clob.order_heartbeats import OrderHeartbeatMismatchResponse
from polymarket.rate_limit import RateLimitUpdate, RateLimitUpdateListener

SyncHeaderResolver: TypeAlias = Callable[[str, str, str | None], Mapping[str, str]]
HeaderResolver: TypeAlias = Callable[[str, str, str | None], Awaitable[Mapping[str, str]]]

_DEFAULT_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30,
)
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=2.0)


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportOptions:
    limits: httpx.Limits = field(default_factory=lambda: _DEFAULT_LIMITS)
    timeout: httpx.Timeout = field(default_factory=lambda: _DEFAULT_TIMEOUT)
    http2: bool = True
    event_hooks: Mapping[str, list[Any]] | None = None


class SyncTransport:
    def __init__(
        self,
        *,
        base_url: str,
        options: TransportOptions | None = None,
        logger: logging.Logger | None = None,
        client: httpx.Client | None = None,
        header_resolver: SyncHeaderResolver | None = None,
        on_rate_limit_update: RateLimitUpdateListener | None = None,
    ) -> None:
        opts = options or TransportOptions()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=opts.timeout,
            limits=opts.limits,
            http2=opts.http2,
            event_hooks=dict(opts.event_hooks) if opts.event_hooks else None,
        )
        self._logger = logger
        self._header_resolver = header_resolver
        self._on_rate_limit_update = on_rate_limit_update
        self._base_url = base_url

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self._request("GET", path, params=params, headers=headers)
        return _read_json(response)

    def get_bytes(
        self,
        path: str,
        *,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        response = self._request("GET", path, params=params, headers=headers)
        return response.content

    def post_json(
        self,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> Any:
        response = self._request(
            "POST", path, params=params, json=json, headers=headers, timeout=timeout
        )
        return _read_json(response)

    def delete_json(
        self,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self._request("DELETE", path, params=params, json=json, headers=headers)
        return _read_json(response)

    def delete(
        self,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._request("DELETE", path, params=params, json=json, headers=headers)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, QueryParamValue | None] | None = None,
        json: object | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        body_str: str | None = None
        content: bytes | None = None
        merged_headers: dict[str, str] = dict(headers) if headers else {}

        if json is not None:
            body_str = _json.dumps(json, separators=(",", ":"))
            content = body_str.encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")

        if self._header_resolver is not None:
            resolved = self._header_resolver(method, path, body_str)
            merged_headers.update(resolved)

        started = time.perf_counter()
        try:
            response = self._client.request(
                method,
                self._base_url if path == "" else path,
                params=_clean_params(params),
                content=content,
                headers=merged_headers or None,
                timeout=timeout if timeout is not None else USE_CLIENT_DEFAULT,
            )
        except httpx.HTTPError as error:
            _log_failure(self._logger, method, path, error, started)
            raise TransportError(str(error) or "Request failed") from error

        _log_response(self._logger, method, path, response, started)
        _notify_rate_limit_update(self._on_rate_limit_update, self._logger, response)
        _raise_for_response_status(response)
        return response


class AsyncTransport:
    def __init__(
        self,
        *,
        base_url: str,
        options: TransportOptions | None = None,
        logger: logging.Logger | None = None,
        client: httpx.AsyncClient | None = None,
        header_resolver: HeaderResolver | None = None,
        on_rate_limit_update: RateLimitUpdateListener | None = None,
    ) -> None:
        opts = options or TransportOptions()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=opts.timeout,
            limits=opts.limits,
            http2=opts.http2,
            event_hooks=dict(opts.event_hooks) if opts.event_hooks else None,
        )
        self._logger = logger
        self._header_resolver = header_resolver
        self._on_rate_limit_update = on_rate_limit_update
        self._base_url = base_url

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = await self._request("GET", path, params=params, headers=headers)
        return _read_json(response)

    async def get_bytes(
        self,
        path: str,
        *,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        response = await self._request("GET", path, params=params, headers=headers)
        return response.content

    async def post_json(
        self,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> Any:
        response = await self._request(
            "POST", path, params=params, json=json, headers=headers, timeout=timeout
        )
        return _read_json(response)

    async def patch_json(
        self,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = await self._request("PATCH", path, params=params, json=json, headers=headers)
        return _read_json(response)

    async def delete_json(
        self,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = await self._request("DELETE", path, params=params, json=json, headers=headers)
        return _read_json(response)

    async def delete(
        self,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        await self._request("DELETE", path, params=params, json=json, headers=headers)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, QueryParamValue | None] | None = None,
        json: object | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        body_str: str | None = None
        content: bytes | None = None
        merged_headers: dict[str, str] = dict(headers) if headers else {}

        if json is not None:
            body_str = _json.dumps(json, separators=(",", ":"))
            content = body_str.encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")

        if self._header_resolver is not None:
            resolved = await self._header_resolver(method, path, body_str)
            merged_headers.update(resolved)

        started = time.perf_counter()
        try:
            response = await self._client.request(
                method,
                self._base_url if path == "" else path,
                params=_clean_params(params),
                content=content,
                headers=merged_headers or None,
                timeout=timeout if timeout is not None else USE_CLIENT_DEFAULT,
            )
        except httpx.HTTPError as error:
            _log_failure(self._logger, method, path, error, started)
            raise TransportError(str(error) or "Request failed") from error

        _log_response(self._logger, method, path, response, started)
        _notify_rate_limit_update(self._on_rate_limit_update, self._logger, response)
        _raise_for_response_status(response)
        return response


def _log_response(
    logger: logging.Logger | None,
    method: str,
    path: str,
    response: httpx.Response,
    started: float,
) -> None:
    if logger is None or not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug(
        "polymarket http %s %s -> %d in %.1fms",
        method,
        path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )


def _log_failure(
    logger: logging.Logger | None,
    method: str,
    path: str,
    error: Exception,
    started: float,
) -> None:
    if logger is None:
        return
    logger.warning(
        "polymarket http %s %s failed in %.1fms: %s",
        method,
        path,
        (time.perf_counter() - started) * 1000,
        error,
    )


def _parse_rate_limit_headers(headers: httpx.Headers) -> RateLimitUpdate | None:
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


def _notify_rate_limit_update(
    listener: RateLimitUpdateListener | None,
    logger: logging.Logger | None,
    response: httpx.Response,
) -> None:
    if listener is None:
        return

    update = _parse_rate_limit_headers(response.headers)
    if update is None:
        return

    try:
        listener(update)
    except Exception:
        if logger is not None:
            logger.warning("polymarket rate-limit update listener failed", exc_info=True)


def _raise_for_response_status(response: httpx.Response) -> None:
    if response.is_success:
        return

    if response.status_code == 429:
        raise RateLimitError(
            f"Request to {response.url} was rate limited",
            retry_after=_extract_retry_after(response),
            rate_limit=_parse_rate_limit_headers(response.headers),
        )

    if response.status_code == 400 and response.url.path == "/v1/heartbeats":
        try:
            mismatch = OrderHeartbeatMismatchResponse.model_validate(response.json())
        except ValueError:
            pass
        else:
            raise OrderHeartbeatMismatchError(mismatch.heartbeat_id)

    raise RequestRejectedError(
        _extract_response_error_message(response),
        status=response.status_code,
        code=_extract_response_error_code(response),
        retry_after=_extract_retry_after(response),
        restriction=_detect_trading_restriction(response),
    )


_HTTP_DATE_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_HTTP_DATE_MONTH = "(?P<month>" + "|".join(_HTTP_DATE_MONTHS) + ")"
_HTTP_DATE_TIME = r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
# RFC 9110 section 5.6.7: recipients accept IMF-fixdate and the two obsolete
# forms. The fields are read as UTC here so the three forms behave alike.
_HTTP_DATE_PATTERNS = (
    re.compile(
        r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), (?P<day>\d{2}) "
        + _HTTP_DATE_MONTH
        + r" (?P<year>\d{4}) "
        + _HTTP_DATE_TIME
        + r" GMT$"
    ),
    re.compile(
        r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), (?P<day>\d{2})-"
        + _HTTP_DATE_MONTH
        + r"-(?P<year>\d{2}) "
        + _HTTP_DATE_TIME
        + r" GMT$"
    ),
    re.compile(
        r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
        + _HTTP_DATE_MONTH
        + r" (?P<day> \d|\d{2}) "
        + _HTTP_DATE_TIME
        + r" (?P<year>\d{4})$"
    ),
)
_FIFTY_YEARS_S = 50 * 365.25 * 24 * 60 * 60


def _parse_http_date(value: str, now: float) -> float | None:
    """Return the epoch seconds of an RFC 9110 HTTP-date, or None when malformed.

    A two-digit year more than fifty years in the future is read as the most
    recent past year with those digits.
    """
    for pattern in _HTTP_DATE_PATTERNS:
        match = pattern.match(value)
        if match is not None:
            break
    else:
        return None
    groups = match.groupdict()
    month = _HTTP_DATE_MONTHS.index(groups["month"]) + 1
    day, hour, minute, second = (int(groups[name]) for name in ("day", "hour", "minute", "second"))
    year_digits = groups["year"]
    year = int(year_digits)
    try:
        if len(year_digits) == 2:
            year += datetime.fromtimestamp(now, UTC).year // 100 * 100
            deadline = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
            if deadline.timestamp() - now > _FIFTY_YEARS_S:
                year -= 100
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC).timestamp()
    except (ValueError, OverflowError):
        return None


def _parse_retry_after_header(header: str, now: float) -> float | None:
    try:
        seconds = float(header.strip())
    except ValueError:
        seconds = None
    if seconds is not None:
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    # RFC 9110 section 10.2.3 also allows an HTTP-date. Report whole seconds
    # from now, never rounding a future deadline down, and clamp past dates.
    deadline = _parse_http_date(header.strip(), now)
    if deadline is None:
        return None
    return float(max(0, math.ceil(deadline - now)))


def _extract_retry_after(response: httpx.Response) -> float | None:
    header = response.headers.get("retry-after")
    if header is not None:
        seconds = _parse_retry_after_header(header, time.time())
        if seconds is not None:
            return seconds

    if "application/json" in response.headers.get("content-type", "").lower():
        try:
            value = response.json().get("retry_after_seconds")
        except (AttributeError, ValueError):
            value = None
        if isinstance(value, int | float) and not isinstance(value, bool):
            try:
                seconds = float(value)
            except OverflowError:
                seconds = None
            if seconds is not None and math.isfinite(seconds) and seconds >= 0:
                return seconds

    return None


def _detect_trading_restriction(response: httpx.Response) -> TradingRestriction | None:
    if response.status_code == 425:
        return "restarting"
    if response.status_code != 503:
        return None

    if "application/json" not in response.headers.get("content-type", "").lower():
        return None
    try:
        body = response.json()
        code = body.get("code")
        error = body.get("error")
    except (AttributeError, ValueError):
        return None
    if code == "post_only_mode":
        return "post_only"
    # Cancel-only responses carry no structured code, only the message text.
    if isinstance(error, str) and "cancel-only" in error:
        return "cancel_only"
    return None


def _clean_params(
    params: Mapping[str, QueryParamValue | None] | None,
) -> dict[str, QueryParamValue] | None:
    if params is None:
        return None

    return {key: value for key, value in params.items() if value is not None}


def _read_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as error:
        raise UnexpectedResponseError(f"Received non-JSON response from {response.url}") from error


def _extract_response_error_code(response: httpx.Response) -> str | None:
    if "application/json" not in response.headers.get("content-type", "").lower():
        return None
    try:
        code = response.json().get("code")
    except (AttributeError, ValueError):
        return None
    if isinstance(code, str) and code:
        return code
    return None


def _extract_response_error_message(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "").lower()

    if "application/json" in content_type:
        try:
            error = response.json().get("error")
        except (AttributeError, ValueError):
            error = None
        if error:
            return str(error)

    if "text/plain" in content_type:
        text = response.text.strip()
        if text:
            return text

    server = response.headers.get("server", "").lower()
    if "cloudflare" in server:
        return (
            f"Request to {response.url} was blocked by Cloudflare "
            f"with status {response.status_code}"
        )

    if "text/html" in content_type or "application/xhtml+xml" in content_type:
        return (
            f"Request to {response.url} failed with status {response.status_code} "
            "and an unexpected HTML response body"
        )

    return (
        f"Request to {response.url} failed with status {response.status_code} "
        "and unreadable response body"
    )
