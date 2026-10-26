import pytest

from polymarket._internal.data_envelope import (
    parse_data_envelope,
    parse_data_page,
    parse_optional_data_envelope,
)
from polymarket.errors import UnexpectedResponseError
from polymarket.models.data import UserVolume


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": {}, "pagination": {}},
        {"data": [], "pagination": {"has_more": True, "next_cursor": None}},
        {"data": [], "pagination": {"has_more": False, "next_cursor": "next"}},
        {"data": [], "pagination": {"has_more": True, "next_cursor": ""}},
        {"data": [], "pagination": {"has_more": 1, "next_cursor": "next"}},
        {"data": [], "pagination": {"has_more": False}},
    ],
)
def test_broken_page_envelopes_fail(payload: object) -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_data_page(payload, UserVolume.parse_response_list)


def test_page_and_optional_envelopes() -> None:
    page = parse_data_page(
        {"data": [], "pagination": {"has_more": True, "next_cursor": "next"}},
        UserVolume.parse_response_list,
    )
    assert page.server_next_cursor == "next"
    assert parse_optional_data_envelope({"data": None}, UserVolume.parse_response) is None
    volume = parse_data_envelope(
        {"data": {"volume": 1, "volume_usdc": 0.25, "trade_count": 2}}, UserVolume.parse_response
    )
    assert volume.trade_count == 2
    with pytest.raises(UnexpectedResponseError):
        parse_optional_data_envelope({}, UserVolume.parse_response)
