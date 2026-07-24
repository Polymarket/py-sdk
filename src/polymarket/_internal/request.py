from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

Service = Literal["gamma", "data", "rfq"]
Method = Literal["GET"]

QueryParamScalar = str | int | float | bool
QueryParamValue = QueryParamScalar | tuple[QueryParamScalar, ...]

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RequestSpec(Generic[T]):
    service: Service
    method: Method
    path: str
    parse: Callable[[object], T]
    params: Mapping[str, QueryParamValue | None] | None = None


@dataclass(frozen=True, slots=True)
class OffsetPaginatedSpec(Generic[T]):
    """A spec for endpoints that paginate via limit/offset.

    `max_page_size` must match the endpoint's server-side limit cap. Without
    it, a page size above the cap makes the server clamp or reject the request
    and pagination silently skips or drops rows.
    """

    service: Service
    path: str
    parse_items: Callable[[object], tuple[T, ...]]
    base_params: Mapping[str, QueryParamValue] | None = None
    max_page_size: int | None = None


@dataclass(frozen=True, slots=True)
class KeysetPaginatedSpec(Generic[T]):
    """A spec for endpoints that paginate via a server-issued opaque cursor.

    The server returns `next_cursor` (opaque string) which is sent back via the
    `after_cursor` query param to fetch the next page. We wrap the server cursor
    in our own envelope (path + query fingerprint) for replay protection.
    """

    service: Service
    path: str
    parse_page: Callable[[object], "KeysetPagePayload[T]"]
    base_params: Mapping[str, QueryParamValue] | None = None
    cursor_param: str = "after_cursor"
    max_page_size: int | None = None


@dataclass(frozen=True, slots=True)
class KeysetPagePayload(Generic[T]):
    items: tuple[T, ...]
    server_next_cursor: str | None


@dataclass(frozen=True, slots=True)
class PageBasedSpec(Generic[T]):
    """A spec for endpoints that paginate via explicit 1-indexed page number.

    Each response carries one payload value of type T (e.g. a SearchResults bundle).
    The dispatcher wraps the payload in a `Page` so callers get the standard
    `Paginator` shape used by every other paginated endpoint.
    """

    service: Service
    path: str
    parse_page: Callable[[object], "PageBasedPagePayload[T]"]
    base_params: Mapping[str, QueryParamValue] | None = None


@dataclass(frozen=True, slots=True)
class PageBasedPagePayload(Generic[T]):
    items: T
    has_more: bool
    total_count: int | None = None


__all__ = [
    "KeysetPagePayload",
    "KeysetPaginatedSpec",
    "Method",
    "OffsetPaginatedSpec",
    "PageBasedPagePayload",
    "PageBasedSpec",
    "QueryParamScalar",
    "QueryParamValue",
    "RequestSpec",
    "Service",
]
