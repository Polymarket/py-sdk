# pyright: reportPrivateUsage=false
import asyncio
import dataclasses
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from polymarket import ApiKeyCreds, AsyncSecureClient
from polymarket._internal.actions.orders.place import (
    is_balance_or_allowance_rejection,
    post_order_with_allowance_recovery,
)
from polymarket._internal.environment import (
    PRODUCTION_CONFIG,
    with_environment_config,
)
from polymarket._internal.wallet import derive_uups_deposit_wallet_address
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import RequestRejectedError

_PRIVATE_KEY = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_CREDS = ApiKeyCreds(key="k", passphrase="p", secret="dGVzdA==")
_STANDARD_EXCHANGE = PRODUCTION_CONFIG.standard_exchange
_CONDITION_ID = "0x5c19f205507ce03ff5f3be08a8090a5969ea6870cc07b902a4ca2e61dfe48fdd"
_ASSET_ID = str((1 << 40) + 8_501_497)


def _builder_auth() -> Any:
    from polymarket import BuilderApiKey

    return BuilderApiKey(key="bk", secret="dGVzdA==", passphrase="bp")


async def _make_deposit_client() -> AsyncSecureClient:
    from eth_account import Account

    signer = Account.from_key(_PRIVATE_KEY)
    wallet = derive_uups_deposit_wallet_address(signer.address, PRODUCTION_CONFIG.wallet_derivation)
    return await AsyncSecureClient._create(
        private_key=_PRIVATE_KEY,
        wallet=wallet,
        credentials=_CREDS,
        api_key=_builder_auth(),
        validate_credentials=False,
    )


def _install_secure_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
        header_resolver=client._ctx.secure_clob._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, secure_clob=transport)


def _install_clob(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://clob.test",
        client=httpx.AsyncClient(base_url="https://clob.test", transport=handler),
    )
    client._ctx = dataclasses.replace(client._ctx, clob=transport)


def _install_relayer(client: AsyncSecureClient, handler: httpx.MockTransport) -> None:
    transport = AsyncTransport(
        base_url="https://relayer.test",
        client=httpx.AsyncClient(base_url="https://relayer.test", transport=handler),
        header_resolver=client._ctx.relayer._header_resolver,
    )
    client._ctx = dataclasses.replace(client._ctx, relayer=transport)


def _accepted_order_payload() -> dict[str, Any]:
    return {
        "errorMsg": "",
        "makingAmount": "5",
        "orderID": "ord-1",
        "status": "live",
        "success": True,
        "takingAmount": "10",
        "tradeIDs": [],
        "transactionsHashes": [],
    }


_LIMIT_PUBLIC_ROUTES: dict[str, Any] = {
    f"/markets-by-token/{_ASSET_ID}": {"condition_id": _CONDITION_ID},
    f"/clob-markets/{_CONDITION_ID}": {
        "fd": {"r": 0, "e": 0},
        "mts": 0.01,
        "nr": False,
        "t": [{"t": _ASSET_ID, "o": "Yes"}],
    },
}


