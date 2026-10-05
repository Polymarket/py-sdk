from __future__ import annotations

from typing import cast

from eth_utils.address import is_hex_address, to_checksum_address

from polymarket._internal.actions.relayer.calls import (
    MAX_UINT256,
    TransactionCall,
    decode_erc20_allowance_result,
    decode_erc1155_is_approved_for_all_result,
    erc20_allowance_call,
    erc20_approval_call,
    erc1155_is_approved_for_all_call,
    erc1155_set_approval_for_all_call,
)
from polymarket._internal.data_envelope import parse_data_envelope
from polymarket._internal.data_params import build_data_params
from polymarket._internal.environment import EnvironmentConfig
from polymarket._internal.eoa.rpc import JsonRpcClient, SyncJsonRpcClient
from polymarket._internal.request import RequestSpec
from polymarket._internal.retry import DATA_READ_RETRY
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.trading import (
    Erc20TradingApproval,
    Erc1155TradingApproval,
    MissingTradingApprovals,
    TradingApprovalsState,
)
from polymarket.types import EvmAddress


def build_get_trading_approvals_state_spec(
    *, wallet: str, config: EnvironmentConfig
) -> RequestSpec[TradingApprovalsState]:
    wallet_address = _normalize_wallet(wallet)
    return RequestSpec(
        service="data",
        method="GET",
        path="/v2/approvals",
        params=build_data_params({"user": wallet_address}),
        parse=lambda payload: parse_data_envelope(
            payload,
            lambda data: _parse_indexed_trading_approvals(
                data, wallet=wallet_address, config=config
            ),
        ),
        retry=DATA_READ_RETRY,
    )


def _parse_indexed_trading_approvals(
    payload: object, *, wallet: EvmAddress, config: EnvironmentConfig
) -> TradingApprovalsState:
    if not isinstance(payload, dict):
        raise UnexpectedResponseError("Trading approvals must be an object")
    data = cast(dict[str, object], payload)
    owner = data.get("address")
    if not isinstance(owner, str) or owner.lower() != wallet.lower():
        raise UnexpectedResponseError("Trading approvals owner does not match the requested wallet")
    chain_id = data.get("chain_id")
    if type(chain_id) is not int or chain_id != config.chain_id:
        raise UnexpectedResponseError("Trading approvals chain does not match the environment")
    contracts = data.get("contracts")
    if not isinstance(contracts, list):
        raise UnexpectedResponseError("Trading approvals are missing the contract catalog")

    erc20, erc1155 = _required_trading_approvals(config)
    required_pairs = {
        *((a.token_address.lower(), a.spender.lower()) for a in erc20),
        *((a.token_address.lower(), a.operator.lower()) for a in erc1155),
    }

    # Only the rows for required pairs are validated. The catalog grows
    # independently of SDK releases, so unrelated rows must never fail a read.
    indexed: dict[tuple[str, str], tuple[str, bool, int | None]] = {}
    for raw in cast(list[object], contracts):
        if not isinstance(raw, dict):
            raise UnexpectedResponseError("Trading approval must be an object")
        row = cast(dict[str, object], raw)
        token, spender = row.get("token"), row.get("spender")
        if not isinstance(token, str) or not isinstance(spender, str):
            continue
        pair = (token.lower(), spender.lower())
        if pair not in required_pairs:
            continue
        if not is_hex_address(token) or not is_hex_address(spender):
            raise UnexpectedResponseError("Trading approval has an invalid token or spender")
        standard = row.get("standard")
        approved = row.get("approved")
        if standard not in ("ERC20", "ERC1155") or not isinstance(approved, bool):
            raise UnexpectedResponseError(
                "Trading approval has an invalid standard or approved flag"
            )
        amount = _parse_approval_amount(row.get("amount")) if standard == "ERC20" else None
        if pair in indexed:
            raise UnexpectedResponseError(
                "Trading approvals contain a duplicate token/spender pair"
            )
        indexed[pair] = (cast(str, standard), approved, amount)

    missing_erc20: list[Erc20TradingApproval] = []
    missing_erc1155: list[Erc1155TradingApproval] = []
    for approval in erc20:
        row = indexed.get((approval.token_address.lower(), approval.spender.lower()))
        if row is None or row[0] != "ERC20" or row[2] is None:
            raise UnexpectedResponseError("Trading approvals are missing a required ERC20 pair")
        # Persistent rows report "max" even when unapproved; exact rows may
        # report approved for a positive allowance below the SDK requirement.
        if not row[1] or row[2] < approval.amount:
            missing_erc20.append(approval)
    for approval in erc1155:
        row = indexed.get((approval.token_address.lower(), approval.operator.lower()))
        if row is None or row[0] != "ERC1155":
            raise UnexpectedResponseError("Trading approvals are missing a required ERC1155 pair")
        if not row[1]:
            missing_erc1155.append(approval)
    missing = MissingTradingApprovals(erc20=tuple(missing_erc20), erc1155=tuple(missing_erc1155))
    return TradingApprovalsState(
        missing=missing, is_fully_approved=not missing.erc20 and not missing.erc1155
    )


def _parse_approval_amount(value: object) -> int:
    if value == "max":
        return MAX_UINT256
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or len(value) > 78
        or (len(value) > 1 and value[0] == "0")
    ):
        raise UnexpectedResponseError("Trading approval amount must be a uint256 decimal or max")
    amount = int(value)
    if amount > MAX_UINT256:
        raise UnexpectedResponseError("Trading approval amount exceeds uint256")
    return amount


