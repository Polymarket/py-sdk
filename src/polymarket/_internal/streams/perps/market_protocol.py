from collections.abc import Callable, Iterable
from typing import Any

from polymarket.models.perps.events import (
    PerpsMarketEvent,
    parse_perps_market_events,
)
from polymarket.streams._specs import (
    PerpsBboSpec,
    PerpsBookSpec,
    PerpsCandlesSpec,
    PerpsSpec,
    PerpsStatisticsSpec,
    PerpsTickersSpec,
    PerpsTradesSpec,
)

PerpsServerState = frozenset[str]
"""Set of upstream channel names derived from active subscriptions."""


def channel_for(spec: PerpsSpec) -> str:
    if isinstance(spec, PerpsTradesSpec):
        return f"trades::{spec.instrument_id}"
    if isinstance(spec, PerpsBboSpec):
        return f"bbo::{spec.instrument_id}"
    if isinstance(spec, PerpsBookSpec):
        return f"book::{spec.instrument_id}"
    if isinstance(spec, PerpsCandlesSpec):
        return f"klines::{spec.instrument_id}::{spec.interval}"
    if isinstance(spec, PerpsTickersSpec):
        return "tickers::all" if spec.instrument_id is None else f"tickers::{spec.instrument_id}"
    return "statistics::all" if spec.instrument_id is None else f"statistics::{spec.instrument_id}"


def derive_state(specs: Iterable[PerpsSpec]) -> PerpsServerState:
    channels: set[str] = set()
    ticker_ids: set[int] = set()
    statistic_ids: set[int] = set()
    all_tickers = False
    all_statistics = False
    for spec in specs:
        if isinstance(spec, PerpsTickersSpec):
            if spec.instrument_id is None:
                all_tickers = True
            else:
                ticker_ids.add(spec.instrument_id)
        elif isinstance(spec, PerpsStatisticsSpec):
            if spec.instrument_id is None:
                all_statistics = True
            else:
                statistic_ids.add(spec.instrument_id)
        else:
            channels.add(channel_for(spec))
    if all_tickers:
        channels.add("tickers::all")
    else:
        channels.update(f"tickers::{instrument_id}" for instrument_id in ticker_ids)
    if all_statistics:
        channels.add("statistics::all")
    else:
        channels.update(f"statistics::{instrument_id}" for instrument_id in statistic_ids)
    return frozenset(channels)


def build_channel_frame(
    *, request_id: int, operation: str, channels: Iterable[str]
) -> dict[str, Any]:
    return {"id": request_id, "req": operation, "chs": sorted(channels)}


def diff_channels(before: PerpsServerState, after: PerpsServerState) -> tuple[list[str], list[str]]:
    added = sorted(after - before)
    removed = sorted(before - after)
    return added, removed


def match_for(spec: PerpsSpec) -> Callable[[PerpsMarketEvent], bool]:
    if isinstance(spec, PerpsCandlesSpec):
        instrument_id = spec.instrument_id
        interval = spec.interval

        def matches_candles(event: PerpsMarketEvent) -> bool:
            return (
                event.topic == "perps.candles"
                and event.payload.instrument_id == instrument_id
                and event.payload.interval == interval
            )

        return matches_candles
    if isinstance(spec, PerpsTickersSpec | PerpsStatisticsSpec):
        topic = spec.topic
        optional_id = spec.instrument_id

        def matches_optional(event: PerpsMarketEvent) -> bool:
            return event.topic == topic and (
                optional_id is None or event.payload.instrument_id == optional_id
            )

        return matches_optional
    topic = spec.topic
    instrument_id = spec.instrument_id

    def matches(event: PerpsMarketEvent) -> bool:
        return event.topic == topic and event.payload.instrument_id == instrument_id

    return matches


def parse_events(raw: object) -> tuple[list[PerpsMarketEvent], int]:
    return parse_perps_market_events(raw)
