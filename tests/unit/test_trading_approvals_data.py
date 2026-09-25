import asyncio
from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest
import respx
from _relayer_helpers import make_deposit_client, make_sync_deposit_client

from polymarket import AsyncPublicClient, PublicClient, TradingApprovalsState
from polymarket._internal.environment import PRODUCTION_CONFIG, with_environment_config
from polymarket.environments import PRODUCTION
from polymarket.errors import RateLimitError, RequestRejectedError, UnexpectedResponseError

WALLET = "0x00000000000000000000000000000000000000AA"
MAX = (1 << 256) - 1
CONFIG = PRODUCTION_CONFIG
ERC20_SPENDERS = (
    CONFIG.standard_exchange,
    CONFIG.neg_risk_exchange,
    CONFIG.collateral_adapter,
    CONFIG.neg_risk_collateral_adapter,
    CONFIG.protocol_v2_router,
    CONFIG.exchange_v3,
    CONFIG.perps_deposit_contract,
)
ERC1155_PAIRS = (
    *((CONFIG.conditional_tokens, spender) for spender in ERC20_SPENDERS[:4]),
    (CONFIG.conditional_tokens, CONFIG.auto_redeem_operator),
    (CONFIG.conditional_tokens, CONFIG.binary_module),
    (CONFIG.conditional_tokens, CONFIG.neg_risk_module),
    (CONFIG.position_manager, CONFIG.protocol_v2_router),
    (CONFIG.position_manager, CONFIG.exchange_v3),
    (CONFIG.position_manager, CONFIG.auto_redeem_operator),
)


def _rows(*, approved: bool = True) -> list[dict[str, object]]:
    return [
        *(
            {
                "token": CONFIG.collateral_token.lower(),
                "spender": spender.lower(),
                "standard": "ERC20",
                "approved": approved,
                "amount": "max",
            }
            for spender in ERC20_SPENDERS
        ),
        *(
            {
                "token": token.lower(),
                "spender": spender.lower(),
                "standard": "ERC1155",
                "approved": approved,
            }
            for token, spender in ERC1155_PAIRS
        ),
    ]


def _payload(rows: list[dict[str, object]]) -> dict[str, object]:
    return {"data": {"address": WALLET.lower(), "chain_id": 137, "contracts": rows}}


def _read(payload: object) -> TradingApprovalsState:
    with respx.mock as router, PublicClient() as client:
        route = router.get(f"{CONFIG.data_url}/v2/approvals", params={"user": WALLET}).respond(
            200, json=payload
        )
        state = client.get_trading_approvals_state(wallet=WALLET)
        assert route.call_count == 1
        return state


def test_missing_state_preserves_required_pairs_order_and_amounts() -> None:
    state = _read(_payload(list(reversed(_rows(approved=False)))))
    assert state.is_fully_approved is False
    assert [(row.token_address, row.spender, row.amount) for row in state.missing.erc20] == [
        (CONFIG.collateral_token, spender, MAX) for spender in ERC20_SPENDERS
    ]
    assert [(row.token_address, row.operator) for row in state.missing.erc1155] == list(
        ERC1155_PAIRS
    )


