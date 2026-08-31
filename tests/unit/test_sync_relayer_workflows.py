# pyright: reportPrivateUsage=false
import dataclasses
import json
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
import pytest
from _relayer_helpers import (
    SPENDER,
    TOKEN,
    install_sync_relayer_handler,
    install_sync_rpc_handler,
    make_sync_deposit_client,
    make_sync_eoa_client,
    make_sync_proxy_client,
    make_sync_safe_client,
    request_json,
    trading_approval_rpc_handler,
)
from eth_abi.abi import decode as abi_decode
from eth_abi.abi import encode as abi_encode

from polymarket import SecureClient
from polymarket._internal.environment import (
    PRODUCTION_CONFIG,
    with_environment_config,
)
from polymarket.calls import merge_v2_call
from polymarket.errors import (
    TimeoutError as PolyTimeoutError,
)
from polymarket.errors import (
    TransactionFailedError,
    UnexpectedResponseError,
    UserInputError,
)
from polymarket.transactions import SyncEoaTransactionHandle, SyncGaslessTransactionHandle
from polymarket.types import EvmAddress

_CONDITION_ID = "0x" + "11" * 32


def _deposit_relayer_handler(captured: list[httpx.Request]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "0"}, request=request)
        if path == "/submit":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-sync",
                },
                request=request,
            )
        return httpx.Response(404, json={"error": "not mocked"}, request=request)

    return handler


def test_approve_erc20_gasless_returns_sync_handle() -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        install_sync_relayer_handler(client, _deposit_relayer_handler(captured))
        handle = client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)

    assert isinstance(handle, SyncGaslessTransactionHandle)
    assert handle.transaction_id == "tx-sync"
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert len(submit_calls) == 1
    body = request_json(submit_calls[0])
    assert body["type"] == "WALLET"


def test_approve_erc20_eoa_uses_direct_broadcast() -> None:
    rpc_calls: list[dict[str, object]] = []

    def rpc_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        rpc_calls.append(body)
        method = body["method"]
        if method == "eth_chainId":
            result: object = hex(137)
        elif method == "eth_getTransactionCount":
            result = hex(7)
        elif method == "eth_gasPrice":
            result = hex(30_000_000_000)
        elif method == "eth_estimateGas":
            result = hex(100_000)
        elif method == "eth_sendRawTransaction":
            result = "0x" + "aa" * 32
        else:
            return httpx.Response(
                404, json={"jsonrpc": "2.0", "id": body["id"], "error": "?"}, request=request
            )
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}, request=request
        )

    with make_sync_eoa_client() as client:
        install_sync_rpc_handler(client, rpc_handler)
        handle = client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)

    assert isinstance(handle, SyncEoaTransactionHandle)
    assert handle.transaction_hash == "0x" + "aa" * 32
    methods = [c["method"] for c in rpc_calls]
    assert "eth_sendRawTransaction" in methods


def test_split_position_routes_through_collateral_adapter() -> None:
    captured: list[httpx.Request] = []
    _CONDITION_ID = "0x" + "11" * 32

    class _StubPaginator:
        def __init__(self, items: tuple[object, ...]) -> None:
            self._items = items

        def first_page(self):  # type: ignore[no-untyped-def]
            from polymarket.pagination import Page

            return Page(items=self._items, has_more=False, next_cursor=None, total_count=1)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "0"}, request=request)
        if path == "/submit":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-split",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    def list_markets_stub(**_: object):  # type: ignore[no-untyped-def]
        return _StubPaginator((_stub_market(_CONDITION_ID, neg_risk=False),))

    with make_sync_deposit_client() as client:
        client.list_markets = list_markets_stub  # type: ignore[method-assign]
        install_sync_relayer_handler(client, handler)
        client.split_position(condition_id=_CONDITION_ID, amount=1_000_000)

    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.collateral_adapter.lower()


def test_setup_trading_approvals_bundles_required_calls_for_deposit_wallet() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "0"}, request=request)
        if path == "/submit":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-setup",
                },
                request=request,
            )
        if path == "/v1/account/transactions/tx-setup":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": "0x" + "ab" * 32,
                    "transaction_id": "tx-setup",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    with make_sync_deposit_client() as client:
        install_sync_relayer_handler(client, handler)
        install_sync_rpc_handler(client, trading_approval_rpc_handler())
        client.setup_trading_approvals()

    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    body = request_json(submit_calls[0])
    inner_calls = body["depositWalletParams"]["calls"]
    assert len(inner_calls) == 17


