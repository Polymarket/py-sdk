"""Position snapshot selection and public/owner reads."""

import re
from collections.abc import Sequence
from datetime import UTC, datetime

from polymarket._internal.actions.perps.builders import validate_address
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UserInputError
from polymarket.models.perps.account import PerpsCredentialsInfo
from polymarket.models.perps.position_snapshots import (
    PerpsPositionSnapshotFill,
    PerpsPositionSnapshots,
)


def _instrument_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4294967295:
        raise UserInputError("instrument ID must be a uint32 integer")
    return value


def build_position_snapshot_selection(
    *,
    active_instrument_ids: Sequence[int] = (),
    history_fills: Sequence[PerpsPositionSnapshotFill] = (),
) -> dict[str, object]:
    if (
        not isinstance(active_instrument_ids, Sequence)  # pyright: ignore[reportUnnecessaryIsInstance]
        or isinstance(active_instrument_ids, str | bytes)
    ):
        raise UserInputError("active_instrument_ids must be a sequence")
    if (
        not isinstance(history_fills, Sequence)  # pyright: ignore[reportUnnecessaryIsInstance]
        or isinstance(history_fills, str | bytes)
    ):
        raise UserInputError("history_fills must be a sequence")
    if (
        len(active_instrument_ids) > 20
        or len(history_fills) > 4
        or not (active_instrument_ids or history_fills)
    ):
        raise UserInputError(
            "select up to 20 active instruments and 4 history fills, with at least one selection"
        )
    active = [_instrument_id(value) for value in active_instrument_ids]
    if len(set(active)) != len(active):
        raise UserInputError("duplicate active instrument IDs")
    history: list[dict[str, object]] = []
    seen: set[tuple[int, int]] = set()
    for fill in history_fills:
        if not isinstance(fill, PerpsPositionSnapshotFill):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise UserInputError("history_fills must contain PerpsPositionSnapshotFill values")
        instrument_id = _instrument_id(fill.instrument_id)
        if (
            not isinstance(fill.trade_id, str)  # pyright: ignore[reportUnnecessaryIsInstance]
            or re.fullmatch(r"[0-9]{1,20}", fill.trade_id) is None
            or int(fill.trade_id) > 2**64 - 1
        ):
            raise UserInputError("trade_id must be a decimal u64 string of at most 20 digits")
        timestamp = fill.timestamp
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise UserInputError("timestamp must be timezone-aware")
            delta = timestamp.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
            if delta.microseconds % 1000:
                raise UserInputError("timestamp must use whole milliseconds")
            timestamp = (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)  # pyright: ignore[reportUnnecessaryIsInstance]
            or not 0 <= timestamp <= 18446744073709
        ):
            raise UserInputError("timestamp must be epoch milliseconds from 0 to 18446744073709")
        key = instrument_id, int(fill.trade_id)
        if key in seen:
            raise UserInputError("duplicate history fills")
        seen.add(key)
        history.append(
            {"instrument_id": instrument_id, "trade_id": fill.trade_id, "timestamp": timestamp}
        )
    return {"active_instrument_ids": active, "history_fills": history}


async def fetch_position_snapshots(
    api: AsyncTransport,
    *,
    address: str,
    active_instrument_ids: Sequence[int] = (),
    history_fills: Sequence[PerpsPositionSnapshotFill] = (),
) -> PerpsPositionSnapshots:
    address = validate_address("address", address)
    selection = build_position_snapshot_selection(
        active_instrument_ids=active_instrument_ids, history_fills=history_fills
    )
    return PerpsPositionSnapshots.parse_response(
        await api.post_json("/v1/info/position-snapshots", json={"address": address, **selection})
    )


async def fetch_own_position_snapshots(
    api: AsyncTransport,
    *,
    active_instrument_ids: Sequence[int] = (),
    history_fills: Sequence[PerpsPositionSnapshotFill] = (),
) -> PerpsPositionSnapshots:
    selection = build_position_snapshot_selection(
        active_instrument_ids=active_instrument_ids, history_fills=history_fills
    )
    owner = PerpsCredentialsInfo.parse_response(await api.get_json("/v1/account/credentials"))
    return PerpsPositionSnapshots.parse_response(
        await api.post_json(
            "/v1/info/position-snapshots", json={"address": owner.address, **selection}
        )
    )
