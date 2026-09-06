"""Account-funding models."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import TypeAlias

from pydantic import AliasChoices, Field, field_validator

from polymarket.models.base import BaseModel
from polymarket.types import EvmAddress, TransactionHash


class KnownFundingTransactionStatus(StrEnum):
    """Known lifecycle states for an account-funding transaction."""

    DEPOSIT_DETECTED = "DEPOSIT_DETECTED"
    PROCESSING = "PROCESSING"
    ORIGIN_TRANSACTION_CONFIRMED = "ORIGIN_TX_CONFIRMED"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# The provider may add transaction states between SDK releases. Preserve
# unknown values as strings while making current states discoverable.
FundingTransactionStatus: TypeAlias = KnownFundingTransactionStatus | str


def _parse_decimal_number(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"expected a decimal number, got bool {value!r}")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, str | int | float):
        try:
            result = Decimal(str(value))
        except DecimalException as error:
            raise ValueError(f"invalid decimal number: {value!r}") from error
    else:
        raise ValueError(f"expected a decimal number, got {type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"expected a finite decimal number, got {value!r}")
    return result


def _parse_nonnegative_integer(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(f"expected a non-negative integer, got bool {value!r}")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isdecimal():
        result = int(value)
    else:
        raise ValueError(f"expected a non-negative integer, got {value!r}")
    if result < 0:
        raise ValueError(f"expected a non-negative integer, got {value!r}")
    return result


def _parse_positive_integer(value: object) -> int:
    result = _parse_nonnegative_integer(value)
    if result == 0:
        raise ValueError(f"expected a positive integer, got {value!r}")
    return result


def _parse_evm_address(value: object) -> EvmAddress:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise ValueError(f"expected an EVM address, got {value!r}")
    try:
        int(value[2:], 16)
    except ValueError as error:
        raise ValueError(f"expected an EVM address, got {value!r}") from error
    return EvmAddress(value)


def _parse_epoch_milliseconds(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.utcoffset() is not None else value.replace(tzinfo=UTC)
    milliseconds = _parse_nonnegative_integer(value)
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError(f"invalid epoch-millisecond timestamp: {value!r}") from error


def _parse_milliseconds_duration(value: object) -> timedelta:
    if isinstance(value, timedelta):
        return value
    milliseconds = _parse_nonnegative_integer(value)
    return timedelta(milliseconds=milliseconds)


class FundingAddresses(BaseModel):
    """Chain-specific addresses configured for one funding workflow."""

    evm: EvmAddress
    svm: str = Field(min_length=1)
    btc: str = Field(min_length=1)
    tron: str | None = Field(
        default=None,
        min_length=1,
        validation_alias=AliasChoices("tron", "tvm"),
    )

    @field_validator("evm", mode="before")
    @classmethod
    def _parse_evm(cls, value: object) -> EvmAddress:
        return _parse_evm_address(value)


class FundingWarning(BaseModel):
    """A non-fatal warning returned while creating funding addresses."""

    code: str
    message: str


class FundingAddressSet(BaseModel):
    """Addresses and advisories for a deposit or withdrawal workflow."""

    addresses: FundingAddresses = Field(validation_alias="address")
    note: str | None = None
    warnings: tuple[FundingWarning, ...] = ()


class FundingToken(BaseModel):
    """A token available for account funding or withdrawal."""

    name: str
    symbol: str
    address: str
    decimals: int = Field(ge=0)


class FundingAsset(BaseModel):
    """A supported chain and token pair."""

    chain_id: int = Field(validation_alias="chainId")
    chain_name: str = Field(validation_alias="chainName")
    token: FundingToken
    minimum_amount_usd: Decimal = Field(validation_alias="minCheckoutUsd", ge=0)

    @field_validator("chain_id", mode="before")
    @classmethod
    def _parse_chain_id(cls, value: object) -> int:
        return _parse_positive_integer(value)

    @field_validator("minimum_amount_usd", mode="before")
    @classmethod
    def _parse_minimum_amount(cls, value: object) -> Decimal:
        return _parse_decimal_number(value)


class FundingAssetCatalog(BaseModel):
    """Supported account-funding assets and any current advisory."""

    assets: tuple[FundingAsset, ...] = Field(validation_alias="supportedAssets")
    note: str | None = None


class FundingFeeBreakdown(BaseModel):
    """Estimated costs included in a funding quote."""

    app_fee_label: str = Field(validation_alias="appFeeLabel")
    app_fee_percent: Decimal = Field(validation_alias="appFeePercent")
    app_fee_usd: Decimal = Field(validation_alias="appFeeUsd")
    fill_cost_percent: Decimal = Field(validation_alias="fillCostPercent")
    fill_cost_usd: Decimal = Field(validation_alias="fillCostUsd")
    gas_usd: Decimal = Field(validation_alias="gasUsd")
    max_slippage: Decimal = Field(validation_alias="maxSlippage")
    minimum_received: Decimal = Field(validation_alias="minReceived")
    swap_impact: Decimal = Field(validation_alias="swapImpact")
    swap_impact_usd: Decimal = Field(validation_alias="swapImpactUsd")
    total_impact: Decimal = Field(validation_alias="totalImpact")
    total_impact_usd: Decimal = Field(validation_alias="totalImpactUsd")

    @field_validator(
        "app_fee_percent",
        "app_fee_usd",
        "fill_cost_percent",
        "fill_cost_usd",
        "gas_usd",
        "max_slippage",
        "minimum_received",
        "swap_impact",
        "swap_impact_usd",
        "total_impact",
        "total_impact_usd",
        mode="before",
    )
    @classmethod
    def _parse_decimal_fields(cls, value: object) -> Decimal:
        return _parse_decimal_number(value)


class FundingQuote(BaseModel):
    """Estimated result and costs for a funding transfer."""

    estimated_checkout_time: timedelta = Field(validation_alias="estCheckoutTimeMs")
    estimated_fees: FundingFeeBreakdown = Field(validation_alias="estFeeBreakdown")
    estimated_input_usd: Decimal = Field(validation_alias="estInputUsd")
    estimated_output_usd: Decimal = Field(validation_alias="estOutputUsd")
    estimated_destination_amount: int = Field(validation_alias="estToTokenBaseUnit")
    quote_id: str = Field(validation_alias="quoteId", min_length=1)

    @field_validator("estimated_checkout_time", mode="before")
    @classmethod
    def _parse_checkout_time(cls, value: object) -> timedelta:
        return _parse_milliseconds_duration(value)

    @field_validator("estimated_input_usd", "estimated_output_usd", mode="before")
    @classmethod
    def _parse_decimal_fields(cls, value: object) -> Decimal:
        return _parse_decimal_number(value)

    @field_validator("estimated_destination_amount", mode="before")
    @classmethod
    def _parse_destination_amount(cls, value: object) -> int:
        return _parse_nonnegative_integer(value)


class FundingTransaction(BaseModel):
    """The current state of one account-funding transaction."""

    source_chain_id: int = Field(validation_alias="fromChainId")
    source_token_address: str = Field(validation_alias="fromTokenAddress")
    source_amount: int = Field(validation_alias="fromAmountBaseUnit")
    destination_chain_id: int = Field(validation_alias="toChainId")
    destination_token_address: str = Field(validation_alias="toTokenAddress")
    status: FundingTransactionStatus
    transaction_hash: TransactionHash | None = Field(default=None, validation_alias="txHash")
    created_at: datetime | None = Field(default=None, validation_alias="createdTimeMs")

    @field_validator("source_chain_id", "destination_chain_id", mode="before")
    @classmethod
    def _parse_chain_ids(cls, value: object) -> int:
        return _parse_positive_integer(value)

    @field_validator("source_amount", mode="before")
    @classmethod
    def _parse_source_amount(cls, value: object) -> int:
        return _parse_nonnegative_integer(value)

    @field_validator("status", mode="before")
    @classmethod
    def _parse_status(cls, value: object) -> FundingTransactionStatus:
        if isinstance(value, KnownFundingTransactionStatus):
            return value
        if not isinstance(value, str) or not value:
            raise ValueError(f"expected a funding transaction status, got {value!r}")
        try:
            return KnownFundingTransactionStatus(value)
        except ValueError:
            return value

    @field_validator("transaction_hash", mode="before")
    @classmethod
    def _parse_transaction_hash(cls, value: object) -> TransactionHash | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ValueError(f"expected a transaction hash, got {value!r}")
        return TransactionHash(value)

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_created_at(cls, value: object) -> datetime | None:
        if value is None:
            return None
        return _parse_epoch_milliseconds(value)


__all__ = [
    "FundingAddressSet",
    "FundingAddresses",
    "FundingAsset",
    "FundingAssetCatalog",
    "FundingFeeBreakdown",
    "FundingQuote",
    "FundingToken",
    "FundingTransaction",
    "FundingTransactionStatus",
    "FundingWarning",
    "KnownFundingTransactionStatus",
]