def test_setup_trading_approvals_skips_submit_when_already_approved() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(404, request=request)

    with make_sync_deposit_client() as client:
        install_sync_relayer_handler(client, handler)
        install_sync_rpc_handler(
            client,
            trading_approval_rpc_handler(allowance=(1 << 256) - 1, approved=True),
        )
        handle = client.setup_trading_approvals()
        handle.wait()

    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert submit_calls == []


def test_close_closes_relayer_and_rpc_transports() -> None:
    client = make_sync_proxy_client()
    client.close()


def _proxy_relayer_handler(captured: list[httpx.Request]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/relay-payload":
            return httpx.Response(
                200,
                json={"address": "0xe679d14b2fe0bdee4a54f25bcec2978e372de566", "nonce": "0"},
                request=request,
            )
        if path == "/submit":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-proxy",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    return handler


def _safe_relayer_handler(captured: list[httpx.Request]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "0"}, request=request)
        if path == "/submit":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-safe",
                },
                request=request,
            )
        if path == "/v1/account/transactions/tx-safe":
            return httpx.Response(
                200,
                json={
                    "state": "STATE_CONFIRMED",
                    "transaction_hash": "0x" + "cd" * 32,
                    "transaction_id": "tx-safe",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    return handler


def test_approve_erc20_proxy_uses_default_gas_limit_when_rpc_estimate_fails() -> None:
    captured: list[httpx.Request] = []

    def rpc_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32_603, "message": "upstream unavailable"},
            },
            request=request,
        )

    with make_sync_proxy_client() as client:
        install_sync_relayer_handler(client, _proxy_relayer_handler(captured))
        install_sync_rpc_handler(client, rpc_handler)
        client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)

    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    assert body["type"] == "PROXY"
    assert body["signatureParams"]["gasLimit"] == "200000"
    assert body["signatureParams"]["relay"].lower() == "0xe679d14b2fe0bdee4a54f25bcec2978e372de566"


def test_approve_erc20_safe_single_call_uses_call_operation() -> None:
    captured: list[httpx.Request] = []

    with make_sync_safe_client() as client:
        install_sync_relayer_handler(client, _safe_relayer_handler(captured))
        client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)

    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    assert body["type"] == "SAFE"
    assert body["signatureParams"]["operation"] == "0"
    assert body["to"].lower() == TOKEN.lower()


def test_setup_trading_approvals_safe_uses_multisend_delegatecall() -> None:
    captured: list[httpx.Request] = []

    with make_sync_safe_client() as client:
        install_sync_relayer_handler(client, _safe_relayer_handler(captured))
        install_sync_rpc_handler(client, trading_approval_rpc_handler())
        client.setup_trading_approvals()

    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    assert body["type"] == "SAFE"
    assert body["signatureParams"]["operation"] == "1"
    assert body["to"].lower() == PRODUCTION_CONFIG.safe_multisend.lower()


def test_execute_transaction_batches_custom_calls() -> None:
    captured: list[httpx.Request] = []
    router = EvmAddress(PRODUCTION_CONFIG.protocol_v2_router)

    with make_sync_deposit_client() as client:
        install_sync_relayer_handler(client, _deposit_relayer_handler(captured))
        handle = client.execute_transaction(
            calls=[
                merge_v2_call(router=router, condition_id="0x03" + "11" * 30, amount=1),
                merge_v2_call(router=router, condition_id="0x03" + "22" * 30, amount=2),
                merge_v2_call(router=router, condition_id="0x03" + "33" * 30, amount=3),
            ],
            metadata="Merge 3 combo positions",
        )

    assert isinstance(handle, SyncGaslessTransactionHandle)
    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    assert body["metadata"] == "Merge 3 combo positions"
    inner_calls = body["depositWalletParams"]["calls"]
    assert len(inner_calls) == 3
    assert {call["target"].lower() for call in inner_calls} == {router.lower()}


def test_execute_transaction_rejects_empty_calls() -> None:
    with (
        make_sync_deposit_client() as client,
        pytest.raises(UserInputError, match="At least one transaction call is required"),
    ):
        client.execute_transaction(calls=[])


