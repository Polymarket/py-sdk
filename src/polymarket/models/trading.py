"""Trading approval state objects."""

from dataclasses import dataclass

from polymarket.types import EvmAddress


@dataclass(frozen=True, slots=True, kw_only=True)
class Erc20TradingApproval:
    """One required ERC-20 allowance that is not configured for a wallet."""

    token_address: EvmAddress
    spender: EvmAddress
    amount: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Erc1155TradingApproval:
    """One required ERC-1155 operator approval that is not configured for a wallet."""

    token_address: EvmAddress
    operator: EvmAddress


@dataclass(frozen=True, slots=True, kw_only=True)
class MissingTradingApprovals:
    """Trading approvals that a wallet still needs to grant."""

    erc20: tuple[Erc20TradingApproval, ...] = ()
    erc1155: tuple[Erc1155TradingApproval, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class TradingApprovalsState:
    """Current trading approval state for a wallet."""

    missing: MissingTradingApprovals
    is_fully_approved: bool


__all__ = [
    "Erc20TradingApproval",
    "Erc1155TradingApproval",
    "MissingTradingApprovals",
    "TradingApprovalsState",
]