async def get_trading_approvals_state(
    rpc: JsonRpcClient, *, wallet: str, config: EnvironmentConfig
) -> TradingApprovalsState:
    wallet_address = _normalize_wallet(wallet)
    erc20, erc1155 = _required_trading_approvals(config)
    erc20_checks, erc1155_checks = _build_approval_checks(
        wallet=wallet_address, erc20=erc20, erc1155=erc1155
    )
    results = await rpc.eth_call_batch(
        [(str(check.to), check.data) for check in [*erc20_checks, *erc1155_checks]]
    )
    return _parse_trading_approvals_state(erc20=erc20, erc1155=erc1155, results=results)


def get_trading_approvals_state_sync(
    rpc: SyncJsonRpcClient, *, wallet: str, config: EnvironmentConfig
) -> TradingApprovalsState:
    wallet_address = _normalize_wallet(wallet)
    erc20, erc1155 = _required_trading_approvals(config)
    erc20_checks, erc1155_checks = _build_approval_checks(
        wallet=wallet_address, erc20=erc20, erc1155=erc1155
    )
    results = rpc.eth_call_batch(
        [(str(check.to), check.data) for check in [*erc20_checks, *erc1155_checks]]
    )
    return _parse_trading_approvals_state(erc20=erc20, erc1155=erc1155, results=results)


def build_missing_trading_approval_calls(
    missing: MissingTradingApprovals,
) -> list[TransactionCall]:
    erc20_calls = [
        erc20_approval_call(
            token_address=approval.token_address,
            spender=approval.spender,
            amount=approval.amount,
        )
        for approval in missing.erc20
    ]
    erc1155_calls = [
        erc1155_set_approval_for_all_call(
            token_address=approval.token_address,
            operator=approval.operator,
            approved=True,
        )
        for approval in missing.erc1155
    ]
    return erc20_calls + erc1155_calls


def _build_approval_checks(
    *,
    wallet: EvmAddress,
    erc20: tuple[Erc20TradingApproval, ...],
    erc1155: tuple[Erc1155TradingApproval, ...],
) -> tuple[list[TransactionCall], list[TransactionCall]]:
    erc20_checks = [
        erc20_allowance_call(
            token_address=approval.token_address,
            owner=wallet,
            spender=approval.spender,
        )
        for approval in erc20
    ]
    erc1155_checks = [
        erc1155_is_approved_for_all_call(
            token_address=approval.token_address,
            owner=wallet,
            operator=approval.operator,
        )
        for approval in erc1155
    ]
    return erc20_checks, erc1155_checks


def _parse_trading_approvals_state(
    *,
    erc20: tuple[Erc20TradingApproval, ...],
    erc1155: tuple[Erc1155TradingApproval, ...],
    results: list[str],
) -> TradingApprovalsState:
    missing_erc20 = tuple(
        approval
        for approval, result in zip(erc20, results[: len(erc20)], strict=True)
        if decode_erc20_allowance_result(result) < approval.amount
    )
    missing_erc1155 = tuple(
        approval
        for approval, result in zip(erc1155, results[len(erc20) :], strict=True)
        if not decode_erc1155_is_approved_for_all_result(result)
    )
    missing = MissingTradingApprovals(erc20=missing_erc20, erc1155=missing_erc1155)
    return TradingApprovalsState(
        missing=missing,
        is_fully_approved=not missing.erc20 and not missing.erc1155,
    )


def _normalize_wallet(wallet: str) -> EvmAddress:
    try:
        return cast(EvmAddress, to_checksum_address(wallet))
    except ValueError as error:
        raise UserInputError(f"Invalid wallet address: {error}") from error


def _required_trading_approvals(
    config: EnvironmentConfig,
) -> tuple[tuple[Erc20TradingApproval, ...], tuple[Erc1155TradingApproval, ...]]:
    collateral = cast(EvmAddress, config.collateral_token)
    conditional = cast(EvmAddress, config.conditional_tokens)
    return (
        (
            Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, config.standard_exchange),
                amount=MAX_UINT256,
            ),
            Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, config.neg_risk_exchange),
                amount=MAX_UINT256,
            ),
            Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, config.collateral_adapter),
                amount=MAX_UINT256,
            ),
            Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, config.neg_risk_collateral_adapter),
                amount=MAX_UINT256,
            ),
            Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, config.protocol_v2_router),
                amount=MAX_UINT256,
            ),
            Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, config.exchange_v3),
                amount=MAX_UINT256,
            ),
            Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, config.perps_deposit_contract),
                amount=MAX_UINT256,
            ),
        ),
        (
            Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, config.standard_exchange),
            ),
            Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, config.neg_risk_exchange),
            ),
            Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, config.collateral_adapter),
            ),
            Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, config.neg_risk_collateral_adapter),
            ),
            Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, config.auto_redeem_operator),
            ),
            Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, config.binary_module),
            ),
            Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, config.neg_risk_module),
            ),
            Erc1155TradingApproval(
                token_address=cast(EvmAddress, config.position_manager),
                operator=cast(EvmAddress, config.protocol_v2_router),
            ),
            Erc1155TradingApproval(
                token_address=cast(EvmAddress, config.position_manager),
                operator=cast(EvmAddress, config.exchange_v3),
            ),
            Erc1155TradingApproval(
                token_address=cast(EvmAddress, config.position_manager),
                operator=cast(EvmAddress, config.auto_redeem_operator),
            ),
        ),
    )


__all__ = [
    "build_get_trading_approvals_state_spec",
    "build_missing_trading_approval_calls",
    "get_trading_approvals_state",
    "get_trading_approvals_state_sync",
]