def test_merge_multiple_positions_batches_combo_merges() -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        install_sync_relayer_handler(client, _deposit_relayer_handler(captured))
        install_sync_rpc_handler(client, _eth_call_result("uint256[]", [100, 60]))
        handle = client.merge_multiple_positions(
            positions=[
                {"position_id": _combo_position("0x03" + "11" * 30, 0), "amount": 1},
                {"position_id": _combo_position("0x03" + "22" * 30, 1), "amount": "max"},
                {"position_id": _combo_position("0x03" + "33" * 30, 0)},
            ],
            metadata="Merge selected combo positions",
        )

    assert isinstance(handle, SyncGaslessTransactionHandle)
    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    inner_calls = body["depositWalletParams"]["calls"]
    assert len(inner_calls) == 3
    assert body["metadata"] == "Merge selected combo positions"
    assert {call["target"].lower() for call in inner_calls} == {
        PRODUCTION_CONFIG.protocol_v2_router.lower()
    }
    assert [call["data"][-64:] for call in inner_calls] == [
        f"{1:064x}",
        f"{60:064x}",
        f"{60:064x}",
    ]


def test_merge_multiple_positions_batches_market_merges() -> None:
    captured: list[httpx.Request] = []
    first_condition_id = "0x" + "11" * 32
    second_condition_id = "0x" + "22" * 32
    market_calls: list[dict[str, object]] = []

    def list_markets_stub(**kwargs: object):  # type: ignore[no-untyped-def]
        market_calls.append(kwargs)
        condition_ids = kwargs.get("condition_ids")
        if condition_ids == [first_condition_id]:
            return _stub_page((_stub_market(first_condition_id, neg_risk=False),))
        if condition_ids == [second_condition_id]:
            return _stub_page((_stub_market(second_condition_id, neg_risk=False),))
        return _stub_page(())

    with make_sync_deposit_client() as client:
        client.list_markets = list_markets_stub  # type: ignore[method-assign]
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        install_sync_relayer_handler(client, _deposit_relayer_handler(captured))
        install_sync_rpc_handler(client, _eth_call_result("uint256[]", [100_000_000, 60_000_000]))
        handle = client.merge_multiple_positions(
            positions=[
                {"condition_id": first_condition_id, "amount": 1_000_000},
                {"condition_id": second_condition_id, "amount": "max"},
            ],
            metadata="Merge selected market positions",
        )

    assert isinstance(handle, SyncGaslessTransactionHandle)
    assert market_calls == [
        {"condition_ids": [first_condition_id], "page_size": 1},
        {"condition_ids": [second_condition_id], "page_size": 1},
    ]
    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    inner_calls = body["depositWalletParams"]["calls"]
    assert len(inner_calls) == 2
    assert body["metadata"] == "Merge selected market positions"
    assert {call["target"].lower() for call in inner_calls} == {
        PRODUCTION_CONFIG.collateral_adapter.lower()
    }
    assert [_decode_merge_positions_amount(call["data"]) for call in inner_calls] == [
        1_000_000,
        60_000_000,
    ]


def test_merge_multiple_positions_rejects_mixed_market_and_combo_positions() -> None:
    with (
        make_sync_deposit_client() as client,
        pytest.raises(UserInputError, match="Cannot mix market and combo"),
    ):
        client.merge_multiple_positions(
            positions=[
                {"condition_id": _CONDITION_ID},
                {"position_id": _combo_position("0x03" + "11" * 30, 0)},
            ]
        )


def test_merge_multiple_positions_rejects_empty_positions() -> None:
    with (
        make_sync_deposit_client() as client,
        pytest.raises(UserInputError, match="positions must include at least one"),
    ):
        client.merge_multiple_positions(positions=[])


def _stub_binary_positions(  # type: ignore[no-untyped-def]
    client: SecureClient,
    *,
    neg_risk: bool,
    yes_size: str,
    no_size: str,
    condition_id: str = _CONDITION_ID,
    calls: list[dict[str, object]] | None = None,
):
    from polymarket.models.data.portfolio import Position
    from polymarket.pagination import Page

    yes = Position.parse_response(
        {
            "conditionId": condition_id,
            "outcomeIndex": 0,
            "size": yes_size,
            "negativeRisk": neg_risk,
        }
    )
    no = Position.parse_response(
        {
            "conditionId": condition_id,
            "outcomeIndex": 1,
            "size": no_size,
            "negativeRisk": neg_risk,
        }
    )

    class _StubPaginator:
        def first_page(self):  # type: ignore[no-untyped-def]
            return Page(items=(yes, no), has_more=False, next_cursor=None, total_count=2)

    def list_positions_stub(**kwargs: object):  # type: ignore[no-untyped-def]
        if calls is not None:
            calls.append(kwargs)
        return _StubPaginator()

    client.list_positions = list_positions_stub  # type: ignore[method-assign]


