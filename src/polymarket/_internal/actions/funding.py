"""Shared request construction and response parsing for account funding."""

from urllib.parse import quote

from eth_utils.address import to_checksum_address
from pydantic import Field, field_validator

from polymarket._internal.request import QueryParamValue
from polymarket._internal.validation import require_nonempty, validate_builder_code
from polymarket.errors import UserInputError
from polymarket.models.base import BaseModel
from polymarket.models.funding import (
    FundingAddressSet,
    FundingAssetCatalog,
    FundingQuote,
    FundingTransaction,
)
from polymarket.pagination import Page

_BUILDER_CODE_HEADER = "X-Builder-Code"
_DEFAULT_STATUS_PAGE_SIZE = 50
_MAX_STATUS_PAGE_SIZE = 100


class _FundingTransactionsPageResponse(BaseModel):
    transactions: tuple[FundingTransaction, ...]
    # Production may briefly return the pre-pagination shape while the new
    # required nextCursor field rolls out. Treat omission as a terminal page.
    next_cursor: str | None = Field(default=None, validation_alias="nextCursor")

    @field_validator("next_cursor")
    @classmethod
    def _validate_next_cursor(cls, value: str | None) -> str | None:
        if value == "":
            raise ValueError("nextCursor must be non-empty or null")
        return value


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


def build_list_funding_transactions_request(
    *,
    address: str,
    page_size: int = _DEFAULT_STATUS_PAGE_SIZE,
    cursor: str | None = None,
) -> tuple[str, dict[str, QueryParamValue]]:
    """Build a request for one page of funding transactions."""
    validated = _require_nonblank("address", address)
    if type(page_size) is not int:
        raise UserInputError("page_size must be an int.")
    if page_size < 1 or page_size > _MAX_STATUS_PAGE_SIZE:
        raise UserInputError(f"page_size must be between 1 and {_MAX_STATUS_PAGE_SIZE}.")
    params: dict[str, QueryParamValue] = {"limit": page_size}
    if cursor is not None:
        params["cursor"] = require_nonempty("cursor", cursor)
    return f"/status/{quote(validated, safe='')}", params


def parse_funding_address_set(data: object) -> FundingAddressSet:
    return FundingAddressSet.parse_response(data)


def parse_funding_asset_catalog(data: object) -> FundingAssetCatalog:
    return FundingAssetCatalog.parse_response(data)


def parse_funding_quote(data: object) -> FundingQuote:
    return FundingQuote.parse_response(data)


def parse_funding_transactions_page(data: object) -> Page[FundingTransaction]:
    response = _FundingTransactionsPageResponse.parse_response(data)
    return Page(
        items=response.transactions,
        has_more=response.next_cursor is not None,
        next_cursor=response.next_cursor,
    )


__all__ = [
    "build_create_deposit_addresses_request",
    "build_create_withdrawal_addresses_request",
    "build_funding_quote_request",
    "build_list_funding_transactions_request",
    "parse_funding_address_set",
    "parse_funding_asset_catalog",
    "parse_funding_quote",
    "parse_funding_transactions_page",
]
