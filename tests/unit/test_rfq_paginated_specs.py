from polymarket._internal.actions import rfq as rfq_actions
from polymarket._internal.request import KeysetPaginatedSpec


def test_list_combo_markets_spec_uses_rfq_cursor_param() -> None:
    spec = rfq_actions.list_combo_markets_spec(exclude=["0xA", "0xB"])

    assert isinstance(spec, KeysetPaginatedSpec)
    assert spec.path == "/v1/combos/markets"
    assert spec.cursor_param == "cursor"
    assert spec.max_page_size == 100
    assert spec.base_params == {"exclude": "0xA,0xB"}