def _stub_market(
    condition_id: str | None,
    *,
    neg_risk: bool | None = True,
    yes_token_id: str | None = "101",
    no_token_id: str | None = "202",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="123",
        condition_id=condition_id,
        state=SimpleNamespace(neg_risk=neg_risk),
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id=yes_token_id),
            no=SimpleNamespace(token_id=no_token_id),
        ),
    )


def _stub_page(items: tuple[object, ...]):  # type: ignore[no-untyped-def]
    from polymarket.pagination import Page

    class _StubPaginator:
        def first_page(self):  # type: ignore[no-untyped-def]
            return Page(items=items, has_more=False, next_cursor=None, total_count=len(items))

    return _StubPaginator()


def _combo_position(condition_id: str, outcome: int) -> str:
    return str(int(f"{condition_id}{outcome:02x}", 16))


def test_merge_positions_routes_through_collateral_adapter() -> None:
    captured: list[httpx.Request] = []

    with make_sync_deposit_client() as client:
        client.list_markets = lambda **_: _stub_page((_stub_market(_CONDITION_ID, neg_risk=False),))  # type: ignore[method-assign]
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        install_sync_relayer_handler(client, _deposit_relayer_handler(captured))
        install_sync_rpc_handler(client, _eth_call_result("uint256[]", [100_000_000, 60_000_000]))
        client.merge_positions(condition_id="0x" + "11" * 32, amount="max")

    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.collateral_adapter.lower()


def test_redeem_positions_routes_through_neg_risk_collateral_adapter() -> None:
    captured: list[httpx.Request] = []
    market_calls: list[dict[str, object]] = []
    condition_id = "0x" + "11" * 32

    def list_markets_stub(**kwargs: object):  # type: ignore[no-untyped-def]
        market_calls.append(kwargs)
        return _stub_page((_stub_market(_CONDITION_ID, neg_risk=True),))

    with make_sync_deposit_client() as client:
        client.list_markets = list_markets_stub  # type: ignore[method-assign]
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        install_sync_relayer_handler(client, _deposit_relayer_handler(captured))
        client.redeem_positions(condition_id=condition_id)

    assert market_calls == [{"condition_ids": [condition_id], "closed": True, "page_size": 1}]
    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.neg_risk_collateral_adapter.lower()


def test_redeem_positions_market_id_resolves_condition_before_fetching_positions() -> None:
    captured: list[httpx.Request] = []
    market_calls: list[dict[str, object]] = []

    def list_markets_stub(**kwargs: object):  # type: ignore[no-untyped-def]
        market_calls.append(kwargs)
        return _stub_page((_stub_market(_CONDITION_ID, neg_risk=True),))

    with make_sync_deposit_client() as client:
        client.list_markets = list_markets_stub  # type: ignore[method-assign]
        client.list_positions = _fail_list_positions  # type: ignore[method-assign]
        install_sync_relayer_handler(client, _deposit_relayer_handler(captured))
        client.redeem_positions(market_id="123")

    assert market_calls == [{"ids": [123], "closed": True, "page_size": 1}]
    submit = [r for r in captured if urlparse(str(r.url)).path == "/submit"][0]
    body = request_json(submit)
    inner = body["depositWalletParams"]["calls"][0]
    assert inner["target"].lower() == PRODUCTION_CONFIG.neg_risk_collateral_adapter.lower()


def test_redeem_positions_market_id_rejects_non_integer() -> None:
    with (
        make_sync_deposit_client() as client,
        pytest.raises(UserInputError, match="Market ID must be an integer"),
    ):
        client.redeem_positions(market_id="not-an-int")


def test_redeem_positions_market_id_raises_when_condition_missing() -> None:
    def list_markets_stub(**_: object):  # type: ignore[no-untyped-def]
        return _stub_page((_stub_market(None),))

    with make_sync_deposit_client() as client:
        client.list_markets = list_markets_stub  # type: ignore[method-assign]
        with pytest.raises(UnexpectedResponseError, match="Missing condition ID for market 123"):
            client.redeem_positions(market_id="123")


def test_split_position_raises_unexpected_response_when_neg_risk_flag_missing() -> None:
    class _StubPaginator:
        def first_page(self):  # type: ignore[no-untyped-def]
            from polymarket.pagination import Page

            return Page(
                items=(_stub_market(_CONDITION_ID, neg_risk=None),),
                has_more=False,
                next_cursor=None,
                total_count=1,
            )

    with (
        pytest.raises(UnexpectedResponseError, match="Missing negative-risk"),
        make_sync_deposit_client() as client,
    ):
        client.list_markets = lambda **_: _StubPaginator()  # type: ignore[method-assign]
        client.split_position(condition_id="0x" + "11" * 32, amount=1)


