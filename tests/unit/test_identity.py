import copy
from typing import Any

import pytest
from _bearer import fake_access_token
from eth_account import Account

from polymarket import ApiKeyCreds
from polymarket._internal.actions.identity import (
    build_migrate_request,
    parse_access_token_claims,
    parse_issued_claims,
    parse_ownership_challenge,
    sign_ownership_challenge,
)
from polymarket.errors import UnexpectedResponseError, UserInputError

SIGNER = Account.from_key("0x" + "22" * 32)
CHAIN_ID = 137


def _challenge(**overrides: Any) -> dict[str, Any]:
    challenge: dict[str, Any] = {
        "challengeId": "2f1c8a1e-6f3b-4c1e-9d2a-3b4c5d6e7f80",
        "expiresAt": "2026-11-10T12:00:00Z",
        "typedData": {
            "domain": {"name": "ClobAuthDomain", "version": "1", "chainId": CHAIN_ID},
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "ClobAuth": [
                    {"name": "address", "type": "address"},
                    {"name": "timestamp", "type": "string"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "message", "type": "string"},
                ],
            },
            "primaryType": "ClobAuth",
            "message": {
                "address": SIGNER.address,
                "timestamp": "1700000000",
                "nonce": "7",
                "message": "This message attests that I control the given wallet",
            },
        },
    }
    challenge.update(overrides)
    return challenge


def _tampered(path: tuple[str, ...], value: object) -> dict[str, Any]:
    challenge = copy.deepcopy(_challenge())
    target = challenge
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return challenge


@pytest.mark.parametrize(
    "challenge",
    [
        _tampered(("typedData", "domain", "verifyingContract"), "0x" + "00" * 20),
        _tampered(("typedData", "domain", "name"), "OtherDomain"),
        _tampered(("typedData", "primaryType"), "Order"),
        _tampered(("typedData", "message", "message"), "I approve this transfer"),
        _tampered(("typedData", "message", "amount"), "1"),
        _tampered(("typedData", "message", "nonce"), "-1"),
        _tampered(("typedData", "types", "Transfer"), []),
        _tampered(("typedData", "types", "ClobAuth"), [{"name": "address", "type": "address"}]),
        _tampered(("challengeId",), "not-a-uuid"),
    ],
)
def test_challenge_other_than_the_clob_auth_attestation_is_rejected(
    challenge: dict[str, Any],
) -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_ownership_challenge(challenge)


@pytest.mark.parametrize(
    ("chain_id", "address"),
    [(CHAIN_ID + 1, SIGNER.address), (CHAIN_ID, Account.from_key("0x" + "33" * 32).address)],
)
def test_challenge_for_another_signer_or_network_is_not_signed(chain_id: int, address: str) -> None:
    challenge = parse_ownership_challenge(_tampered(("typedData", "message", "address"), address))

    with pytest.raises(UnexpectedResponseError, match="signer and network"):
        sign_ownership_challenge(SIGNER, challenge, chain_id=chain_id)


def test_migration_proves_ownership_without_sending_the_secret() -> None:
    credentials = ApiKeyCreds(
        key="api-key", passphrase="passphrase", secret="c2VjcmV0LWZvci1taWdyYXRpb24tdGVzdHM="
    )

    body = build_migrate_request(
        credentials=credentials, signer=SIGNER.address, wallet=None, timestamp=1700000000
    )

    assert body == {
        "signer": SIGNER.address,
        "timestamp": "1700000000",
        "clob_api_key": "api-key",
        "clob_passphrase": "passphrase",
        # Reference proof produced by the TypeScript SDK for the same input.
        "clob_signature": "lDEVgzplUyVlmKelGVoqKeJ8AYpYoV2ltmcLbZ_oEQU=",
    }
    assert credentials.secret not in str(body)


def test_unreadable_token_is_a_caller_error_when_supplied_and_a_server_error_when_issued() -> None:
    token = fake_access_token(sub="not-an-address", exp=1)

    with pytest.raises(UserInputError):
        parse_access_token_claims(token)
    with pytest.raises(UnexpectedResponseError):
        parse_issued_claims(token)
