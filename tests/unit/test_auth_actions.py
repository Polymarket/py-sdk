import inspect
from datetime import UTC, datetime
from typing import get_type_hints

import pytest

from polymarket._internal.actions.auth import (
    build_l1_auth_headers,
    parse_api_key_creds,
    parse_api_keys_response,
    parse_builder_api_key_creds,
    parse_builder_api_keys_response,
)
from polymarket._internal.l1_auth import ApiKeyAuthSignature
from polymarket.auth import BuilderApiKey
from polymarket.errors import UnexpectedResponseError
from polymarket.models.clob.api_key import BuilderApiKeyInfo


def _sig() -> ApiKeyAuthSignature:
    return ApiKeyAuthSignature(address="0xabc", nonce=0, signature="0xsig", timestamp=1700000000)


def test_build_l1_auth_headers_includes_all_four_fields() -> None:
    headers = build_l1_auth_headers(_sig())

    assert headers == {
        "POLY_ADDRESS": "0xabc",
        "POLY_NONCE": "0",
        "POLY_SIGNATURE": "0xsig",
        "POLY_TIMESTAMP": "1700000000",
    }


def test_parse_api_key_creds_renames_wire_apikey_to_key() -> None:
    creds = parse_api_key_creds({"apiKey": "k", "secret": "s", "passphrase": "p"})

    assert creds.key == "k"
    assert creds.secret == "s"
    assert creds.passphrase == "p"


def test_parse_api_key_creds_rejects_missing_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_api_key_creds({"apiKey": "k", "secret": "s"})


def test_parse_api_key_creds_rejects_non_dict() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_api_key_creds([])


def test_parse_api_keys_response_returns_tuple_of_strings() -> None:
    keys = parse_api_keys_response({"apiKeys": ["a", "b"]})

    assert keys == ("a", "b")


def test_parse_api_keys_response_accepts_empty_list() -> None:
    assert parse_api_keys_response({"apiKeys": []}) == ()


def test_parse_api_keys_response_rejects_missing_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_api_keys_response({})


def test_parse_api_keys_response_rejects_non_string_entry() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_api_keys_response({"apiKeys": [1, 2]})


def test_parse_builder_api_key_creds_returns_builder_api_key() -> None:
    creds = parse_builder_api_key_creds({"key": "k", "secret": "s", "passphrase": "p"})

    assert isinstance(creds, BuilderApiKey)
    assert (creds.key, creds.secret, creds.passphrase) == ("k", "s", "p")


def test_parse_builder_api_key_creds_rejects_missing_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_builder_api_key_creds({"key": "k", "secret": "s"})


def test_parse_builder_api_key_creds_rejects_non_dict() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_builder_api_key_creds([])


def test_parse_builder_api_keys_response_parses_records() -> None:
    keys = parse_builder_api_keys_response(
        [{"key": "k", "createdAt": "1700000000000", "revokedAt": None}]
    )

    assert len(keys) == 1
    assert keys[0].key == "k"
    assert keys[0].created_at is not None
    assert keys[0].revoked_at is None


def test_builder_api_key_info_annotations_and_signature_expose_datetimes() -> None:
    hints = get_type_hints(BuilderApiKeyInfo, include_extras=True)
    assert hints["created_at"] == (datetime | None)
    assert hints["revoked_at"] == (datetime | None)

    parameters = inspect.signature(BuilderApiKeyInfo).parameters
    assert parameters["createdAt"].annotation == (datetime | None)
    assert parameters["revokedAt"].annotation == (datetime | None)


def test_parse_builder_api_keys_response_preserves_timestamp_formats() -> None:
    keys = parse_builder_api_keys_response(
        [
            {
                "key": "k",
                "createdAt": 1700000000000,
                "revokedAt": "2023-11-14T22:13:25Z",
            }
        ]
    )

    assert keys[0].created_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert keys[0].revoked_at == datetime(2023, 11, 14, 22, 13, 25, tzinfo=UTC)


def test_parse_builder_api_keys_response_normalizes_bare_string_elements() -> None:
    keys = parse_builder_api_keys_response(["a", {"key": "b"}])

    assert [k.key for k in keys] == ["a", "b"]


def test_parse_builder_api_keys_response_accepts_empty_list() -> None:
    assert parse_builder_api_keys_response([]) == ()


def test_parse_builder_api_keys_response_rejects_non_list() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_builder_api_keys_response({"apiKeys": []})
