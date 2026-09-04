from __future__ import annotations

from typing import cast

from eth_utils.address import to_checksum_address

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
from polymarket._internal.environment import EnvironmentConfig
from polymarket._internal.eoa.rpc import JsonRpcClient, SyncJsonRpcClient
from polymarket.errors import UserInputError
from polymarket.models.trading import (
    Erc20TradingApproval,
    Erc1155TradingApproval,
    MissingTradingApprovals,
    TradingApprovalsState,
)
from polymarket.types import EvmAddress


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
    "build_missing_trading_approval_calls",
    "get_trading_approvals_state",
    "get_trading_approvals_state_sync",
]
