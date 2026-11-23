import pytest

from polymarket._internal.actions import gamma as gamma_actions
from polymarket.errors import UserInputError


def test_get_market_spec_by_id_includes_optional_params() -> None:
    spec = gamma_actions.get_market_spec(
        id="42", slug=None, url=None, include_tag=True, locale="en"
    )
    assert spec.method == "GET"
    assert spec.path == "/v1/markets/42"
    assert spec.params == {"include_tag": True, "locale": "en"}


def test_get_market_spec_by_slug_omits_unset_params() -> None:
    spec = gamma_actions.get_market_spec(
        id=None, slug="some-slug", url=None, include_tag=None, locale=None
    )

    assert spec.path == "/v1/markets/slug/some-slug"
    assert spec.params == {"include_tag": None, "locale": None}


def test_get_market_spec_rejects_missing_lookup() -> None:
    with pytest.raises(UserInputError, match="exactly one of id, slug, or url for market"):
        gamma_actions.get_market_spec(id=None, slug=None, url=None, include_tag=None, locale=None)


def test_get_market_tags_spec_builds_path() -> None:
    spec = gamma_actions.get_market_tags_spec("42")
    assert spec.method == "GET"
    assert spec.path == "/v1/markets/42/tags"
    assert spec.params is None


def test_get_market_tags_spec_rejects_empty_id() -> None:
    with pytest.raises(UserInputError, match="id is required"):
        gamma_actions.get_market_tags_spec("")


def test_get_event_spec_by_id_includes_optional_params() -> None:
    spec = gamma_actions.get_event_spec(
        id="99",
        slug=None,
        url=None,
        include_best_lines=True,
        include_chat=False,
        include_template=True,
        locale="es",
    )

    assert spec.path == "/v1/events/99"
    assert spec.params == {
        "include_best_lines": True,
        "include_chat": False,
        "include_template": True,
        "locale": "es",
    }


def test_get_event_spec_by_slug_omits_unset_params() -> None:
    spec = gamma_actions.get_event_spec(
        id=None,
        slug="event-slug",
        url=None,
        include_best_lines=None,
        include_chat=None,
        include_template=None,
        locale=None,
    )

    assert spec.path == "/v1/events/slug/event-slug"
    assert spec.params == {
        "include_best_lines": None,
        "include_chat": None,
        "include_template": None,
        "locale": None,
    }


def test_get_event_tags_spec_builds_path() -> None:
    spec = gamma_actions.get_event_tags_spec("99")

    assert spec.path == "/v1/events/99/tags"
    assert spec.params is None


def test_get_event_tags_spec_rejects_empty_id() -> None:
    with pytest.raises(UserInputError, match="id is required"):
        gamma_actions.get_event_tags_spec("")


def test_get_series_spec_includes_optional_params() -> None:
    spec = gamma_actions.get_series_spec("series-id", locale="en")
    assert spec.path == "/v1/series/series-id"
    assert spec.params == {"locale": "en"}


def test_get_series_spec_omits_unset_params() -> None:
    spec = gamma_actions.get_series_spec("series-id", locale=None)

    assert spec.params == {"locale": None}


def test_get_series_spec_rejects_empty_id() -> None:
    with pytest.raises(UserInputError, match="id is required"):
        gamma_actions.get_series_spec("", locale=None)


def test_get_tag_spec_by_id_includes_options() -> None:
    spec = gamma_actions.get_tag_spec(id="42", slug=None, include_template=True, locale="en")

    assert spec.path == "/v1/tags/42"
    assert spec.params == {
        "include_template": True,
        "locale": "en",
    }


def test_get_tag_spec_by_slug_with_only_locale() -> None:
    spec = gamma_actions.get_tag_spec(id=None, slug="politics", include_template=None, locale="en")

    assert spec.path == "/v1/tags/slug/politics"
    assert spec.params == {
        "include_template": None,
        "locale": "en",
    }


def test_get_tag_spec_rejects_slug_with_include_template() -> None:
    with pytest.raises(UserInputError, match="include_template is only supported for tag id"):
        gamma_actions.get_tag_spec(id=None, slug="politics", include_template=True, locale=None)


def test_get_related_tags_spec_by_id_includes_filters() -> None:
    spec = gamma_actions.get_related_tags_spec(id="42", slug=None, omit_empty=True, status="active")

    assert spec.path == "/v1/tags/42/related-tags"
    assert spec.params == {"omit_empty": True, "status": "active"}


def test_get_related_tags_spec_by_slug_without_filters() -> None:
    spec = gamma_actions.get_related_tags_spec(
        id=None, slug="politics", omit_empty=None, status=None
    )

    assert spec.path == "/v1/tags/slug/politics/related-tags"
    assert spec.params == {"omit_empty": None, "status": None}


def test_get_related_tags_spec_rejects_slug_with_omit_empty() -> None:
    with pytest.raises(
        UserInputError, match="omit_empty and status are only supported for related tag id"
    ):
        gamma_actions.get_related_tags_spec(id=None, slug="politics", omit_empty=True, status=None)


def test_get_related_tags_spec_rejects_slug_with_status() -> None:
    with pytest.raises(
        UserInputError, match="omit_empty and status are only supported for related tag id"
    ):
        gamma_actions.get_related_tags_spec(
            id=None, slug="politics", omit_empty=None, status="active"
        )


def test_get_related_tag_resources_spec_by_id() -> None:
    spec = gamma_actions.get_related_tag_resources_spec(
        id="42", slug=None, locale="en", omit_empty=True, status="active"
    )

    assert spec.path == "/v1/tags/42/related-tags/tags"
    assert spec.params == {"locale": "en", "omit_empty": True, "status": "active"}


def test_get_related_tag_resources_spec_by_slug() -> None:
    spec = gamma_actions.get_related_tag_resources_spec(
        id=None, slug="politics", locale=None, omit_empty=None, status=None
    )

    assert spec.path == "/v1/tags/slug/politics/related-tags/tags"
    assert spec.params == {"locale": None, "omit_empty": None, "status": None}


def test_get_sports_spec_builds_request() -> None:
    spec = gamma_actions.get_sports_spec()
    assert spec.method == "GET"
    assert spec.path == "/v1/sports"
    assert spec.params is None


def test_get_sports_market_types_spec_builds_request() -> None:
    spec = gamma_actions.get_sports_market_types_spec()

    assert spec.path == "/v1/sports/market-types"
    assert spec.params is None


def test_get_public_profile_spec_builds_request() -> None:
    spec = gamma_actions.get_public_profile_spec("0xWALLET")

    assert spec.path == "/v1/public-profile"
    assert spec.params == {"address": "0xWALLET"}


def test_get_public_profile_spec_rejects_empty_address() -> None:
    with pytest.raises(UserInputError, match="address is required"):
        gamma_actions.get_public_profile_spec("")


def test_get_comment_thread_spec_builds_request_with_positions() -> None:
    spec = gamma_actions.get_comment_thread_spec("1000", get_positions=True)

    assert spec.path == "/v1/comments/1000"
    assert spec.params == {"get_positions": True}


def test_get_comment_thread_spec_omits_positions_flag() -> None:
    spec = gamma_actions.get_comment_thread_spec("1000", get_positions=None)

    assert spec.params == {"get_positions": None}


def test_get_comment_thread_spec_rejects_empty_id() -> None:
    with pytest.raises(UserInputError, match="id is required"):
        gamma_actions.get_comment_thread_spec("", get_positions=None)
