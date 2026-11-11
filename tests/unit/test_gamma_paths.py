import pytest

from polymarket._internal.gamma_paths import (
    build_comment_thread_path,
    build_comments_by_user_address_path,
    build_event_path,
    build_event_tags_path,
    build_market_path,
    build_market_tags_path,
    build_related_tag_resources_path,
    build_related_tags_path,
    build_series_path,
    build_tag_path,
)
from polymarket.errors import UserInputError


def test_build_market_path_by_id() -> None:
    assert build_market_path(id="12345", slug=None, url=None) == "/v1/markets/12345"


def test_build_market_path_by_slug() -> None:
    assert build_market_path(id=None, slug="some-slug", url=None) == "/v1/markets/slug/some-slug"


def test_build_market_path_by_url() -> None:
    assert (
        build_market_path(
            id=None,
            slug=None,
            url="https://polymarket.com/event/some-slug",
        )
        == "/v1/markets/slug/some-slug"
    )


def test_build_market_path_by_selected_market_event_url() -> None:
    assert (
        build_market_path(
            id=None,
            slug=None,
            url="https://polymarket.com/event/event-slug/market-slug",
        )
        == "/v1/markets/slug/market-slug"
    )


def test_build_market_path_accepts_www_host() -> None:
    assert (
        build_market_path(
            id=None,
            slug=None,
            url="https://www.polymarket.com/market/some-slug",
        )
        == "/v1/markets/slug/some-slug"
    )


def test_build_market_path_url_encodes_special_characters() -> None:
    assert build_market_path(id="a b/c", slug=None, url=None) == "/v1/markets/a%20b%2Fc"


def test_build_market_path_rejects_no_inputs() -> None:
    with pytest.raises(UserInputError, match="exactly one of id, slug, or url for market"):
        build_market_path(id=None, slug=None, url=None)


def test_build_market_path_rejects_multiple_inputs() -> None:
    with pytest.raises(UserInputError, match="exactly one of id, slug, or url for market"):
        build_market_path(id="123", slug="some-slug", url=None)


def test_build_market_path_treats_empty_strings_as_unset() -> None:
    with pytest.raises(UserInputError, match="exactly one of id, slug, or url for market"):
        build_market_path(id="", slug="", url="")


def test_build_market_path_rejects_non_https_url() -> None:
    with pytest.raises(UserInputError, match="valid Polymarket URL"):
        build_market_path(id=None, slug=None, url="http://polymarket.com/market/some-slug")


def test_build_market_path_rejects_other_domain() -> None:
    with pytest.raises(UserInputError, match="valid Polymarket URL"):
        build_market_path(id=None, slug=None, url="https://evil.com/market/some-slug")


def test_build_market_path_rejects_unsupported_polymarket_url() -> None:
    with pytest.raises(UserInputError, match="Polymarket market URL"):
        build_market_path(id=None, slug=None, url="https://polymarket.com/tag/politics")


def test_build_market_path_rejects_url_with_extra_segments() -> None:
    with pytest.raises(UserInputError, match="Polymarket market URL"):
        build_market_path(id=None, slug=None, url="https://polymarket.com/market/a/b")


def test_build_market_path_rejects_url_with_one_segment() -> None:
    with pytest.raises(UserInputError, match="Polymarket market URL"):
        build_market_path(id=None, slug=None, url="https://polymarket.com/market")


def test_build_event_path_by_id() -> None:
    assert build_event_path(id="99", slug=None, url=None) == "/v1/events/99"


def test_build_event_path_by_slug() -> None:
    assert build_event_path(id=None, slug="event-slug", url=None) == "/v1/events/slug/event-slug"


def test_build_event_path_by_url() -> None:
    assert (
        build_event_path(
            id=None,
            slug=None,
            url="https://polymarket.com/event/event-slug",
        )
        == "/v1/events/slug/event-slug"
    )


def test_build_event_path_rejects_market_url() -> None:
    with pytest.raises(UserInputError, match="Polymarket event URL"):
        build_event_path(id=None, slug=None, url="https://polymarket.com/market/some-slug")


