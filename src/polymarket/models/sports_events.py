from datetime import datetime
from typing import Any, Literal, cast

from pydantic import Field, field_validator, model_validator

from polymarket.models.base import BaseModel
from polymarket.models.clob._validators import (
    _parse_epoch_ms_or_iso_timestamp,  # pyright: ignore[reportPrivateUsage]
)


class SportsGameResult(BaseModel):
    game_id: int = Field(validation_alias="gameId")
    sportradar_game_id: str | None = Field(default=None, validation_alias="sportradarGameId")
    slug: str | None = None
    league_abbreviation: str = Field(validation_alias="leagueAbbreviation")
    home_team: str | None = Field(default=None, validation_alias="homeTeam")
    away_team: str | None = Field(default=None, validation_alias="awayTeam")
    status: str
    live: bool
    ended: bool
    score: str
    period: str | None = None
    elapsed: str | None = None
    finished_at: datetime | None = Field(default=None, validation_alias="finishedTimestamp")
    turn: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coalesce_finished_timestamp(cls, data: Any) -> Any:
        # Mirror TS's `finishedTimestamp ?? finished_timestamp` (nullish
        # coalescing). AliasChoices would short-circuit on the first PRESENT
        # key even if its value is null, which silently drops a valid
        # snake_case fallback.
        if not isinstance(data, dict):
            return data
        wire = dict(cast(dict[str, Any], data))
        camel = wire.get("finishedTimestamp")
        snake = wire.pop("finished_timestamp", None)
        if camel in (None, "") and snake not in (None, ""):
            wire["finishedTimestamp"] = snake
        return wire

    @field_validator("finished_at", mode="before")
    @classmethod
    def _parse_finished_at(cls, value: object) -> object:
        return _parse_epoch_ms_or_iso_timestamp(value)


class SportsResultEvent(BaseModel):
    topic: Literal["sports"] = "sports"
    type: Literal["sport_result"] = "sport_result"
    payload: SportsGameResult


SportsEvent = SportsResultEvent


def parse_sports_event(raw: object) -> SportsEvent:
    """Wrap a raw sports game-result payload into the envelope shape."""
    return SportsResultEvent.model_validate(
        {"topic": "sports", "type": "sport_result", "payload": raw}
    )


__all__ = [
    "SportsEvent",
    "SportsGameResult",
    "SportsResultEvent",
    "parse_sports_event",
]
