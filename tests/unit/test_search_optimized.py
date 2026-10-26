import asyncio
from decimal import Decimal

import httpx
import pytest
import respx

from polymarket import AsyncPublicClient, Event, Market, PublicClient, SearchEvent, SearchResults
from polymarket.errors import UnexpectedResponseError


def optimized_event() -> dict[str, object]:
    return {
        "id": "event-1",
        "title": "Example",
        "slug": "example",
        "active": True,
        "startDate": "2026-01-01T00:00:00Z",
        "markets": [
            {
                "question": "Example?",
                "slug": "example-market",
                "active": True,
                "outcomes": ["Yes", "No"],
                "outcomePrices": ["0.6", "0.4"],
                "bestBid": 0,
                "bestAsk": 0.6,
                "spread": 0.6,
            }
        ],
    }


def test_compact_search_preserves_summary_without_inventing_market_id() -> None:
    event = SearchResults.parse_response({"events": [optimized_event()]}).events[0]
    assert isinstance(event, SearchEvent)
    assert event.active is True
    assert event.start_date is not None
    market = event.markets[0]
    assert market.id is None
    assert market.slug == "example-market"
    assert market.outcome_prices == (Decimal("0.6"), Decimal("0.4"))
    assert market.best_bid == Decimal(0)
    assert market.best_ask == Decimal("0.6")
    with pytest.raises(UnexpectedResponseError):
        Market.parse_response(optimized_event()["markets"][0])  # type: ignore[index]
    with pytest.raises(UnexpectedResponseError):
        Event.parse_response(optimized_event())


def test_full_search_retains_full_market_model() -> None:
    payload = {"id": "event-1", "markets": [{"id": "market-1", "outcomes": ["Yes", "No"]}]}
    event = SearchResults.parse_response({"events": [payload]}).events[0]
    assert isinstance(event, Event)
    assert isinstance(event.markets[0], Market)
    assert event.markets[0].id == "market-1"


@pytest.mark.parametrize("has_more", [True, False])
def test_top_level_continuation(has_more: bool) -> None:
    page = SearchResults.parse_page_response({"hasMore": has_more})
    assert page.has_more is has_more


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_invalid_top_level_continuation(value: object) -> None:
    with pytest.raises(UnexpectedResponseError, match="hasMore"):
        SearchResults.parse_page_response({"hasMore": value})


@respx.mock
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_optimized_search_continues_to_exhaustion(mode: str) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"events": [optimized_event()], "hasMore": page == 1})

    respx.get("https://gamma-api.polymarket.com/public-search").mock(side_effect=handle)

    if mode == "sync":
        with PublicClient() as client:
            pages = list(client.search(q="example", optimized=True))
    else:

        async def run() -> list[object]:
            async with AsyncPublicClient() as client:
                return [page async for page in client.search(q="example", optimized=True)]

        pages = asyncio.run(run())
    assert len(pages) == 2
    assert [r.url.params["page"] for r in requests] == ["1", "2"]
    assert all(r.url.params["optimized"] == "true" for r in requests)
