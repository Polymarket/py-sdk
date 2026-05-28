from datetime import UTC, datetime

import pytest

from polymarket._internal.actions.auth import (
    build_l1_auth_headers,
    parse_api_key_creds,
    parse_api_keys_response,
    parse_builder_api_key_creds,
    parse_builder_api_keys_response,
)
from polymarket._internal.l1_auth import ApiKeyAuthSignature
from polymarket.errors import UnexpectedResponseError


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


def test_parse_builder_api_key_creds_returns_builder_auth() -> None:
    creds = parse_builder_api_key_creds(
        {"key": "builder-key", "secret": "dGVzdA==", "passphrase": "builder-pass"}
    )

    assert creds.key == "builder-key"
    assert creds.secret == "dGVzdA=="
    assert creds.passphrase == "builder-pass"


def test_parse_builder_api_key_creds_rejects_missing_field() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_builder_api_key_creds({"key": "builder-key", "secret": "dGVzdA=="})


def test_parse_builder_api_keys_response_accepts_strings_and_metadata() -> None:
    keys = parse_builder_api_keys_response(
        [
            "builder-key-1",
            {"key": "builder-key-2", "createdAt": 1700000000000, "revokedAt": None},
        ]
    )

    assert keys[0].key == "builder-key-1"
    assert keys[0].created_at is None
    assert keys[1].key == "builder-key-2"
    assert keys[1].created_at == datetime.fromtimestamp(1700000000, tz=UTC)
    assert keys[1].revoked_at is None


def test_parse_builder_api_keys_response_rejects_non_list() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_builder_api_keys_response({"apiKeys": ["builder-key"]})
