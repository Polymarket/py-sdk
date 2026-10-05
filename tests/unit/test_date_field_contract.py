from datetime import UTC, date, datetime
from typing import get_type_hints

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.gamma.common import parse_optional_date
from polymarket.models.gamma.event import EventSchedule
from polymarket.models.rtds_events import CommentRemovedPayload

_COMMENT_REMOVED_BASE = {"id": "99"}


class TestParseOptionalDate:
    def test_returns_none_for_none(self) -> None:
        assert parse_optional_date(None) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert parse_optional_date("") is None

    def test_parses_date_only_string(self) -> None:
        assert parse_optional_date("2026-05-31") == date(2026, 5, 31)

    def test_parses_midnight_utc_datetime_string(self) -> None:
        assert parse_optional_date("2026-04-27T00:00:00Z") == date(2026, 4, 27)

    def test_parses_microsecond_iso_string(self) -> None:
        assert parse_optional_date("2026-05-05T15:15:05.474907Z") == date(2026, 5, 5)

    def test_passes_through_date_instance(self) -> None:
        d = date(2026, 1, 2)
        assert parse_optional_date(d) is d

    def test_extracts_date_from_datetime_instance(self) -> None:
        dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert parse_optional_date(dt) == date(2026, 1, 2)

    def test_rejects_invalid_date_string(self) -> None:
        with pytest.raises(ValueError):
            parse_optional_date("not-a-date")

    def test_rejects_out_of_range_date_string(self) -> None:
        with pytest.raises(ValueError):
            parse_optional_date("2026-13-01")

    def test_rejects_integer(self) -> None:
        with pytest.raises(ValueError):
            parse_optional_date(42)

    def test_rejects_float(self) -> None:
        with pytest.raises(ValueError):
            parse_optional_date(1.5)

    def test_rejects_boolean(self) -> None:
        with pytest.raises(ValueError):
            parse_optional_date(True)


class TestEventScheduleEventDateContract:
    def test_annotation_resolves_to_date(self) -> None:
        hints = get_type_hints(EventSchedule)
        assert hints["event_date"] == (date | None)

    def test_parses_date_only_wire_format(self) -> None:
        sched = EventSchedule.parse_response({"eventDate": "2025-03-02"})
        assert sched.event_date == date(2025, 3, 2)
        assert isinstance(sched.event_date, date)

    def test_none_stays_none(self) -> None:
        sched = EventSchedule.parse_response({"eventDate": None})
        assert sched.event_date is None

    def test_missing_field_is_none(self) -> None:
        sched = EventSchedule.parse_response({})
        assert sched.event_date is None

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            EventSchedule.parse_response({"eventDate": "not-a-date"})

    def test_does_not_disturb_sibling_datetime_fields(self) -> None:
        sched = EventSchedule.parse_response(
            {
                "eventDate": "2025-03-02",
                "startDate": "2025-03-01T12:00:00Z",
                "endDate": "2025-03-03T00:00:00Z",
            }
        )
        assert sched.event_date == date(2025, 3, 2)
        assert sched.start_date == datetime(2025, 3, 1, 12, 0, tzinfo=UTC)
        assert sched.end_date == datetime(2025, 3, 3, 0, 0, tzinfo=UTC)


class TestCommentRemovedPayloadDatetimeContract:
    def test_created_at_annotation_resolves_to_datetime(self) -> None:
        hints = get_type_hints(CommentRemovedPayload)
        assert hints["created_at"] == (datetime | None)
        assert hints["updated_at"] == (datetime | None)

    def test_parses_microsecond_iso_format(self) -> None:
        payload = CommentRemovedPayload.parse_response(
            {
                **_COMMENT_REMOVED_BASE,
                "createdAt": "2026-05-05T15:15:05.474907Z",
                "updatedAt": "2026-05-05T15:15:19.589696Z",
            }
        )
        assert payload.created_at == datetime(2026, 5, 5, 15, 15, 5, 474907, tzinfo=UTC)
        assert payload.updated_at == datetime(2026, 5, 5, 15, 15, 19, 589696, tzinfo=UTC)

    def test_parses_plain_iso_format(self) -> None:
        payload = CommentRemovedPayload.parse_response(
            {**_COMMENT_REMOVED_BASE, "createdAt": "2024-03-09T00:00:00Z"}
        )
        assert payload.created_at == datetime(2024, 3, 9, tzinfo=UTC)

    def test_none_stays_none(self) -> None:
        payload = CommentRemovedPayload.parse_response(
            {**_COMMENT_REMOVED_BASE, "createdAt": None, "updatedAt": None}
        )
        assert payload.created_at is None
        assert payload.updated_at is None

    def test_missing_fields_are_none(self) -> None:
        payload = CommentRemovedPayload.parse_response(_COMMENT_REMOVED_BASE)
        assert payload.created_at is None
        assert payload.updated_at is None

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(UnexpectedResponseError):
            CommentRemovedPayload.parse_response(
                {**_COMMENT_REMOVED_BASE, "createdAt": "not-a-datetime"}
            )


class TestNoStringDateFieldsRemain:
    def test_event_schedule_event_date_is_not_str(self) -> None:
        annotation = EventSchedule.model_fields["event_date"].annotation
        assert str not in (getattr(annotation, "__args__", ()) or ())

    def test_comment_removed_created_at_is_not_str(self) -> None:
        annotation = CommentRemovedPayload.model_fields["created_at"].annotation
        assert str not in (getattr(annotation, "__args__", ()) or ())

    def test_comment_removed_updated_at_is_not_str(self) -> None:
        annotation = CommentRemovedPayload.model_fields["updated_at"].annotation
        assert str not in (getattr(annotation, "__args__", ()) or ())
