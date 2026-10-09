from decimal import Decimal
from typing import Any

import pytest

from polymarket import PublicClient, TokenModule, TokenReference
from polymarket._internal.actions.data import build_get_token_references_spec
from polymarket.errors import UnexpectedResponseError, UserInputError

CONDITION = "0x" + "ab" * 32
STRUCTURAL = "0x03" + "cd" * 30


def token_payload(**changes: object) -> dict[str, Any]:
    # Representative fields from pinned tokens.rs; this is not a live capture.
    return {
        "token_id": "123",
        "condition_id": CONDITION,
        "structural_condition_id": None,
        "module": "v1_ctf",
        "outcome_index": 1,
        "clob_index": 0,
        "outcome": "Yes",
        "opposite_token_id": "124",
        "resolved": True,
        "final_price": 0.5,
        "title": "Question?",
        "market_slug": "question",
        "closed": True,
        "neg_risk": False,
        "neg_risk_market_id": None,
        "question_index": None,
        "event_id": 1234,
        "event_slug": "event",
        **changes,
    }


NULLABLE_FIELDS = [
    "structural_condition_id",
    "clob_index",
    "outcome",
    "opposite_token_id",
    "final_price",
    "title",
    "market_slug",
    "closed",
    "neg_risk",
    "neg_risk_market_id",
    "question_index",
    "event_id",
    "event_slug",
]


def test_canonical_requests_preserve_order_and_condition_width() -> None:
    spec = build_get_token_references_spec(asset_ids=[" 002 ", "", "1", "02", "000"])
    assert (spec.service, spec.method, spec.path) == ("data", "GET", "/v2/tokens")
    assert spec.params == {"token_id": "2,1,0"}
    assert build_get_token_references_spec(
        condition_ids=[f" {STRUCTURAL.upper().replace('0X', '0x')} ", CONDITION, STRUCTURAL]
    ).params == {"condition": f"{STRUCTURAL},{CONDITION}"}
    assert build_get_token_references_spec(asset_ids="0" * 100 + "1" * 78).params == {
        "token_id": "1" * 78
    }
    assert build_get_token_references_spec(asset_ids="9" * 78).params == {"token_id": "9" * 78}


@pytest.mark.parametrize("limit", [49, 50])
def test_asset_limit_counts_normalized_distinct_values(limit: int) -> None:
    ids = [str(n) for n in range(limit)]
    params = build_get_token_references_spec(asset_ids=[*ids, *["0" + s for s in ids]]).params
    assert params == {"token_id": ",".join(ids)}


@pytest.mark.parametrize("limit", [9, 10])
def test_condition_limit_counts_normalized_distinct_values(limit: int) -> None:
    ids = ["0x" + f"{n:064x}" for n in range(limit)]
    assert build_get_token_references_spec(condition_ids=[*ids, *ids]).params == {
        "condition": ",".join(ids)
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"asset_ids": []},
        {"asset_ids": ["", " "]},
        {"asset_ids": ["1"], "condition_ids": []},
        {"asset_ids": ["1"], "condition_ids": CONDITION},
        {"asset_ids": "1,2"},
        {"asset_ids": "1e5"},
        {"asset_ids": "0x1f"},
        {"asset_ids": "-3"},
        {"asset_ids": "١"},
        {"asset_ids": "1" * 79},
        {"asset_ids": [str(n) for n in range(51)]},
        {"asset_ids": 123},
        {"asset_ids": [True]},
        {"condition_ids": ["0x" + f"{n:064x}" for n in range(11)]},
        {"condition_ids": "0X" + "a" * 64},
        {"condition_ids": "0x" + "a" * 63},
        {"condition_ids": "0x" + "z" * 64},
        {"condition_ids": [1]},
    ],
)
def test_public_validation_precedes_transport(kwargs: dict[str, Any]) -> None:
    with PublicClient() as client, pytest.raises(UserInputError):
        client.get_token_references(**kwargs)


def test_direct_collection_and_canonical_model_roundtrip() -> None:
    spec = build_get_token_references_spec(asset_ids="123")
    rows = spec.parse({"data": [token_payload(), token_payload(token_id="124"), token_payload()]})
    assert tuple(row.asset_id for row in rows) == ("123", "124", "123")
    assert rows[0].opposite_asset_id == "124"
    assert rows[0].module is TokenModule.V1_CTF
    assert rows[0].final_price == Decimal("0.5")
    assert rows[0].event_id == "1234"
    assert spec.parse({"data": []}) == ()
    assert TokenReference.model_validate(rows[0].model_dump()) == rows[0]
    assert TokenReference.model_validate_json(rows[0].model_dump_json()) == rows[0]


@pytest.mark.parametrize("module", ["v1_ctf", "binary", "neg_risk", "combo"])
def test_modules_and_required_explicit_nulls(module: str) -> None:
    row = TokenReference.parse_response(
        token_payload(**dict.fromkeys(NULLABLE_FIELDS), module=module)
    )
    assert row.module == module
    assert row.final_price is None and row.event_id is None and row.clob_index is None
    assert row.structural_condition_id is None and row.opposite_asset_id is None


@pytest.mark.parametrize("field", NULLABLE_FIELDS)
def test_missing_nullable_field_is_contract_failure(field: str) -> None:
    payload = token_payload()
    del payload[field]
    with pytest.raises(UnexpectedResponseError):
        TokenReference.parse_response(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"module": "future"},
        {"condition_id": "not-hex"},
        {"structural_condition_id": STRUCTURAL},
        {"outcome_index": 0.5},
        {"final_price": "not-a-price"},
        {"resolved": "true"},
        {"event_id": 1.5},
    ],
)
def test_invalid_contract_fields(changes: dict[str, object]) -> None:
    with pytest.raises(UnexpectedResponseError):
        TokenReference.parse_response(token_payload(**changes))