def _public_handler(captured: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path in _LIMIT_PUBLIC_ROUTES:
            return httpx.Response(200, json=_LIMIT_PUBLIC_ROUTES[path], request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return httpx.MockTransport(handler)


async def _make_signed_buy_order(client: AsyncSecureClient) -> Any:
    return await client.create_limit_order(asset_id=_ASSET_ID, price="0.5", size="10", side="BUY")


def test_is_balance_or_allowance_rejection_matches_ts_signal() -> None:
    err = RequestRejectedError("not enough balance / allowance is not enough", status=400)
    assert is_balance_or_allowance_rejection(err) is True


def test_is_balance_or_allowance_rejection_rejects_other_400() -> None:
    err = RequestRejectedError("invalid order", status=400)
    assert is_balance_or_allowance_rejection(err) is False


def test_is_balance_or_allowance_rejection_rejects_non_400() -> None:
    err = RequestRejectedError("allowance is not enough", status=500)
    assert is_balance_or_allowance_rejection(err) is False


def test_is_balance_or_allowance_rejection_rejects_other_exceptions() -> None:
    assert is_balance_or_allowance_rejection(ValueError("nope")) is False


def test_place_limit_order_first_post_success_no_recovery_calls() -> None:
    public_captured: list[httpx.Request] = []
    secure_captured: list[httpx.Request] = []

    def secure_handler(request: httpx.Request) -> httpx.Response:
        secure_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/order":
            return httpx.Response(200, json=_accepted_order_payload(), request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    async def run() -> None:
        client = await _make_deposit_client()
        try:
            _install_clob(client, _public_handler(public_captured))
            _install_secure_clob(client, httpx.MockTransport(secure_handler))
            await client.place_limit_order(asset_id=_ASSET_ID, price="0.5", size="10", side="BUY")
        finally:
            await client.close()

    asyncio.run(run())
    secure_paths = [urlparse(str(r.url)).path for r in secure_captured]
    assert secure_paths == ["/order"]


def test_place_limit_order_skips_approve_when_allowance_already_sufficient() -> None:
    public_captured: list[httpx.Request] = []
    secure_captured: list[httpx.Request] = []

    def secure_handler(request: httpx.Request) -> httpx.Response:
        secure_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/order":
            return httpx.Response(400, json={"error": "allowance is not enough"}, request=request)
        if path == "/balance-allowance":
            return httpx.Response(
                200,
                json={"balance": "0", "allowances": {_STANDARD_EXCHANGE: "99999999999"}},
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    async def run() -> None:
        client = await _make_deposit_client()
        try:
            _install_clob(client, _public_handler(public_captured))
            _install_secure_clob(client, httpx.MockTransport(secure_handler))
            with pytest.raises(RequestRejectedError, match="allowance is not enough"):
                await client.place_limit_order(
                    asset_id=_ASSET_ID, price="0.5", size="10", side="BUY"
                )
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(r.url)).path for r in secure_captured]
    assert paths.count("/order") == 1  # no retry
    assert "/balance-allowance" in paths
    assert "/balance-allowance/update" not in paths  # no approve, no refresh


def test_place_limit_order_does_not_recover_on_non_allowance_400() -> None:
    secure_captured: list[httpx.Request] = []

    def secure_handler(request: httpx.Request) -> httpx.Response:
        secure_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/order":
            return httpx.Response(400, json={"error": "invalid signature"}, request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    async def run() -> None:
        client = await _make_deposit_client()
        try:
            _install_clob(client, _public_handler([]))
            _install_secure_clob(client, httpx.MockTransport(secure_handler))
            with pytest.raises(RequestRejectedError, match="invalid signature"):
                await client.place_limit_order(
                    asset_id=_ASSET_ID, price="0.5", size="10", side="BUY"
                )
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(r.url)).path for r in secure_captured]
    assert paths == ["/order"]


def test_place_limit_order_recovers_buy_with_approve_max_then_retries() -> None:
    public_captured: list[httpx.Request] = []
    secure_captured: list[httpx.Request] = []
    relayer_captured: list[httpx.Request] = []
    order_post_count = {"n": 0}

    def secure_handler(request: httpx.Request) -> httpx.Response:
        secure_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/order":
            order_post_count["n"] += 1
            if order_post_count["n"] == 1:
                return httpx.Response(
                    400, json={"error": "allowance is not enough"}, request=request
                )
            return httpx.Response(200, json=_accepted_order_payload(), request=request)
        if path == "/balance-allowance":
            return httpx.Response(
                200,
                json={"balance": "0", "allowances": {_STANDARD_EXCHANGE: "0"}},
                request=request,
            )
        if path == "/balance-allowance/update":
            return httpx.Response(
                200,
                json={"balance": "100000000", "allowances": {_STANDARD_EXCHANGE: "99999999999"}},
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    def relayer_handler(request: httpx.Request) -> httpx.Response:
        relayer_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "0"}, request=request)
        if path == "/submit":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transactionHash": "0x" + "ab" * 32,
                    "transactionID": "tx-approve",
                },
                request=request,
            )
        if path.startswith("/v1/account/transactions/"):
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": "0x" + "ab" * 32,
                    "transaction_id": "tx-approve",
                },
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    async def run() -> Any:
        client = await _make_deposit_client()
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config, relayer_poll_frequency_ms=1
                ),
            ),
        )
        try:
            _install_clob(client, _public_handler(public_captured))
            _install_secure_clob(client, httpx.MockTransport(secure_handler))
            _install_relayer(client, httpx.MockTransport(relayer_handler))
            return await client.place_limit_order(
                asset_id=_ASSET_ID, price="0.5", size="10", side="BUY"
            )
        finally:
            await client.close()

    response = asyncio.run(run())
    assert response.order_id == "ord-1"

    secure_paths = [urlparse(str(r.url)).path for r in secure_captured]
    assert secure_paths.count("/order") == 2  # exactly one retry
    # Refresh after approve = two-call (update + balance-allowance), matching TS.
    assert secure_paths.count("/balance-allowance/update") == 1
    # /balance-allowance called twice: once pre-approve, once post-refresh.
    assert secure_paths.count("/balance-allowance") == 2

    relayer_paths = [urlparse(str(r.url)).path for r in relayer_captured]
    assert "/submit" in relayer_paths  # approve was submitted

    # ERC20 approve on collateral_token to standard_exchange
    approve_submit = next(r for r in relayer_captured if urlparse(str(r.url)).path == "/submit")
    import json as _json

    body = _json.loads(approve_submit.content.decode("utf-8"))
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.collateral_token.lower()


