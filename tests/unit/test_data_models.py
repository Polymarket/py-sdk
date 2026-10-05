from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from data_v2_samples import position_payload, sample

from polymarket import (
    BiggestWinnerKind,
    BuilderStanding,
    BuilderVolumePoint,
    ComboPosition,
    Holder,
    LiveVolume,
    MarketLiveVolume,
    MetaHolder,
    OpenInterest,
    PortfolioValue,
    Position,
    PositionStatus,
    PriceHistoryPoint,
    Resolution,
    ResolutionStatus,
    Trade,
    TraderLeaderboardEntry,
    TraderLeaderboardStanding,
    UserPnlSeries,
    UserStats,
    UserVolume,
)
from polymarket.errors import UnexpectedResponseError
from polymarket.models.base import BaseModel
from polymarket.models.data.leaderboard import parse_biggest_winners


@pytest.mark.parametrize(
    "model,name",
    [
        (Trade, "trades"),
        (Position, "positions"),
        (ComboPosition, "positions_combos"),
        (MetaHolder, "holders"),
        (OpenInterest, "oi"),
        (Resolution, "resolutions"),
        (TraderLeaderboardEntry, "leaderboard"),
        (BuilderStanding, "builders_leaderboard"),
        (BuilderVolumePoint, "builders_volume"),
        (PriceHistoryPoint, "prices-history"),
    ],
)
def test_captured_rows_and_canonical_roundtrip(model: type[BaseModel], name: str) -> None:
    rows = model.parse_response_list(sample(name))
    assert rows
    for row in rows:
        assert model.model_validate(row.model_dump()) == row


@pytest.mark.parametrize(
    "model,name",
    [
        (PortfolioValue, "value"),
        (UserStats, "user-stats"),
        (UserPnlSeries, "user-pnl"),
        (UserVolume, "user-volume"),
        (LiveVolume, "live-volume"),
        (TraderLeaderboardStanding, "leaderboard_standing"),
    ],
)
def test_captured_objects(model: type[BaseModel], name: str) -> None:
    value = model.parse_response(sample(name))
    assert model.model_validate(value.model_dump()) == value


def test_position_sentinels_and_numbers() -> None:
    position = Position.parse_response(
        position_payload(
            event_id="0",
            end_date="1970-01-01",
            last_event_at=0,
            outcome_index=999,
            opposite_token_id="",
            title="",
            current_size=0.123456,
        )
    )
    assert (
        position.event_id is None and position.end_date is None and position.last_event_at is None
    )
    assert (
        position.outcome_index is None
        and position.opposite_asset_id is None
        and position.title is None
    )
    assert position.current_size == Decimal("0.123456")
    assert position.token_id == position.asset_id
    assert position.status is PositionStatus.OPEN
    assert Position.parse_response(position_payload(end_date="2026-05-31")).end_date == date(
        2026, 5, 31
    )
    for field in ("proxy_wallet", "token_id", "current_size", "condition_id"):
        payload = position_payload()
        payload.pop(field)
        with pytest.raises(UnexpectedResponseError):
            Position.parse_response(payload)


def test_nullable_pnl_and_unranked_standing() -> None:
    payload = sample("user-pnl")
    payload["points"][0]["fees_paid"] = None
    assert UserPnlSeries.parse_response(payload).points[0].fees_paid is None
    for value in (None, 0):
        standing = TraderLeaderboardStanding.parse_response(
            {**sample("leaderboard_standing"), "rank_pnl": value, "rank_volume": value}
        )
        assert standing.pnl_rank is None and standing.volume_rank is None


def test_resolution_units_and_timestamps() -> None:
    payload: dict[str, Any] = sample("resolutions")[0]
    for timestamp in ("1700000000", "2023-11-14T22:13:20Z"):
        row = Resolution.parse_response(
            {
                **payload,
                "proposed_price": "69",
                "reproposed_price": "69",
                "price": "69",
                "payouts": [500000, 500000],
                "last_update_timestamp": timestamp,
            }
        )
        assert row.price is None and row.proposed_price is None and row.reproposed_price is None
        assert row.payouts == (Decimal("0.5"), Decimal("0.5"))
        assert row.status is ResolutionStatus(payload["status"])
        assert row.last_updated_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    dated = Resolution.parse_response({**payload, "last_update_timestamp": "2023-11-14"})
    assert dated.last_updated_at == datetime(2023, 11, 14, tzinfo=UTC)
    combo = ComboPosition.parse_response_list(sample("positions_combos"))[0]
    market = combo.legs[0].market
    assert market is not None and market.end_date == datetime(2026, 8, 5, tzinfo=UTC)
    assert OpenInterest.parse_response({"condition_id": "GLOBAL", "value": 0}).condition_id is None


def test_winner_discriminators_and_holder_pnl() -> None:
    market = parse_biggest_winners(sample("biggest-winners"))[0]
    assert market.kind is BiggestWinnerKind.MARKET
    assert (
        parse_biggest_winners(sample("biggest-winners_combos"))[0].kind is BiggestWinnerKind.COMBO
    )
    for event_id in (None, "", "0", 0, -1, "abc"):
        with pytest.raises(UnexpectedResponseError):
            parse_biggest_winners([{**sample("biggest-winners")[0], "event_id": event_id}])
    holder = Holder.parse_response(sample("holders")[0]["holders"][0])
    assert holder.total_pnl is not None


@pytest.mark.parametrize("payouts", [[500000, 500000], [1000000, 0], None])
def test_resolution_response_payouts_survive_canonical_roundtrips(
    payouts: list[int] | None,
) -> None:
    payload = {**sample("resolutions")[0], "payouts": payouts}
    row = Resolution.parse_response_list([payload])[0]
    expected = None if payouts is None else tuple(Decimal(value) / 1_000_000 for value in payouts)
    assert row.payouts == expected
    assert payload["payouts"] == payouts
    assert Resolution.model_validate(row.model_dump()) == row
    assert Resolution.model_validate_json(row.model_dump_json()) == row


@pytest.mark.parametrize("price", ["", "garbage"])
def test_malformed_decimal_responses_raise_sdk_errors(price: str) -> None:
    with pytest.raises(UnexpectedResponseError):
        PriceHistoryPoint.parse_response(
            {"timestamp": 1700000000, "price": price, "resolution_seconds": 60}
        )
    with pytest.raises(UnexpectedResponseError):
        Holder.parse_response({**sample("holders")[0]["holders"][0], "total_pnl": price})


@pytest.mark.parametrize("payouts", [[], [1], [1, 2, 3], ["garbage", 0], [True, 0], ["sNaN", 0]])
def test_malformed_resolution_payouts_raise_sdk_errors(payouts: list[object]) -> None:
    with pytest.raises(UnexpectedResponseError):
        Resolution.parse_response({**sample("resolutions")[0], "payouts": payouts})


def test_malformed_analytics_identity_and_timestamp_raise_sdk_errors() -> None:
    with pytest.raises(UnexpectedResponseError):
        OpenInterest.parse_response({"value": 1})
    with pytest.raises(UnexpectedResponseError):
        MarketLiveVolume.parse_response({"condition_id": "garbage", "taker_volume": 1})
    assert (
        MarketLiveVolume.parse_response({"condition_id": "", "taker_volume": 1}).condition_id
        is None
    )
    with pytest.raises(UnexpectedResponseError):
        PriceHistoryPoint.parse_response(
            {"timestamp": 10**100, "price": 0.5, "resolution_seconds": 60}
        )