@pytest.mark.parametrize("mode", ["sync_public", "async_public", "sync_secure", "async_secure"])
@pytest.mark.parametrize("override", [False, True])
def test_clients_read_data_without_rpc(mode: str, override: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        user = request.url.params["user"]
        if override or "public" in mode:
            assert user == WALLET
        else:
            assert user.lower() != WALLET.lower()
        return httpx.Response(
            200,
            json={"data": {"address": user.lower(), "chain_id": 137, "contracts": _rows()}},
        )

    async def async_run() -> TradingApprovalsState:
        if mode == "async_secure":
            async with await make_deposit_client() as client:
                return await client.get_trading_approvals_state(wallet=WALLET if override else None)
        async with AsyncPublicClient() as public:
            return await public.get_trading_approvals_state(wallet=WALLET)

    with respx.mock as router:
        route = router.get(f"{CONFIG.data_url}/v2/approvals").mock(side_effect=handler)
        if mode.startswith("async"):
            state = asyncio.run(async_run())
        elif mode == "sync_secure":
            with make_sync_deposit_client() as client:
                state = client.get_trading_approvals_state(wallet=WALLET if override else None)
        else:
            with PublicClient() as public:
                state = public.get_trading_approvals_state(wallet=WALLET)
        assert route.call_count == 1
    assert state.is_fully_approved is True
    assert state.missing.erc20 == ()
    assert state.missing.erc1155 == ()


def test_mixed_amounts_require_both_approved_and_full_allowance() -> None:
    rows = _rows()
    rows[0]["approved"] = False  # Persistent rows say "max" even when unapproved.
    rows[1]["amount"] = str(MAX)
    rows[6]["amount"] = "1"  # Perps calls a finite allowance approved.
    rows[7]["approved"] = False
    state = _read(_payload(rows))
    assert [row.spender for row in state.missing.erc20] == [
        CONFIG.standard_exchange,
        CONFIG.perps_deposit_contract,
    ]
    assert state.missing.erc1155[0].operator == CONFIG.standard_exchange
    assert len(state.missing.erc1155) == 1


@pytest.mark.parametrize(
    "amount", [None, 1, True, "", "01", "-1", "1.5", "1e3", "0x01", "١", str(1 << 256)]
)
def test_malformed_amounts_do_not_become_missing_or_approved(amount: object) -> None:
    rows = _rows()
    rows[0]["amount"] = amount
    with pytest.raises(UnexpectedResponseError):
        _read(_payload(rows))


_CATALOG_MUTATIONS: list[Callable[[list[dict[str, object]]], object]] = [
    lambda rows: rows.pop(),
    lambda rows: rows.append(dict(rows[0])),
    lambda rows: rows[0].update(standard="ERC1155"),
    lambda rows: rows[7].update(standard="ERC20", amount="max"),
    lambda rows: rows[0].pop("amount"),
    lambda rows: rows[0].update(approved=1),
    lambda rows: rows[0].update(approved="false"),
    lambda rows: rows[0].update(token="not-an-address"),
    lambda rows: rows[0].update(spender=None),
]


@pytest.mark.parametrize("mutate", _CATALOG_MUTATIONS)
def test_incomplete_or_ambiguous_required_catalog_fails(
    mutate: Callable[[list[dict[str, object]]], object],
) -> None:
    rows = _rows()
    mutate(rows)
    with pytest.raises(UnexpectedResponseError):
        _read(_payload(rows))


@pytest.mark.parametrize(
    "overrides",
    [
        {"address": "0x" + "12" * 20},
        {"chain_id": 1},
        {"chain_id": "137"},
        {"chain_id": True},
        {"contracts": None},
    ],
)
def test_wrong_owner_chain_or_catalog_fails(overrides: dict[str, object]) -> None:
    with pytest.raises(UnexpectedResponseError):
        _read({"data": {"address": WALLET, "chain_id": 137, "contracts": _rows(), **overrides}})


def test_unrelated_rows_and_renamed_labels_do_not_change_requirements() -> None:
    rows = _rows()
    for row in rows:
        row.update(id="renamed", feature="something_else")
    rows.extend(
        [
            {
                "token": "0x" + "12" * 20,
                "spender": WALLET,
                "standard": "ERC20",
                "amount": "0",
                "approved": False,
            },
            # Rows the SDK does not evaluate may use shapes it does not know.
            {"token": CONFIG.conditional_tokens, "spender": WALLET, "standard": "ERC721"},
            {"token": CONFIG.collateral_token, "spender": "0x" + "34" * 20, "amount": None},
            {"token": "not-an-address", "spender": None, "standard": "ERC20"},
        ]
    )
    assert _read(_payload(rows)).is_fully_approved is True


def test_read_uses_configured_endpoint_chain_and_required_targets() -> None:
    token = "0x" + "12" * 20
    environment = with_environment_config(
        PRODUCTION,
        config=replace(CONFIG, data_url="https://data.test", chain_id=123, collateral_token=token),
    )
    rows = _rows(approved=False)
    for row in rows[:7]:
        row["token"] = token
    with respx.mock as router, PublicClient(environment) as client:
        route = router.get("https://data.test/v2/approvals", params={"user": WALLET}).respond(
            200, json={"data": {"address": WALLET, "chain_id": 123, "contracts": rows}}
        )
        state = client.get_trading_approvals_state(wallet=WALLET)
        assert route.call_count == 1
    assert len(state.missing.erc20) == 7
    assert all(row.token_address == token for row in state.missing.erc20)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status,attempts", [(400, 1), (503, 1), (429, 3)])
def test_http_failure_is_preserved_without_rpc_fallback(
    mode: str, status: int, attempts: int
) -> None:
    async def async_run() -> None:
        async with AsyncPublicClient() as client:
            await client.get_trading_approvals_state(wallet=WALLET)

    with respx.mock as router, PublicClient() as client:
        route = router.get(f"{CONFIG.data_url}/v2/approvals").respond(
            status, headers={"Retry-After": "0"}, json={"error": "unavailable"}
        )
        with pytest.raises(RateLimitError if status == 429 else RequestRejectedError):
            if mode == "async":
                asyncio.run(async_run())
            else:
                client.get_trading_approvals_state(wallet=WALLET)
        assert route.call_count == attempts