def test_place_limit_order_recovers_sell_with_erc1155_approve_for_all_then_retries() -> None:
    import json as _json

    public_captured: list[httpx.Request] = []
    secure_captured: list[httpx.Request] = []
    relayer_captured: list[httpx.Request] = []
    order_post_count = {"n": 0}

    def secure_handler(request: httpx.Request) -> httpx.Response:
        secure_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/order":
            order_post_count["n"] += 1
            if order_post_count["n"] == 1:
                return httpx.Response(
                    400, json={"error": "allowance is not enough"}, request=request
                )
            return httpx.Response(200, json=_accepted_order_payload(), request=request)
        if path == "/balance-allowance":
            return httpx.Response(
                200,
                json={"balance": "0", "allowances": {_STANDARD_EXCHANGE: "0"}},
                request=request,
            )
        if path == "/balance-allowance/update":
            return httpx.Response(200, json={}, request=request)
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    def relayer_handler(request: httpx.Request) -> httpx.Response:
        relayer_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "0"}, request=request)
        if path == "/submit":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transactionHash": "0x" + "cd" * 32,
                    "transactionID": "tx-erc1155",
                },
                request=request,
            )
        if path.startswith("/v1/account/transactions/"):
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": "0x" + "cd" * 32,
                    "transaction_id": "tx-erc1155",
                },
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    async def run() -> Any:
        client = await _make_deposit_client()
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config, relayer_poll_frequency_ms=1
                ),
            ),
        )
        try:
            _install_clob(client, _public_handler(public_captured))
            _install_secure_clob(client, httpx.MockTransport(secure_handler))
            _install_relayer(client, httpx.MockTransport(relayer_handler))
            return await client.place_limit_order(
                asset_id=_ASSET_ID, price="0.5", size="10", side="SELL"
            )
        finally:
            await client.close()

    response = asyncio.run(run())
    assert response.order_id == "ord-1"

    secure_paths = [urlparse(str(r.url)).path for r in secure_captured]
    assert secure_paths.count("/order") == 2

    # The pre-approve allowance fetch must query the CONDITIONAL asset path with the token_id.
    pre_approve_check = next(
        r for r in secure_captured if urlparse(str(r.url)).path == "/balance-allowance"
    )
    from urllib.parse import parse_qs

    qs = parse_qs(urlparse(str(pre_approve_check.url)).query)
    assert qs["asset_type"] == ["CONDITIONAL"]
    assert qs["token_id"] == [_ASSET_ID]

    # Approve was sent: setApprovalForAll on the conditional_tokens contract.
    approve_submit = next(r for r in relayer_captured if urlparse(str(r.url)).path == "/submit")
    body = _json.loads(approve_submit.content.decode("utf-8"))
    inner = body["depositWalletParams"]["calls"][0]
    set_approval_selector = "0xa22cb465"  # setApprovalForAll(address,bool)
    assert inner["target"].lower() == PRODUCTION_CONFIG.conditional_tokens.lower()
    assert inner["data"].startswith(set_approval_selector)


