from decimal import Decimal

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.rfq import ComboMarket

_CONDITION_ID = "0x4cd77d456c83e7d8c569a8fb8f6396c3f40154f657e6d970733e2b1b6a7110ff"


def _combo_market_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "1897034",
        "condition_id": _CONDITION_ID,
        "position_ids": ["POSITION-YES", "POSITION-NO"],
        "slug": "combo-market",
        "title": "Will this market resolve Yes?",
        "outcomes": ["Yes", "No"],
        "outcome_prices": ["0.695", "0.305"],
        "image": "https://example.test/image.png",
        "volume": 524879.8786760003,
        "tags": ["sports", "soccer"],
    }
    payload.update(overrides)
    return payload


def test_combo_market_parses_catalog_payload() -> None:
    market = ComboMarket.parse_response(_combo_market_payload())

    assert market.id == "1897034"
    assert market.condition_id == _CONDITION_ID
    assert market.outcomes.yes.label == "Yes"
    assert market.outcomes.yes.position_id == "POSITION-YES"
    assert market.outcomes.yes.price == Decimal("0.695")
    assert market.outcomes.no.label == "No"
    assert market.outcomes.no.position_id == "POSITION-NO"
    assert market.outcomes.no.price == Decimal("0.305")


def test_combo_market_requires_binary_aligned_outcomes() -> None:
    with pytest.raises(UnexpectedResponseError):
        ComboMarket.parse_response(_combo_market_payload(outcomes=["Yes"]))
