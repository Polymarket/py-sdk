"""Gamma request path helpers."""

from urllib.parse import quote, urlparse

from polymarket._internal.validation import require_nonempty
from polymarket.errors import UserInputError


def build_market_path(*, id: str | None, slug: str | None, url: str | None) -> str:
    return _build_entity_path("market", id=id, slug=slug, url=url)


def build_event_path(*, id: str | None, slug: str | None, url: str | None) -> str:
    return _build_entity_path("event", id=id, slug=slug, url=url)


def build_market_tags_path(id: str) -> str:
    return f"/v1/markets/{quote(require_nonempty('id', id), safe='')}/tags"


def build_event_tags_path(id: str) -> str:
    return f"/v1/events/{quote(require_nonempty('id', id), safe='')}/tags"


def build_series_path(id: str) -> str:
    return f"/v1/series/{quote(require_nonempty('id', id), safe='')}"


def build_comment_thread_path(id: str) -> str:
    return f"/v1/comments/{quote(require_nonempty('id', id), safe='')}"


def build_comments_by_user_address_path(address: str) -> str:
    return f"/v1/users/{quote(require_nonempty('address', address), safe='')}/comments"


def build_tag_path(*, id: str | None, slug: str | None) -> str:
    if (id is None) == (slug is None):
        raise UserInputError("Provide exactly one of id or slug.")

    if id is not None:
        if id == "":
            raise UserInputError("Tag id cannot be empty.")
        return f"/v1/tags/{quote(id, safe='')}"

    if slug == "":
        raise UserInputError("Tag slug cannot be empty.")
    return f"/v1/tags/slug/{quote(slug or '', safe='')}"


def build_related_tags_path(*, id: str | None, slug: str | None) -> str:
    return f"{build_tag_path(id=id, slug=slug)}/related-tags"


def build_related_tag_resources_path(*, id: str | None, slug: str | None) -> str:
    return f"{build_tag_path(id=id, slug=slug)}/related-tags/tags"


def _build_entity_path(kind: str, *, id: str | None, slug: str | None, url: str | None) -> str:
    lookup_type, value = _resolve_lookup(kind, id=id, slug=slug, url=url)

    if lookup_type == "id":
        return f"/v1/{kind}s/{quote(value, safe='')}"

    if lookup_type == "url":
        value = _parse_polymarket_url(value, kind)

    return f"/v1/{kind}s/slug/{quote(value, safe='')}"


def _resolve_lookup(
    kind: str,
    *,
    id: str | None,
    slug: str | None,
    url: str | None,
) -> tuple[str, str]:
    selected = [
        (name, value) for name, value in (("id", id), ("slug", slug), ("url", url)) if value
    ]

    if len(selected) != 1:
        raise UserInputError(f"Provide exactly one of id, slug, or url for {kind} lookup.")

    return selected[0]


def _parse_polymarket_url(raw_url: str, kind: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme != "https" or parsed.netloc not in {"polymarket.com", "www.polymarket.com"}:
        raise UserInputError("Expected a valid Polymarket URL.")

    segments = [segment for segment in parsed.path.split("/") if segment]
    if kind == "market" and 2 <= len(segments) <= 3 and segments[0] == "event":
        return segments[-1]

    if len(segments) != 2 or segments[0] != kind:
        raise UserInputError(f"Expected a Polymarket {kind} URL.")

    return segments[1]