def test_place_limit_order_retry_failure_surfaces_directly() -> None:
    public_captured: list[httpx.Request] = []
    secure_captured: list[httpx.Request] = []
    order_post_count = {"n": 0}

    def secure_handler(request: httpx.Request) -> httpx.Response:
        secure_captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/order":
            order_post_count["n"] += 1
            if order_post_count["n"] == 1:
                return httpx.Response(
                    400, json={"error": "allowance is not enough"}, request=request
                )
            return httpx.Response(400, json={"error": "second-attempt rejection"}, request=request)
        if path == "/balance-allowance":
            return httpx.Response(
                200,
                json={"balance": "0", "allowances": {_STANDARD_EXCHANGE: "0"}},
                request=request,
            )
        if path == "/balance-allowance/update":
            return httpx.Response(
                200,
                json={"balance": "100000000", "allowances": {_STANDARD_EXCHANGE: "99999999999"}},
                request=request,
            )
        return httpx.Response(404, request=request)

    def relayer_handler(request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "0"}, request=request)
        if path == "/submit":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transactionHash": "0x" + "ab" * 32,
                    "transactionID": "tx-a",
                },
                request=request,
            )
        if path.startswith("/v1/account/transactions/"):
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": "0x" + "ab" * 32,
                    "transaction_id": "tx-a",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    async def run() -> None:
        client = await _make_deposit_client()
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config, relayer_poll_frequency_ms=1
                ),
            ),
        )
        try:
            _install_clob(client, _public_handler(public_captured))
            _install_secure_clob(client, httpx.MockTransport(secure_handler))
            _install_relayer(client, httpx.MockTransport(relayer_handler))
            with pytest.raises(RequestRejectedError, match="second-attempt rejection"):
                await client.place_limit_order(
                    asset_id=_ASSET_ID, price="0.5", size="10", side="BUY"
                )
        finally:
            await client.close()

    asyncio.run(run())
    # exactly two /order attempts; no third
    posts = [r for r in secure_captured if urlparse(str(r.url)).path == "/order"]
    assert len(posts) == 2


def test_post_order_with_allowance_recovery_helper_is_idempotent_on_success() -> None:
    secure_captured: list[httpx.Request] = []

    def secure_handler(request: httpx.Request) -> httpx.Response:
        secure_captured.append(request)
        return httpx.Response(200, json=_accepted_order_payload(), request=request)

    async def run() -> None:
        client = await _make_deposit_client()
        try:
            _install_clob(client, _public_handler([]))
            _install_secure_clob(client, httpx.MockTransport(secure_handler))
            signed = await _make_signed_buy_order(client)
            await post_order_with_allowance_recovery(client, signed)
        finally:
            await client.close()

    asyncio.run(run())
    paths = [urlparse(str(r.url)).path for r in secure_captured]
    assert paths == ["/order"]
