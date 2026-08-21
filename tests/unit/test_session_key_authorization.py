"""Scoped session-key authorization and signing regression tests."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import urlparse

import httpx
import pytest
from _relayer_helpers import (
    PK_PROXY_WALLET,
    SPENDER,
    TOKEN,
    install_relayer_handler,
    install_relayer_routes,
    install_sync_relayer_handler,
    make_deposit_client,
    make_sync_deposit_client,
    request_json,
)
from eth_abi.abi import decode as abi_decode
from eth_account import Account

from polymarket import AuthorizeSessionKeyResult, SessionKeyKnownScope, UserInputError

_AUTHORIZATIONS_PATH = "/v1/session-signers/authorizations"
_EXECUTE_PARAMS_PATH = "/v1/account/transactions/params"
_SESSION_ACCOUNT = Account.from_key(PK_PROXY_WALLET)
_SESSION_ADDRESS = _SESSION_ACCOUNT.address
_TRANSACTION_HASH = "0x" + "ab" * 32
_TRANSACTION_ID = "tx-session-key"
_SESSION_SIGNER_MAGIC_BYTES = bytes.fromhex("6492" * 16)
_NEWER_SCOPE = "NEWER_SCOPE"


def _authorization_handler(
    captured: list[httpx.Request],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == _EXECUTE_PARAMS_PATH:
            return httpx.Response(
                200,
                json={"address": _SESSION_ADDRESS, "nonce": "7"},
                request=request,
            )
        if path == _AUTHORIZATIONS_PATH:
            return httpx.Response(
                200,
                json={
                    "operationId": "operation-1",
                    "status": "PENDING",
                    "transactionHash": None,
                    "transactionId": _TRANSACTION_ID,
                },
                request=request,
            )
        if path == f"/v1/account/transactions/{_TRANSACTION_ID}":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": _TRANSACTION_HASH,
                    "transaction_id": _TRANSACTION_ID,
                },
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return handler


def _assert_authorization_result_and_request(
    result: AuthorizeSessionKeyResult,
    captured: list[httpx.Request],
    *,
    requested_expiry: datetime,
    wallet: str,
) -> None:
    expected_expiry = requested_expiry.astimezone(UTC).replace(microsecond=0)
    assert result.operation_id == "operation-1"
    assert result.session_key.address.lower() == _SESSION_ADDRESS.lower()
    assert result.session_key.scopes == (
        SessionKeyKnownScope.CLOB,
        SessionKeyKnownScope.COMBOSRFQ,
        _NEWER_SCOPE,
    )
    assert result.session_key.valid_until == expected_expiry
    assert result.transaction.transaction_hash == _TRANSACTION_HASH
    assert result.transaction.transaction_id == _TRANSACTION_ID

    authorization_requests = [
        request for request in captured if urlparse(str(request.url)).path == _AUTHORIZATIONS_PATH
    ]
    assert len(authorization_requests) == 1
    request = authorization_requests[0]
    assert request.headers["Idempotency-Key"] == "authorization-1"
    body = cast(dict[str, object], request_json(request))
    assert body["nonce"] == "7"
    assert body["scopes"] == ["CLOB", "COMBOSRFQ", _NEWER_SCOPE]
    session_signer_address = body["sessionSignerAddress"]
    assert isinstance(session_signer_address, str)
    assert session_signer_address.lower() == _SESSION_ADDRESS.lower()
    assert body["validUntil"] == str(int(expected_expiry.timestamp()))
    wallet_address = body["walletAddress"]
    assert isinstance(wallet_address, str)
    assert wallet_address.lower() == wallet.lower()
    signature = body["signature"]
    assert isinstance(signature, str)
    assert len(signature) == 2 + 65 * 2


def test_authorize_session_key_async_normalizes_and_submits_request() -> None:
    captured: list[httpx.Request] = []
    requested_expiry = datetime.now(UTC) + timedelta(minutes=15, microseconds=123_456)

    async def run() -> tuple[AuthorizeSessionKeyResult, str]:
        client = await make_deposit_client()
        install_relayer_handler(client, _authorization_handler(captured))
        try:
            result = await client.authorize_session_key(
                address=_SESSION_ADDRESS,
                scopes=(
                    _NEWER_SCOPE,
                    SessionKeyKnownScope.COMBOSRFQ,
                    SessionKeyKnownScope.CLOB,
                    _NEWER_SCOPE,
                    SessionKeyKnownScope.CLOB,
                ),
                valid_until=requested_expiry,
                idempotency_key=" authorization-1 ",
            )
            return result, str(client.wallet)
        finally:
            await client.close()

    result, wallet = asyncio.run(run())
    _assert_authorization_result_and_request(
        result,
        captured,
        requested_expiry=requested_expiry,
        wallet=wallet,
    )


def test_authorize_session_key_sync_normalizes_and_submits_request() -> None:
    captured: list[httpx.Request] = []
    requested_expiry = datetime.now(UTC) + timedelta(minutes=15, microseconds=123_456)

    with make_sync_deposit_client() as client:
        install_sync_relayer_handler(client, _authorization_handler(captured))
        result = client.authorize_session_key(
            address=_SESSION_ADDRESS,
            scopes=(
                _NEWER_SCOPE,
                SessionKeyKnownScope.COMBOSRFQ,
                SessionKeyKnownScope.CLOB,
                _NEWER_SCOPE,
                SessionKeyKnownScope.CLOB,
            ),
            valid_until=requested_expiry,
            idempotency_key=" authorization-1 ",
        )
        wallet = str(client.wallet)

    _assert_authorization_result_and_request(
        result,
        captured,
        requested_expiry=requested_expiry,
        wallet=wallet,
    )


def test_authorize_session_key_rejects_address_without_0x_prefix() -> None:
    with (
        make_sync_deposit_client() as client,
        pytest.raises(UserInputError, match="valid EVM address"),
    ):
        client.authorize_session_key(
            address=_SESSION_ADDRESS.removeprefix("0x"),
            scopes=(SessionKeyKnownScope.CLOB,),
            valid_until=datetime.now(UTC) + timedelta(minutes=15),
        )


def test_authorize_session_key_rejects_invalid_cross_field_combinations() -> None:
    valid_expiry = datetime.now(UTC) + timedelta(minutes=15)
    client = make_sync_deposit_client()
    try:
        with pytest.raises(UserInputError, match="must differ from the Deposit Wallet"):
            client.authorize_session_key(
                address=str(client.wallet),
                scopes=(SessionKeyKnownScope.CLOB,),
                valid_until=valid_expiry,
            )

        with pytest.raises(UserInputError, match="ALL cannot be combined"):
            client.authorize_session_key(
                address=_SESSION_ADDRESS,
                scopes=(SessionKeyKnownScope.ALL, SessionKeyKnownScope.CLOB),
                valid_until=valid_expiry,
            )

        with pytest.raises(UserInputError, match="non-empty strings"):
            client.authorize_session_key(
                address=_SESSION_ADDRESS,
                scopes=("",),
                valid_until=valid_expiry,
            )

        with pytest.raises(UserInputError, match="timezone-aware datetime"):
            client.authorize_session_key(
                address=_SESSION_ADDRESS,
                scopes=(SessionKeyKnownScope.CLOB,),
                valid_until=datetime.now(),
            )
    finally:
        client.close()


def test_session_signer_gasless_payload_wraps_the_owner_signature() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        client._ctx = dataclasses.replace(client._ctx, signer=_SESSION_ACCOUNT)
        install_relayer_routes(
            client,
            captured,
            {
                _EXECUTE_PARAMS_PATH: {"address": _SESSION_ADDRESS, "nonce": "11"},
                "/submit": {
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-gasless",
                },
            },
        )
        try:
            await client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        finally:
            await client.close()

    asyncio.run(run())

    submit_requests = [
        request for request in captured if urlparse(str(request.url)).path == "/submit"
    ]
    assert len(submit_requests) == 1
    body = cast(dict[str, object], request_json(submit_requests[0]))
    from_address = body["from"]
    assert isinstance(from_address, str)
    assert from_address.lower() == _SESSION_ADDRESS.lower()
    signature = body["signature"]
    assert isinstance(signature, str)
    raw = bytes.fromhex(signature.removeprefix("0x"))
    assert raw[-32:] == _SESSION_SIGNER_MAGIC_BYTES
    signer_id, salt, owner_signature = cast(
        tuple[bytes, bytes, bytes],
        abi_decode(["bytes32", "bytes32", "bytes"], raw[:-32]),
    )
    assert signer_id == bytes.fromhex(_SESSION_ADDRESS[2:]).rjust(32, b"\x00")
    assert salt == b"\x00" * 32
    assert len(owner_signature) == 65
