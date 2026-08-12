import inspect
from datetime import UTC, datetime
from typing import Any, get_type_hints

import pytest
from pydantic import ValidationError

from polymarket.models.sports_events import (
    SportsGameResult,
    SportsResultEvent,
    parse_sports_event,
)

_WIRE: dict[str, Any] = {
    "gameId": 123,
    "sportradarGameId": "sr-abc",
    "slug": "lakers-vs-celtics",
    "leagueAbbreviation": "NBA",
    "homeTeam": "LAL",
    "awayTeam": "BOS",
    "status": "live",
    "live": True,
    "ended": False,
    "score": "98-102",
    "period": "Q4",
    "elapsed": "10:32",
    "turn": "BOS",
}


def test_sports_event_has_envelope_shape() -> None:
    event = parse_sports_event(_WIRE)
    assert event.topic == "sports"
    assert event.type == "sport_result"
    assert isinstance(event.payload, SportsGameResult)


def test_camelcase_wire_fields_map_to_snake_case() -> None:
    event = parse_sports_event(_WIRE)
    assert event.payload.game_id == 123
    assert event.payload.sportradar_game_id == "sr-abc"
    assert event.payload.league_abbreviation == "NBA"
    assert event.payload.home_team == "LAL"
    assert event.payload.away_team == "BOS"


def test_finished_timestamp_exposes_canonical_annotation_and_alias_signature() -> None:
    hints = get_type_hints(SportsGameResult, include_extras=True)
    parameters = inspect.signature(SportsGameResult).parameters

    assert hints["finished_at"] == (datetime | None)
    assert parameters["finishedTimestamp"].annotation == (datetime | None)
    assert "finished_at" not in parameters


def test_required_fields_only() -> None:
    minimal: dict[str, Any] = {
        "gameId": 1,
        "leagueAbbreviation": "NBA",
        "status": "scheduled",
        "live": False,
        "ended": False,
        "score": "0-0",
    }
    event = parse_sports_event(minimal)
    assert event.payload.game_id == 1
    assert event.payload.home_team is None
    assert event.payload.away_team is None
    assert event.payload.finished_at is None


def test_finished_timestamp_camelcase_parses_to_datetime() -> None:
    payload = dict(_WIRE) | {"finishedTimestamp": "1710000000000"}
    event = parse_sports_event(payload)
    assert event.payload.finished_at == datetime.fromtimestamp(1710000000, tz=UTC)


def test_finished_timestamp_snake_case_alias_also_works() -> None:
    payload = dict(_WIRE) | {"finished_timestamp": "1710000000000"}
    event = parse_sports_event(payload)
    assert event.payload.finished_at == datetime.fromtimestamp(1710000000, tz=UTC)


def test_null_camelcase_falls_back_to_non_null_snake_case() -> None:
    # Mirrors TS's `finishedTimestamp ?? finished_timestamp`. AliasChoices
    # alone would short-circuit on the explicitly-null camelCase key and
    # silently drop the valid snake_case fallback.
    payload = dict(_WIRE) | {
        "finishedTimestamp": None,
        "finished_timestamp": "1710000000000",
    }
    event = parse_sports_event(payload)
    assert event.payload.finished_at == datetime.fromtimestamp(1710000000, tz=UTC)


def test_finished_timestamp_accepts_epoch_ms_as_int() -> None:
    payload = dict(_WIRE) | {"finishedTimestamp": 1710000000000}
    event = parse_sports_event(payload)
    assert event.payload.finished_at == datetime.fromtimestamp(1710000000, tz=UTC)


def test_finished_timestamp_accepts_iso_string() -> None:
    payload = dict(_WIRE) | {"finishedTimestamp": "2024-03-09T12:00:00+00:00"}
    event = parse_sports_event(payload)
    assert event.payload.finished_at is not None
    assert event.payload.finished_at.year == 2024


@pytest.mark.parametrize(
    "finished_timestamp", [True, 1710000000000.0, b"1710000000000", "+1", "-1"]
)
def test_finished_timestamp_preserves_rejected_inputs(finished_timestamp: object) -> None:
    payload = dict(_WIRE) | {"finishedTimestamp": finished_timestamp}

    with pytest.raises(ValidationError):
        parse_sports_event(payload)


def test_missing_required_field_raises_validation_error() -> None:
    payload = dict(_WIRE)
    del payload["gameId"]
    with pytest.raises(ValidationError):
        parse_sports_event(payload)


def test_envelope_roundtrip_through_model_dump_and_validate() -> None:
    event = parse_sports_event(_WIRE)
    dumped = event.model_dump()
    restored = SportsResultEvent.model_validate(dumped)
    assert restored.topic == "sports"
    assert restored.type == "sport_result"
    assert restored.payload.game_id == 123
