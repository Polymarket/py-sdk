"""Shared request construction and response parsing for account funding."""

from urllib.parse import quote

from eth_utils.address import to_checksum_address

from polymarket._internal.validation import require_nonempty, validate_builder_code
from polymarket.errors import UserInputError
from polymarket.models.base import BaseModel
from polymarket.models.funding import (
    FundingAddressSet,
    FundingAssetCatalog,
    FundingQuote,
    FundingTransaction,
)

_BUILDER_CODE_HEADER = "X-Builder-Code"


class _FundingTransactionsResponse(BaseModel):
    transactions: tuple[FundingTransaction, ...]


def _validate_evm_address(name: str, value: object) -> str:
    validated = require_nonempty(name, value)
    if len(validated) != 42 or not validated.startswith("0x"):
        raise UserInputError(f"{name} must be a valid EVM address.")
    try:
        int(validated[2:], 16)
        return to_checksum_address(validated)
    except ValueError as error:
        raise UserInputError(f"{name} must be a valid EVM address.") from error


def _require_nonblank(name: str, value: object) -> str:
    validated = require_nonempty(name, value).strip()
    if not validated:
        raise UserInputError(f"{name} is required")
    return validated


def _validate_positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise UserInputError(f"{name} must be a positive integer.")
    return value


def _builder_headers(builder_code: str | None) -> dict[str, str]:
    if builder_code is None:
        return {}
    return {_BUILDER_CODE_HEADER: validate_builder_code(builder_code)}


def build_create_deposit_addresses_request(
    *, wallet: str, builder_code: str | None = None
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Build a request for chain-specific deposit addresses."""
    return (
        "/deposit",
        {"address": _validate_evm_address("wallet", wallet)},
        _builder_headers(builder_code),
    )


def build_create_withdrawal_addresses_request(
    *,
    wallet: str,
    destination_chain_id: int,
    destination_token_address: str,
    recipient_address: str,
    builder_code: str | None = None,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Build a request for chain-specific withdrawal addresses."""
    return (
        "/withdraw",
        {
            "address": _validate_evm_address("wallet", wallet),
            "toChainId": str(
                _validate_positive_integer("destination_chain_id", destination_chain_id)
            ),
            "toTokenAddress": _require_nonblank(
                "destination_token_address", destination_token_address
            ),
            "recipientAddr": _require_nonblank("recipient_address", recipient_address),
        },
        _builder_headers(builder_code),
    )


def build_funding_quote_request(
    *,
    amount: int,
    source_chain_id: int,
    source_token_address: str,
    destination_chain_id: int,
    destination_token_address: str,
    recipient_address: str,
) -> tuple[str, dict[str, str]]:
    """Build a request for a funding transfer quote."""
    return (
        "/quote",
        {
            "fromAmountBaseUnit": str(_validate_positive_integer("amount", amount)),
            "fromChainId": str(_validate_positive_integer("source_chain_id", source_chain_id)),
            "fromTokenAddress": _require_nonblank("source_token_address", source_token_address),
            "recipientAddress": _require_nonblank("recipient_address", recipient_address),
            "toChainId": str(
                _validate_positive_integer("destination_chain_id", destination_chain_id)
            ),
            "toTokenAddress": _require_nonblank(
                "destination_token_address", destination_token_address
            ),
        },
    )


def build_funding_status_request(*, address: str) -> str:
    """Build a status path for an EVM, SVM, Bitcoin, or Tron address."""
    validated = _require_nonblank("address", address)
    return f"/status/{quote(validated, safe='')}"


def parse_funding_address_set(data: object) -> FundingAddressSet:
    return FundingAddressSet.parse_response(data)


def parse_funding_asset_catalog(data: object) -> FundingAssetCatalog:
    return FundingAssetCatalog.parse_response(data)


def parse_funding_quote(data: object) -> FundingQuote:
    return FundingQuote.parse_response(data)


def parse_funding_transactions(data: object) -> tuple[FundingTransaction, ...]:
    return _FundingTransactionsResponse.parse_response(data).transactions


__all__ = [
    "build_create_deposit_addresses_request",
    "build_create_withdrawal_addresses_request",
    "build_funding_quote_request",
    "build_funding_status_request",
    "parse_funding_address_set",
    "parse_funding_asset_catalog",
    "parse_funding_quote",
    "parse_funding_transactions",
]
