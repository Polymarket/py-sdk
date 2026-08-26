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
    make_session_client,
    make_sync_deposit_client,
    make_sync_session_client,
    request_json,
)
from eth_account import Account

from polymarket import (
    AsyncSecureClient,
    AuthorizedSessionKey,
    AuthorizeSessionKeyResult,
    RelayerApiKey,
    RevokeSessionKeyResult,
    SecureClient,
    SessionKeyKnownScope,
    SessionKeyScope,
    TransactionFailedError,
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
_REVOCATION_OPERATION_ID = "op-session-key-revocation"
_NEWER_SCOPE = "NEWER_SCOPE"
_LISTED_EXPIRY = 1_900_000_000
_SESSION_SIGNER_MAGIC_HEX = "6492" * 16


def _authorization_handler(
    captured: list[httpx.Request],
    *,
    wallet: str,
    status: str = "SUBMITTED",
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
                    "operationId": "",
                    "status": status,
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
            listed_scopes = list(cast(list[str], scopes))
            return httpx.Response(
                200,
                json={
                    "wallet": wallet,
                    "signers": [
                        {
                            "address": address,
                            "scopes": listed_scopes,
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
    revocation_status: str = "FENCED",
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
                            "scopes": ["clob", f" {_NEWER_SCOPE.lower()} "],
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
                    "fenced": revocation_status
                    in {"FENCED", "SWEPT", "CHAIN_SUBMITTED", "CONFIRMED"},
                    "operationId": _REVOCATION_OPERATION_ID,
                    "status": revocation_status,
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
    expected_request_scopes: tuple[SessionKeyScope, ...],
    expected_session_scopes: tuple[SessionKeyScope, ...],
    requested_expiry: datetime,
    wallet: str,
) -> None:
    expected_expiry = requested_expiry.astimezone(UTC).replace(microsecond=0)
    assert not hasattr(result, "operation_id")
    assert result.session_key.address.lower() == _SESSION_ADDRESS.lower()
    assert result.session_key.scopes == expected_session_scopes
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
    assert body["scopes"] == [str(scope) for scope in expected_request_scopes]
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


def test_authorize_session_key_async_preserves_scopes_and_submits_request() -> None:
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
                    f" {_NEWER_SCOPE.lower()} ",
                    SessionKeyKnownScope.COMBOSRFQ,
                    " clob ",
                    _NEWER_SCOPE,
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
        expected_request_scopes=(
            f" {_NEWER_SCOPE.lower()} ",
            SessionKeyKnownScope.COMBOSRFQ,
            " clob ",
            _NEWER_SCOPE,
            _NEWER_SCOPE,
            SessionKeyKnownScope.CLOB,
        ),
        expected_session_scopes=(
            f" {_NEWER_SCOPE.lower()} ",
            SessionKeyKnownScope.COMBOSRFQ,
            " clob ",
            _NEWER_SCOPE,
            _NEWER_SCOPE,
            SessionKeyKnownScope.CLOB,
        ),
        requested_expiry=requested_expiry,
        wallet=wallet,
    )


def test_authorize_session_key_async_retries_the_exact_signed_payload() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_deposit_client()
        stable_handler = _authorization_handler(captured, wallet=str(client.wallet))
        lost_response = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal lost_response
            if urlparse(str(request.url)).path == _AUTHORIZATIONS_PATH and not lost_response:
                lost_response = True
                captured.append(request)
                raise httpx.ReadTimeout("response lost after submission", request=request)
            return stable_handler(request)

        config = dataclasses.replace(
            client._ctx.environment_config,
            relayer_poll_frequency_ms=0,
        )
        client._ctx = dataclasses.replace(client._ctx, _resolved_environment_config=config)
        install_relayer_handler(client, handler)
        _install_secure_clob_handler(client, handler)
        try:
            await client.authorize_session_key(
                address=_SESSION_ADDRESS,
                scopes=("clob",),
                valid_until=datetime.now(UTC) + timedelta(minutes=15),
                idempotency_key="exact-authorization",
            )
        finally:
            await client.close()

    asyncio.run(run())

    authorization_requests = [
        request for request in captured if urlparse(str(request.url)).path == _AUTHORIZATIONS_PATH
    ]
    assert len(authorization_requests) == 2
    first, second = authorization_requests
    assert first.content == second.content
    assert first.headers["Idempotency-Key"] == second.headers["Idempotency-Key"]
    assert first.headers["Idempotency-Key"] == "exact-authorization"
    assert sum(urlparse(str(request.url)).path == _EXECUTE_PARAMS_PATH for request in captured) == 1


@pytest.mark.parametrize(
    "authorization_status",
    ("SUBMITTED", "REGISTRY_PENDING", "REGISTERED"),
)
def test_authorize_session_key_sync_uses_default_scopes(authorization_status: str) -> None:
    captured: list[httpx.Request] = []
    requested_expiry = datetime.now(UTC) + timedelta(minutes=15, microseconds=123_456)

    with make_sync_deposit_client() as client:
        wallet = str(client.wallet)
        handler = _authorization_handler(
            captured,
            wallet=wallet,
            status=authorization_status,
        )
        install_sync_relayer_handler(client, handler)
        _install_sync_secure_clob_handler(client, handler)
        result = client.authorize_session_key(
            address=_SESSION_ADDRESS,
            valid_until=requested_expiry,
            idempotency_key=" authorization-1 ",
        )

    _assert_authorization_result_and_request(
        result,
        captured,
        expected_request_scopes=(SessionKeyKnownScope.ALL,),
        expected_session_scopes=(SessionKeyKnownScope.ALL,),
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
    assert session_key.scopes == ("clob", f" {_NEWER_SCOPE.lower()} ")
    assert session_key.valid_until == datetime.fromtimestamp(_LISTED_EXPIRY, tz=UTC)

    assert revocation.operation_id == _REVOCATION_OPERATION_ID
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

    paths = [urlparse(str(request.url)).path for request in captured]
    assert f"/v1/account/transactions/{_REVOCATION_TRANSACTION_ID}" in paths


def test_fetch_and_revoke_session_key_async() -> None:
    captured: list[httpx.Request] = []

    async def run() -> tuple[
        tuple[AuthorizedSessionKey, ...],
        RevokeSessionKeyResult,
        str,
    ]:
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


@pytest.mark.parametrize(
    "revocation_status",
    ("PENDING", "FENCED", "SWEPT", "CHAIN_SUBMITTED", "CONFIRMED"),
)
def test_fetch_and_revoke_session_key_sync(revocation_status: str) -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        wallet = str(client.wallet)
        handler = _management_handler(
            captured,
            wallet=wallet,
            revocation_status=revocation_status,
        )
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


def test_revoke_session_key_sync_retries_the_exact_signed_payload() -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        stable_handler = _management_handler(captured, wallet=str(client.wallet))
        lost_response = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal lost_response
            if urlparse(str(request.url)).path == _REVOCATIONS_PATH and not lost_response:
                lost_response = True
                captured.append(request)
                raise httpx.ReadTimeout("response lost after submission", request=request)
            return stable_handler(request)

        config = dataclasses.replace(
            client._ctx.environment_config,
            relayer_poll_frequency_ms=0,
        )
        client._ctx = dataclasses.replace(client._ctx, _resolved_environment_config=config)
        install_sync_relayer_handler(client, handler)
        revocation = client.revoke_session_key(
            address=_SESSION_ADDRESS,
            idempotency_key="exact-revocation",
        )

    assert revocation.operation_id == _REVOCATION_OPERATION_ID
    revocation_requests = [
        request for request in captured if urlparse(str(request.url)).path == _REVOCATIONS_PATH
    ]
    assert len(revocation_requests) == 2
    first, second = revocation_requests
    assert first.content == second.content
    assert first.headers["Idempotency-Key"] == second.headers["Idempotency-Key"]
    assert first.headers["Idempotency-Key"] == "exact-revocation"
    assert sum(urlparse(str(request.url)).path == _EXECUTE_PARAMS_PATH for request in captured) == 1


def test_revoke_session_key_waits_for_confirmation_before_returning() -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        handler = _management_handler(captured, wallet=str(client.wallet))
        install_sync_relayer_handler(client, handler)
        revocation = client.revoke_session_key(address=_SESSION_ADDRESS)

    assert revocation.transaction.transaction_id == _REVOCATION_TRANSACTION_ID
    assert revocation.transaction.transaction_hash == _TRANSACTION_HASH
    assert (
        sum(
            urlparse(str(request.url)).path
            == f"/v1/account/transactions/{_REVOCATION_TRANSACTION_ID}"
            for request in captured
        )
        == 1
    )


def test_authorize_session_key_retries_transient_registry_read_failure() -> None:
    captured: list[httpx.Request] = []

    async def run() -> AuthorizeSessionKeyResult:
        client = await make_deposit_client()
        stable_handler = _authorization_handler(captured, wallet=str(client.wallet))
        registry_unavailable = True

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal registry_unavailable
            if urlparse(str(request.url)).path == _SESSION_KEYS_PATH and registry_unavailable:
                registry_unavailable = False
                captured.append(request)
                return httpx.Response(503, json={"error": "registry unavailable"}, request=request)
            return stable_handler(request)

        config = dataclasses.replace(
            client._ctx.environment_config,
            relayer_max_polls=3,
            relayer_poll_frequency_ms=0,
        )
        client._ctx = dataclasses.replace(client._ctx, _resolved_environment_config=config)
        install_relayer_handler(client, handler)
        _install_secure_clob_handler(client, handler)
        try:
            return await client.authorize_session_key(
                address=_SESSION_ADDRESS,
                valid_until=datetime.now(UTC) + timedelta(minutes=15),
            )
        finally:
            await client.close()

    result = asyncio.run(run())

    assert result.session_key.address.lower() == _SESSION_ADDRESS.lower()
    assert sum(urlparse(str(request.url)).path == _SESSION_KEYS_PATH for request in captured) == 2


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


def test_authorize_session_key_allows_wallet_address_to_reach_service() -> None:
    captured: list[httpx.Request] = []
    requested_expiry = datetime.now(UTC) + timedelta(minutes=15)

    with make_sync_deposit_client() as client:
        wallet = str(client.wallet)
        handler = _authorization_handler(captured, wallet=wallet)
        install_sync_relayer_handler(client, handler)
        _install_sync_secure_clob_handler(client, handler)

        result = client.authorize_session_key(
            address=wallet,
            scopes=(SessionKeyKnownScope.CLOB,),
            valid_until=requested_expiry,
        )

    assert result.session_key.address.lower() == wallet.lower()
    authorization_request = next(
        request for request in captured if urlparse(str(request.url)).path == _AUTHORIZATIONS_PATH
    )
    body = cast(dict[str, object], request_json(authorization_request))
    session_signer_address = body["sessionSignerAddress"]
    assert isinstance(session_signer_address, str)
    assert session_signer_address.lower() == wallet.lower()


def test_authorize_session_key_rejects_invalid_cross_field_combinations() -> None:
    valid_expiry = datetime.now(UTC) + timedelta(minutes=15)
    client = make_sync_deposit_client()
    try:
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


def test_authorize_session_key_requires_builder_api_key() -> None:
    valid_expiry = datetime.now(UTC) + timedelta(minutes=15)

    with make_sync_deposit_client() as client:
        client._ctx = dataclasses.replace(client._ctx, api_key=None)
        with pytest.raises(
            UserInputError,
            match="Session-key authorization requires builder API-key authentication",
        ):
            client.authorize_session_key(
                address=_SESSION_ADDRESS,
                valid_until=valid_expiry,
            )


def test_authorize_session_key_rejects_relayer_api_key() -> None:
    valid_expiry = datetime.now(UTC) + timedelta(minutes=15)
    relayer_api_key = RelayerApiKey(
        key="relayer-key",
        address="0x0000000000000000000000000000000000000001",
    )

    with make_sync_deposit_client() as client:
        client._ctx = dataclasses.replace(client._ctx, api_key=relayer_api_key)
        with pytest.raises(
            UserInputError,
            match="Session-key authorization requires builder API-key authentication",
        ):
            client.authorize_session_key(
                address=_SESSION_ADDRESS,
                valid_until=valid_expiry,
            )


def test_revoke_session_key_requires_gasless_api_key() -> None:
    with make_sync_deposit_client() as client:
        client._ctx = dataclasses.replace(client._ctx, api_key=None)
        with pytest.raises(
            UserInputError,
            match="Session-key revocation requires API-key authentication",
        ):
            client.revoke_session_key(address=_SESSION_ADDRESS)


@pytest.mark.parametrize("status", ("FAILED", "SUPERSEDED", "REPAIR_REQUIRED"))
def test_authorize_session_key_rejects_terminal_status_before_polling(status: str) -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        handler = _authorization_handler(captured, wallet=str(client.wallet), status=status)
        install_sync_relayer_handler(client, handler)
        with pytest.raises(
            TransactionFailedError,
            match=rf"Session-key authorization reached terminal status {status}",
        ):
            client.authorize_session_key(
                address=_SESSION_ADDRESS,
                valid_until=datetime.now(UTC) + timedelta(minutes=15),
            )

    paths = [urlparse(str(request.url)).path for request in captured]
    assert f"/v1/account/transactions/{_TRANSACTION_ID}" not in paths


def test_revoke_session_key_rejects_terminal_status_before_polling() -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        handler = _management_handler(
            captured,
            wallet=str(client.wallet),
            revocation_status="FAILED",
        )
        install_sync_relayer_handler(client, handler)
        with pytest.raises(
            TransactionFailedError,
            match="Session-key revocation reached terminal status FAILED",
        ):
            client.revoke_session_key(address=_SESSION_ADDRESS)

    paths = [urlparse(str(request.url)).path for request in captured]
    assert f"/v1/account/transactions/{_REVOCATION_TRANSACTION_ID}" not in paths


def test_authorize_session_key_rejects_unknown_response_status() -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        handler = _authorization_handler(captured, wallet=str(client.wallet), status="PENDING")
        install_sync_relayer_handler(client, handler)
        with pytest.raises(UnexpectedResponseError, match="did not match expected shape"):
            client.authorize_session_key(
                address=_SESSION_ADDRESS,
                valid_until=datetime.now(UTC) + timedelta(minutes=15),
            )


def test_revoke_session_key_rejects_unknown_response_status() -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        handler = _management_handler(
            captured,
            wallet=str(client.wallet),
            revocation_status="SUBMITTED",
        )
        install_sync_relayer_handler(client, handler)
        with pytest.raises(UnexpectedResponseError, match="did not match expected shape"):
            client.revoke_session_key(address=_SESSION_ADDRESS)


def test_session_signer_wraps_gasless_wallet_action_signature() -> None:
    captured: list[httpx.Request] = []

    async def run() -> None:
        client = await make_session_client()
        assert client._ctx.signer_type == "SESSION_KEY"
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
            await client.approve_erc20(
                token_address=TOKEN,
                spender_address=SPENDER,
                amount=1,
            )
        finally:
            await client.close()

    asyncio.run(run())
    submit = next(request for request in captured if urlparse(str(request.url)).path == "/submit")
    body = cast(dict[str, object], request_json(submit))
    signature = body["signature"]
    assert isinstance(signature, str)
    assert signature.startswith("0x" + _SESSION_ADDRESS[2:].lower().rjust(64, "0"))
    assert signature.endswith(_SESSION_SIGNER_MAGIC_HEX)


def test_session_signer_wraps_gasless_wallet_action_signature_sync() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == _EXECUTE_PARAMS_PATH:
            return httpx.Response(
                200,
                json={"address": _SESSION_ADDRESS, "nonce": "11"},
                request=request,
            )
        if path == "/submit":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-gasless-sync",
                },
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    with make_sync_session_client() as client:
        assert client._ctx.signer_type == "SESSION_KEY"
        install_sync_relayer_handler(client, handler)
        client.approve_erc20(
            token_address=TOKEN,
            spender_address=SPENDER,
            amount=1,
        )

    submit = next(request for request in captured if urlparse(str(request.url)).path == "/submit")
    body = cast(dict[str, object], request_json(submit))
    signature = body["signature"]
    assert isinstance(signature, str)
    assert signature.startswith("0x" + _SESSION_ADDRESS[2:].lower().rjust(64, "0"))
    assert signature.endswith(_SESSION_SIGNER_MAGIC_HEX)
