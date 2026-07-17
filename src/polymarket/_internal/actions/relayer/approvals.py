from __future__ import annotations

from dataclasses import dataclass
from typing import cast

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
from polymarket._internal.eoa.rpc import JsonRpcClient, SyncJsonRpcClient
from polymarket.environments import Environment
from polymarket.types import EvmAddress


@dataclass(frozen=True, slots=True)
class _Erc20TradingApproval:
    token_address: EvmAddress
    spender: EvmAddress
    amount: int


@dataclass(frozen=True, slots=True)
class _Erc1155TradingApproval:
    token_address: EvmAddress
    operator: EvmAddress


async def resolve_missing_trading_approval_calls(
    rpc: JsonRpcClient, *, wallet: EvmAddress, environment: Environment
) -> list[TransactionCall]:
    erc20, erc1155 = _required_trading_approvals(environment)
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
    results = await rpc.eth_call_batch(
        [(str(check.to), check.data) for check in [*erc20_checks, *erc1155_checks]]
    )

    erc20_missing: list[TransactionCall] = []
    for approval, result in zip(erc20, results[: len(erc20)], strict=True):
        allowance = decode_erc20_allowance_result(result)
        if allowance < approval.amount:
            erc20_missing.append(
                erc20_approval_call(
                    token_address=approval.token_address,
                    spender=approval.spender,
                    amount=approval.amount,
                )
            )

    erc1155_missing: list[TransactionCall] = []
    for approval, result in zip(erc1155, results[len(erc20) :], strict=True):
        approved = decode_erc1155_is_approved_for_all_result(result)
        if not approved:
            erc1155_missing.append(
                erc1155_set_approval_for_all_call(
                    token_address=approval.token_address,
                    operator=approval.operator,
                    approved=True,
                )
            )

    return erc20_missing + erc1155_missing


def resolve_missing_trading_approval_calls_sync(
    rpc: SyncJsonRpcClient, *, wallet: EvmAddress, environment: Environment
) -> list[TransactionCall]:
    erc20, erc1155 = _required_trading_approvals(environment)
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
    results = rpc.eth_call_batch(
        [(str(check.to), check.data) for check in [*erc20_checks, *erc1155_checks]]
    )

    erc20_missing: list[TransactionCall] = []
    for approval, result in zip(erc20, results[: len(erc20)], strict=True):
        allowance = decode_erc20_allowance_result(result)
        if allowance < approval.amount:
            erc20_missing.append(
                erc20_approval_call(
                    token_address=approval.token_address,
                    spender=approval.spender,
                    amount=approval.amount,
                )
            )

    erc1155_missing: list[TransactionCall] = []
    for approval, result in zip(erc1155, results[len(erc20) :], strict=True):
        approved = decode_erc1155_is_approved_for_all_result(result)
        if not approved:
            erc1155_missing.append(
                erc1155_set_approval_for_all_call(
                    token_address=approval.token_address,
                    operator=approval.operator,
                    approved=True,
                )
            )

    return erc20_missing + erc1155_missing


def _required_trading_approvals(
    environment: Environment,
) -> tuple[list[_Erc20TradingApproval], list[_Erc1155TradingApproval]]:
    collateral = cast(EvmAddress, environment.collateral_token)
    conditional = cast(EvmAddress, environment.conditional_tokens)
    return (
        [
            _Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, environment.standard_exchange),
                amount=MAX_UINT256,
            ),
            _Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, environment.neg_risk_exchange),
                amount=MAX_UINT256,
            ),
            _Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, environment.collateral_adapter),
                amount=MAX_UINT256,
            ),
            _Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, environment.neg_risk_collateral_adapter),
                amount=MAX_UINT256,
            ),
            _Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, environment.protocol_v2_router),
                amount=MAX_UINT256,
            ),
            _Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, environment.exchange_v3),
                amount=MAX_UINT256,
            ),
            _Erc20TradingApproval(
                token_address=collateral,
                spender=cast(EvmAddress, environment.perps_deposit_contract),
                amount=MAX_UINT256,
            ),
        ],
        [
            _Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, environment.standard_exchange),
            ),
            _Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, environment.neg_risk_exchange),
            ),
            _Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, environment.collateral_adapter),
            ),
            _Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, environment.neg_risk_collateral_adapter),
            ),
            _Erc1155TradingApproval(
                token_address=conditional,
                operator=cast(EvmAddress, environment.auto_redeem_operator),
            ),
            _Erc1155TradingApproval(
                token_address=cast(EvmAddress, environment.position_manager),
                operator=cast(EvmAddress, environment.protocol_v2_router),
            ),
            _Erc1155TradingApproval(
                token_address=cast(EvmAddress, environment.position_manager),
                operator=cast(EvmAddress, environment.exchange_v3),
            ),
            _Erc1155TradingApproval(
                token_address=cast(EvmAddress, environment.position_manager),
                operator=cast(EvmAddress, environment.auto_redeem_operator),
            ),
        ],
    )


__all__ = [
    "resolve_missing_trading_approval_calls",
    "resolve_missing_trading_approval_calls_sync",
]