def test_build_event_path_rejects_no_inputs() -> None:
    with pytest.raises(UserInputError, match="exactly one of id, slug, or url for event"):
        build_event_path(id=None, slug=None, url=None)


def test_build_tag_path_by_id() -> None:
    assert build_tag_path(id="42", slug=None) == "/v1/tags/42"


def test_build_tag_path_by_slug() -> None:
    assert build_tag_path(id=None, slug="politics") == "/v1/tags/slug/politics"


def test_build_tag_path_url_encodes_special_characters() -> None:
    assert build_tag_path(id="a/b", slug=None) == "/v1/tags/a%2Fb"
    assert build_tag_path(id=None, slug="a b") == "/v1/tags/slug/a%20b"


def test_build_tag_path_rejects_both_inputs() -> None:
    with pytest.raises(UserInputError, match="Provide exactly one of id or slug"):
        build_tag_path(id="42", slug="politics")


def test_build_tag_path_rejects_neither_input() -> None:
    with pytest.raises(UserInputError, match="Provide exactly one of id or slug"):
        build_tag_path(id=None, slug=None)


def test_build_tag_path_rejects_empty_id() -> None:
    with pytest.raises(UserInputError, match="Tag id cannot be empty"):
        build_tag_path(id="", slug=None)


def test_build_tag_path_rejects_empty_slug() -> None:
    with pytest.raises(UserInputError, match="Tag slug cannot be empty"):
        build_tag_path(id=None, slug="")


def test_build_related_tags_path_by_id() -> None:
    assert build_related_tags_path(id="42", slug=None) == "/v1/tags/42/related-tags"


def test_build_related_tags_path_by_slug() -> None:
    assert (
        build_related_tags_path(id=None, slug="politics") == "/v1/tags/slug/politics/related-tags"
    )


def test_build_related_tag_resources_path_by_id() -> None:
    assert build_related_tag_resources_path(id="42", slug=None) == "/v1/tags/42/related-tags/tags"


def test_build_related_tag_resources_path_by_slug() -> None:
    assert (
        build_related_tag_resources_path(id=None, slug="politics")
        == "/v1/tags/slug/politics/related-tags/tags"
    )


def test_build_market_tags_path_builds_path() -> None:
    assert build_market_tags_path("42") == "/v1/markets/42/tags"


def test_build_market_tags_path_url_encodes() -> None:
    assert build_market_tags_path("a/b") == "/v1/markets/a%2Fb/tags"


def test_build_market_tags_path_rejects_empty_id() -> None:
    with pytest.raises(UserInputError, match="id is required"):
        build_market_tags_path("")


def test_build_event_tags_path_builds_path() -> None:
    assert build_event_tags_path("42") == "/v1/events/42/tags"


def test_build_event_tags_path_rejects_empty_id() -> None:
    with pytest.raises(UserInputError, match="id is required"):
        build_event_tags_path("")


def test_build_series_path_builds_path() -> None:
    assert build_series_path("series-1") == "/v1/series/series-1"


def test_build_series_path_url_encodes() -> None:
    assert build_series_path("a b") == "/v1/series/a%20b"


def test_build_series_path_rejects_empty_id() -> None:
    with pytest.raises(UserInputError, match="id is required"):
        build_series_path("")


def test_build_comment_thread_path_builds_path() -> None:
    assert build_comment_thread_path("1000") == "/v1/comments/1000"


def test_build_comment_thread_path_rejects_empty_id() -> None:
    with pytest.raises(UserInputError, match="id is required"):
        build_comment_thread_path("")


def test_build_comments_by_user_address_path_builds_path() -> None:
    assert build_comments_by_user_address_path("0xUSER") == "/v1/users/0xUSER/comments"


def test_build_comments_by_user_address_path_url_encodes() -> None:
    assert build_comments_by_user_address_path("a b") == "/v1/users/a%20b/comments"


def test_build_comments_by_user_address_path_rejects_empty_address() -> None:
    with pytest.raises(UserInputError, match="address is required"):
        build_comments_by_user_address_path("")
