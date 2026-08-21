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

from polymarket import (
    AsyncSecureClient,
    AuthorizedSessionKey,
    AuthorizeSessionKeyResult,
    RevokeSessionKeyResult,
    SecureClient,
    SessionKeyKnownScope,
    UnexpectedResponseError,
    UserInputError,
)
from polymarket.clients._transport import AsyncTransport, SyncTransport

_AUTHORIZATIONS_PATH = "/v1/session-signers/authorizations"
_EXECUTE_PARAMS_PATH = "/v1/account/transactions/params"
_REVOCATIONS_PATH = "/v1/session-signers/revocations"
_SESSION_KEYS_PATH = "/v1/user/session-signers"
_SESSION_ACCOUNT = Account.from_key(PK_PROXY_WALLET)
_SESSION_ADDRESS = _SESSION_ACCOUNT.address
_TRANSACTION_HASH = "0x" + "ab" * 32
_TRANSACTION_ID = "tx-session-key"
_REVOCATION_TRANSACTION_ID = "tx-session-key-revocation"
_SESSION_SIGNER_MAGIC_BYTES = bytes.fromhex("6492" * 16)
_NEWER_SCOPE = "NEWER_SCOPE"
_LISTED_EXPIRY = 1_900_000_000


def _authorization_handler(
    captured: list[httpx.Request],
    *,
    wallet: str,
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
        if path == _SESSION_KEYS_PATH:
            authorization_request = next(
                captured_request
                for captured_request in captured
                if urlparse(str(captured_request.url)).path == _AUTHORIZATIONS_PATH
            )
            body = cast(dict[str, object], request_json(authorization_request))
            address = body["sessionSignerAddress"]
            scopes = body["scopes"]
            valid_until = body["validUntil"]
            assert isinstance(address, str)
            assert isinstance(scopes, list)
            assert isinstance(valid_until, str)
            return httpx.Response(
                200,
                json={
                    "wallet": wallet,
                    "signers": [
                        {
                            "address": address,
                            "scopes": scopes,
                            "valid_until": int(valid_until),
                        }
                    ],
                },
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return handler


def _install_secure_clob_handler(
    client: AsyncSecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(
            base_url="https://clob.test",
            transport=httpx.MockTransport(handler),
        ),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)


def _install_sync_secure_clob_handler(
    client: SecureClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    transport = SyncTransport(
        base_url="https://clob.test",
        client=httpx.Client(
            base_url="https://clob.test",
            transport=httpx.MockTransport(handler),
        ),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)


def _management_handler(
    captured: list[httpx.Request],
    *,
    wallet: str,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == _SESSION_KEYS_PATH:
            return httpx.Response(
                200,
                json={
                    "wallet": wallet.lower(),
                    "signers": [
                        {
                            "address": _SESSION_ADDRESS.lower(),
                            "scopes": [SessionKeyKnownScope.CLOB.value, _NEWER_SCOPE],
                            "valid_until": _LISTED_EXPIRY,
                        }
                    ],
                },
                request=request,
            )
        if path == _EXECUTE_PARAMS_PATH:
            return httpx.Response(
                200,
                json={"address": _SESSION_ADDRESS, "nonce": "9"},
                request=request,
            )
        if path == _REVOCATIONS_PATH:
            return httpx.Response(
                200,
                json={
                    "fenced": True,
                    "operationId": "revocation-1",
                    "status": "PENDING",
                    "transactionId": _REVOCATION_TRANSACTION_ID,
                },
                request=request,
            )
        if path == f"/v1/account/transactions/{_REVOCATION_TRANSACTION_ID}":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": _TRANSACTION_HASH,
                    "transaction_id": _REVOCATION_TRANSACTION_ID,
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
        wallet = str(client.wallet)
        handler = _authorization_handler(captured, wallet=wallet)
        install_relayer_handler(client, handler)
        _install_secure_clob_handler(client, handler)
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
            return result, wallet
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
        wallet = str(client.wallet)
        handler = _authorization_handler(captured, wallet=wallet)
        install_sync_relayer_handler(client, handler)
        _install_sync_secure_clob_handler(client, handler)
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

    _assert_authorization_result_and_request(
        result,
        captured,
        requested_expiry=requested_expiry,
        wallet=wallet,
    )


def _assert_fetch_and_revocation(
    session_keys: tuple[AuthorizedSessionKey, ...],
    revocation: RevokeSessionKeyResult,
    captured: list[httpx.Request],
    *,
    wallet: str,
) -> None:
    assert len(session_keys) == 1
    session_key = session_keys[0]
    assert session_key.address.lower() == _SESSION_ADDRESS.lower()
    assert session_key.scopes == (SessionKeyKnownScope.CLOB, _NEWER_SCOPE)
    assert session_key.valid_until == datetime.fromtimestamp(_LISTED_EXPIRY, tz=UTC)

    assert revocation.operation_id == "revocation-1"
    assert revocation.transaction.transaction_hash == _TRANSACTION_HASH
    assert revocation.transaction.transaction_id == _REVOCATION_TRANSACTION_ID

    revocation_requests = [
        request for request in captured if urlparse(str(request.url)).path == _REVOCATIONS_PATH
    ]
    assert len(revocation_requests) == 1
    request = revocation_requests[0]
    assert request.headers["Idempotency-Key"] == "revocation-key"
    body = cast(dict[str, object], request_json(request))
    assert body["nonce"] == "9"
    assert body["sessionSignerAddress"] == _SESSION_ADDRESS
    wallet_address = body["walletAddress"]
    assert isinstance(wallet_address, str)
    assert wallet_address.lower() == wallet.lower()
    deadline = body["deadline"]
    assert isinstance(deadline, str)
    assert deadline.isdigit()
    signature = body["signature"]
    assert isinstance(signature, str)
    assert len(signature) == 2 + 65 * 2


def test_fetch_and_revoke_session_key_async() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[tuple[AuthorizedSessionKey, ...], RevokeSessionKeyResult, str]:
        client = await make_deposit_client()
        wallet = str(client.wallet)
        handler = _management_handler(captured, wallet=wallet)
        install_relayer_handler(client, handler)
        _install_secure_clob_handler(client, handler)
        try:
            session_keys = await client.fetch_session_keys()
            revocation = await client.revoke_session_key(
                address=_SESSION_ADDRESS,
                idempotency_key=" revocation-key ",
            )
            return session_keys, revocation, wallet
        finally:
            await client.close()

    session_keys, revocation, wallet = asyncio.run(run())
    _assert_fetch_and_revocation(
        session_keys,
        revocation,
        captured,
        wallet=wallet,
    )


def test_fetch_and_revoke_session_key_sync() -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        wallet = str(client.wallet)
        handler = _management_handler(captured, wallet=wallet)
        install_sync_relayer_handler(client, handler)
        _install_sync_secure_clob_handler(client, handler)
        session_keys = client.fetch_session_keys()
        revocation = client.revoke_session_key(
            address=_SESSION_ADDRESS,
            idempotency_key=" revocation-key ",
        )

    _assert_fetch_and_revocation(
        session_keys,
        revocation,
        captured,
        wallet=wallet,
    )


def test_fetch_session_keys_rejects_a_different_response_wallet() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"wallet": "0x000000000000000000000000000000000000dEaD", "signers": []},
            request=request,
        )

    with make_sync_deposit_client() as client:
        _install_sync_secure_clob_handler(client, handler)
        with pytest.raises(UnexpectedResponseError, match="does not match authenticated wallet"):
            client.fetch_session_keys()


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
