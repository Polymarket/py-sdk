from __future__ import annotations

import json as _json
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeAlias

import httpx
from httpx import USE_CLIENT_DEFAULT

from polymarket._internal.request import QueryParamValue
from polymarket.errors import (
    RateLimitError,
    RequestRejectedError,
    TransportError,
    UnexpectedResponseError,
)

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
                path,
                params=_clean_params(params),
                content=content,
                headers=merged_headers or None,
                timeout=timeout if timeout is not None else USE_CLIENT_DEFAULT,
            )
        except httpx.HTTPError as error:
            _log_failure(self._logger, method, path, error, started)
            raise TransportError(str(error) or "Request failed") from error

        _log_response(self._logger, method, path, response, started)
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
                path,
                params=_clean_params(params),
                content=content,
                headers=merged_headers or None,
                timeout=timeout if timeout is not None else USE_CLIENT_DEFAULT,
            )
        except httpx.HTTPError as error:
            _log_failure(self._logger, method, path, error, started)
            raise TransportError(str(error) or "Request failed") from error

        _log_response(self._logger, method, path, response, started)
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


def _raise_for_response_status(response: httpx.Response) -> None:
    if response.is_success:
        return

    if response.status_code == 429:
        raise RateLimitError(f"Request to {response.url} was rate limited")

    raise RequestRejectedError(
        _extract_response_error_message(response),
        status=response.status_code,
        retry_after=_extract_retry_after(response),
    )


def _extract_retry_after(response: httpx.Response) -> float | None:
    header = response.headers.get("retry-after")
    if header is not None:
        try:
            seconds = float(header.strip())
        except ValueError:
            seconds = None
        if seconds is not None and math.isfinite(seconds) and seconds >= 0:
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