def _fail_list_positions(**_: object) -> None:
    raise AssertionError("list_positions should not be called")


def _eth_call_result(abi_type: str, value: object):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": "0x" + abi_encode([abi_type], [value]).hex(),
            },
            request=request,
        )

    return handler


def _decode_merge_positions_amount(data: str) -> int:
    decoded = abi_decode(
        ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
        bytes.fromhex(data[10:]),
    )
    amount = decoded[4]
    assert isinstance(amount, int)
    return amount


def _wait_relayer_handler(state: str, *, error_msg: str | None = None):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "0"}, request=request)
        if path == "/submit":
            return httpx.Response(
                200,
                json={"state": "STATE_NEW", "transactionHash": None, "transactionID": "tx-w"},
                request=request,
            )
        if path.startswith("/v1/account/transactions/"):
            body: dict[str, object] = {
                "state": state,
                "transaction_hash": "0x" + "aa" * 32,
                "transaction_id": "tx-w",
            }
            if error_msg is not None:
                body["error_msg"] = error_msg
            return httpx.Response(200, json=body, request=request)
        return httpx.Response(404, request=request)

    return handler


def test_gasless_wait_returns_outcome_on_terminal_success() -> None:
    with make_sync_deposit_client() as client:
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config, relayer_poll_frequency_ms=1
                ),
            ),
        )
        install_sync_relayer_handler(client, _wait_relayer_handler("STATE_CONFIRMED"))
        handle = client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        outcome = handle.wait()

    assert outcome.transaction_id == "tx-w"
    assert outcome.transaction_hash == "0x" + "aa" * 32


def test_gasless_wait_raises_transaction_failed_on_terminal_failure() -> None:
    with make_sync_deposit_client() as client:
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config, relayer_poll_frequency_ms=1
                ),
            ),
        )
        install_sync_relayer_handler(
            client, _wait_relayer_handler("STATE_FAILED", error_msg="reverted on chain")
        )
        handle = client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        with pytest.raises(TransactionFailedError, match="reverted on chain"):
            handle.wait()


def test_gasless_wait_times_out_when_terminal_state_never_reached() -> None:
    with make_sync_deposit_client() as client:
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config,
                    relayer_poll_frequency_ms=1,
                    relayer_max_polls=3,
                ),
            ),
        )
        install_sync_relayer_handler(client, _wait_relayer_handler("STATE_NEW"))
        handle = client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)
        with pytest.raises(PolyTimeoutError):
            handle.wait()


def test_gasless_submit_retries_on_retryable_400_then_succeeds() -> None:
    captured: list[httpx.Request] = []
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "0"}, request=request)
        if path == "/submit":
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(
                    400,
                    json={"error": "wallet busy with active action"},
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-retry",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    with make_sync_deposit_client() as client:
        client._ctx = dataclasses.replace(
            client._ctx,
            environment=with_environment_config(
                client._ctx.environment,
                config=dataclasses.replace(
                    client._ctx.environment_config, relayer_poll_frequency_ms=1
                ),
            ),
        )
        install_sync_relayer_handler(client, handler)
        handle = client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)

    assert handle.transaction_id == "tx-retry"
    submit_calls = [r for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert len(submit_calls) == 2


def test_gasless_submit_self_heals_with_nonce_from_submit_error() -> None:
    captured: list[httpx.Request] = []
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = urlparse(str(request.url)).path
        if path == "/v1/account/transactions/params":
            return httpx.Response(200, json={"address": "0xRELAY", "nonce": "9"}, request=request)
        if path == "/submit":
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(
                    400,
                    json={"error": "batch nonce 9 does not match on-chain nonce 2"},
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "state": "STATE_NEW",
                    "transactionHash": None,
                    "transactionID": "tx-healed",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    with make_sync_deposit_client() as client:
        install_sync_relayer_handler(client, handler)
        handle = client.approve_erc20(token_address=TOKEN, spender_address=SPENDER, amount=1)

    assert handle.transaction_id == "tx-healed"
    submit_bodies = [request_json(r) for r in captured if urlparse(str(r.url)).path == "/submit"]
    assert len(submit_bodies) == 2
    assert submit_bodies[1]["nonce"] == "2"
