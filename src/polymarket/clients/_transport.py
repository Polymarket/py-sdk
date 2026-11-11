from __future__ import annotations

import json as _json
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeAlias, cast

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
# Called with the access token a request used after the server rejected it as expired.
SyncExpiredTokenRecovery: TypeAlias = Callable[[str], None]
ExpiredTokenRecovery: TypeAlias = Callable[[str], Awaitable[None]]

_AUTH_PATH_PREFIX = "/v1/auth/"
_EXPIRED_ACCESS_TOKEN = "expired_access_token"
_SECRET_HEADER = re.compile(r"authorization|api.?key|passphrase|signature|secret", re.IGNORECASE)
# Body fields that carry credentials. Identifiers such as ``token_id`` stay readable.
_CREDENTIAL_BODY_FIELD = re.compile(
    r"^(?:access|refresh|verification)_?token$|secret|passphrase|signature|api.?key|^key$",
    re.IGNORECASE,
)
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]*")
_REDACTED = "[REDACTED]"
_AUTH_REJECTED_MESSAGE = "Authentication request rejected."
_AUTH_TRANSPORT_MESSAGE = "Authentication transport failed."

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
        recover_expired_token: SyncExpiredTokenRecovery | None = None,
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
        self._recover_expired_token = recover_expired_token
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

    def post(
        self,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._request("POST", path, params=params, json=json, headers=headers)

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

        # Replays reuse the serialized body and resolve headers again for the new attempt.
        replayed = False
        while True:
            attempt_headers = dict(merged_headers)
            if self._header_resolver is not None:
                attempt_headers.update(self._header_resolver(method, path, body_str))
            secrets = _request_secrets(attempt_headers, json)

            started = time.perf_counter()
            outcome: httpx.Response | httpx.HTTPError
            try:
                outcome = self._client.request(
                    method,
                    self._base_url if path == "" else path,
                    params=_clean_params(params),
                    content=content,
                    headers=attempt_headers or None,
                    timeout=timeout if timeout is not None else USE_CLIENT_DEFAULT,
                )
            except httpx.HTTPError as error:
                outcome = error
            if isinstance(outcome, httpx.HTTPError):
                # Raised outside the handler so a credentialed request keeps no reference
                # to the failed request and its headers. Only the redacted error is logged.
                failure = _transport_error(outcome, path=path, secrets=secrets)
                _log_failure(self._logger, method, path, failure, started)
                raise failure
            response = outcome

            _log_response(self._logger, method, path, response, started)
            _notify_rate_limit_update(self._on_rate_limit_update, self._logger, response)
            expired_token = _expired_access_token(response, path=path, headers=attempt_headers)
            if replayed or self._recover_expired_token is None or expired_token is None:
                break
            self._recover_expired_token(expired_token)
            replayed = True

        _raise_for_response_status(response, path=path, secrets=secrets)
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
        recover_expired_token: ExpiredTokenRecovery | None = None,
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
        self._recover_expired_token = recover_expired_token
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

    async def post(
        self,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, QueryParamValue | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        await self._request("POST", path, params=params, json=json, headers=headers)

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

        # Replays reuse the serialized body and resolve headers again for the new attempt.
        replayed = False
        while True:
            attempt_headers = dict(merged_headers)
            if self._header_resolver is not None:
                attempt_headers.update(await self._header_resolver(method, path, body_str))
            secrets = _request_secrets(attempt_headers, json)

            started = time.perf_counter()
            outcome: httpx.Response | httpx.HTTPError
            try:
                outcome = await self._client.request(
                    method,
                    self._base_url if path == "" else path,
                    params=_clean_params(params),
                    content=content,
                    headers=attempt_headers or None,
                    timeout=timeout if timeout is not None else USE_CLIENT_DEFAULT,
                )
            except httpx.HTTPError as error:
                outcome = error
            if isinstance(outcome, httpx.HTTPError):
                # Raised outside the handler so a credentialed request keeps no reference
                # to the failed request and its headers. Only the redacted error is logged.
                failure = _transport_error(outcome, path=path, secrets=secrets)
                _log_failure(self._logger, method, path, failure, started)
                raise failure
            response = outcome

            _log_response(self._logger, method, path, response, started)
            _notify_rate_limit_update(self._on_rate_limit_update, self._logger, response)
            expired_token = _expired_access_token(response, path=path, headers=attempt_headers)
            if replayed or self._recover_expired_token is None or expired_token is None:
                break
            await self._recover_expired_token(expired_token)
            replayed = True

        _raise_for_response_status(response, path=path, secrets=secrets)
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


def _request_secrets(headers: Mapping[str, str], body: object) -> tuple[str, ...]:
    secrets: list[str] = []
    for name, value in headers.items():
        if not value or not _SECRET_HEADER.search(name):
            continue
        secrets.append(value)
        scheme, _, token = value.partition(" ")
        if scheme.lower() == "bearer" and token:
            secrets.append(token)
    _collect_body_secrets(body, secrets)
    return tuple(secret for secret in secrets if secret)


def _collect_body_secrets(value: object, secrets: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, field in cast(Mapping[object, object], value).items():
            if (
                isinstance(field, str)
                and isinstance(key, str)
                and _CREDENTIAL_BODY_FIELD.search(key)
            ):
                secrets.append(field)
            else:
                _collect_body_secrets(field, secrets)
    elif isinstance(value, list | tuple):
        for item in cast(list[object] | tuple[object, ...], value):
            _collect_body_secrets(item, secrets)


def _safe_error_code(code: str | None, secrets: tuple[str, ...]) -> str | None:
    if code is None or _redact(code, secrets) != code:
        return None
    return code


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    # HTTP errors can quote a header value in its escaped str or bytes form.
    forms = {
        form
        for secret in secrets
        for form in (secret, repr(secret)[1:-1], repr(secret.encode())[2:-1])
        if form
    }
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, _REDACTED)
    return text


def _auth_error_code(response: httpx.Response, secrets: tuple[str, ...]) -> str | None:
    code = _safe_error_code(_extract_response_error_code(response), secrets)
    if code is None or _ERROR_CODE.fullmatch(code) is None:
        return None
    return code


def _is_auth_path(path: str) -> bool:
    return path.startswith(_AUTH_PATH_PREFIX)


def _transport_error(
    error: httpx.HTTPError, *, path: str, secrets: tuple[str, ...]
) -> TransportError:
    if _is_auth_path(path):
        return TransportError(_AUTH_TRANSPORT_MESSAGE)
    message = str(error) or "Request failed"
    if secrets:
        return TransportError(_redact(message, secrets))
    transport_error = TransportError(message)
    transport_error.__cause__ = error
    return transport_error


def _expired_access_token(
    response: httpx.Response, *, path: str, headers: Mapping[str, str]
) -> str | None:
    """Return the access token the server rejected as expired, if it did."""
    if response.status_code != 401 or _is_auth_path(path):
        return None
    if _extract_response_error_code(response) != _EXPIRED_ACCESS_TOKEN:
        return None
    for name, value in headers.items():
        if name.lower() == "authorization":
            scheme, _, token = value.partition(" ")
            if scheme.lower() == "bearer" and token:
                return token
    return None


def _raise_for_response_status(
    response: httpx.Response, *, path: str, secrets: tuple[str, ...] = ()
) -> None:
    if response.is_success:
        return

    if _is_auth_path(path) and response.status_code != 429:
        # Authentication responses can echo credentials, so only the status and
        # a code are kept.
        raise RequestRejectedError(
            _AUTH_REJECTED_MESSAGE,
            status=response.status_code,
            code=_auth_error_code(response, secrets),
            retry_after=_extract_retry_after(response),
        )

    if response.status_code == 429:
        raise RateLimitError(
            f"Request to {response.url} was rate limited",
            retry_after=_extract_retry_after(response),
            rate_limit=_parse_rate_limit_headers(response.headers),
        )

    if response.status_code == 400 and path == "/v1/heartbeats":
        try:
            mismatch = OrderHeartbeatMismatchResponse.model_validate(response.json())
        except ValueError:
            pass
        else:
            raise OrderHeartbeatMismatchError(mismatch.heartbeat_id)

    message = _extract_response_error_message(response)
    code = _extract_response_error_code(response)
    if secrets:
        message = _redact(message, secrets)
        code = _safe_error_code(code, secrets)
    raise RequestRejectedError(
        message,
        status=response.status_code,
        code=code,
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
