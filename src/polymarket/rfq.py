from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import TracebackType
from typing import Any, Literal, Protocol, TypeAlias, runtime_checkable

from polymarket.errors import PolymarketError
from polymarket.models.types import ComboConditionId, PositionId
from polymarket.types import EvmAddress, TransactionHash

RfqId: TypeAlias = str
RfqQuoteId: TypeAlias = str
RfqRequestorPublicId: TypeAlias = str


class RfqDirection(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class RfqSide(StrEnum):
    YES = "YES"


class RfqQuoteSource(StrEnum):
    COLLATERAL = "collateral"
    INVENTORY = "inventory"


class RfqRequestedSizeUnit(StrEnum):
    NOTIONAL = "notional"
    SHARES = "shares"


class RfqConfirmationDecision(StrEnum):
    CONFIRM = "CONFIRM"
    DECLINE = "DECLINE"


class RfqExecutionStatus(StrEnum):
    MATCHED = "MATCHED"
    MINED = "MINED"
    CONFIRMED = "CONFIRMED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"


class RfqErrorCode(StrEnum):
    ADDRESS_MISMATCH = "ADDRESS_MISMATCH"
    ALLOWANCE_VALIDATION_FAILED = "ALLOWANCE_VALIDATION_FAILED"
    BALANCE_VALIDATION_FAILED = "BALANCE_VALIDATION_FAILED"
    CONTRADICTORY_LEGS = "CONTRADICTORY_LEGS"
    EXPIRED_RFQ = "EXPIRED_RFQ"
    INVALID_ACCEPTANCE = "INVALID_ACCEPTANCE"
    INVALID_CONFIRMATION = "INVALID_CONFIRMATION"
    INVALID_EXECUTION_RESULT = "INVALID_EXECUTION_RESULT"
    INVALID_IDENTITY = "INVALID_IDENTITY"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    INVALID_QUOTE = "INVALID_QUOTE"
    INVALID_RFQ = "INVALID_RFQ"
    INVALID_RFQ_STATE = "INVALID_RFQ_STATE"
    INVALID_ROLE = "INVALID_ROLE"
    LEG_METADATA_UNAVAILABLE = "LEG_METADATA_UNAVAILABLE"
    MAKER_ALREADY_RESPONDED = "MAKER_ALREADY_RESPONDED"
    MAKER_NOT_REQUIRED = "MAKER_NOT_REQUIRED"
    PRE_EXECUTION_BALANCE_RESERVATION_FAILED = "PRE_EXECUTION_BALANCE_RESERVATION_FAILED"
    QUOTE_MISMATCH = "QUOTE_MISMATCH"
    QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    REQUEST_FAILED = "REQUEST_FAILED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    SUBMISSION_WINDOW_CLOSED = "SUBMISSION_WINDOW_CLOSED"
    TRADE_SUBMISSION_FAILED = "TRADE_SUBMISSION_FAILED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    UNAUTHORIZED_ROLE = "UNAUTHORIZED_ROLE"
    UNKNOWN_RFQ = "UNKNOWN_RFQ"


@dataclass(frozen=True, slots=True, kw_only=True)
class RfqRequestedSize:
    unit: RfqRequestedSizeUnit
    value: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class RfqQuoteReference:
    rfq_id: RfqId
    quote_id: RfqQuoteId


@dataclass(frozen=True, slots=True, kw_only=True)
class RfqCancelQuoteAck:
    rfq_id: RfqId
    quote_id: RfqQuoteId


@dataclass(frozen=True, slots=True, kw_only=True)
class RfqConfirmationAck:
    rfq_id: RfqId
    quote_id: RfqQuoteId


@dataclass(frozen=True, slots=True, kw_only=True)
class RfqExecutionUpdateEvent:
    type: Literal["execution_update"]
    rfq_id: RfqId
    status: RfqExecutionStatus
    tx_hash: TransactionHash | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RfqTradeEvent:
    type: Literal["trade"]
    rfq_id: RfqId
    requester_id: RfqRequestorPublicId
    condition_id: ComboConditionId
    leg_position_ids: tuple[PositionId, ...]
    direction: RfqDirection
    side: RfqSide
    price: Decimal
    size: Decimal
    executed_at: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RfqQuoteRequestEvent:
    type: Literal["quote_request"]
    rfq_id: RfqId
    requestor_public_id: RfqRequestorPublicId
    leg_position_ids: tuple[PositionId, ...]
    condition_id: ComboConditionId
    yes_position_id: PositionId
    no_position_id: PositionId
    direction: RfqDirection
    side: RfqSide
    requested_size: RfqRequestedSize
    submission_deadline: int
    _session: RfqSession = field(repr=False, compare=False)

    async def quote(
        self,
        *,
        price: Decimal | int | float | str,
        size: Decimal | int | float | str | None = None,
        source: RfqQuoteSource | str = RfqQuoteSource.COLLATERAL,
    ) -> RfqQuoteReference:
        return await self._session.quote(self, price=price, size=size, source=source)


@dataclass(frozen=True, slots=True, kw_only=True)
class RfqConfirmationRequestEvent:
    type: Literal["confirmation_request"]
    rfq_id: RfqId
    quote_id: RfqQuoteId
    signer_address: EvmAddress
    maker_address: EvmAddress
    signature_type: int
    leg_position_ids: tuple[PositionId, ...]
    condition_id: ComboConditionId
    yes_position_id: PositionId
    no_position_id: PositionId
    direction: RfqDirection
    side: RfqSide
    fill_size: Decimal
    price: Decimal
    confirm_by: int
    _session: RfqSession = field(repr=False, compare=False)

    async def confirm(self) -> RfqConfirmationAck:
        return await self._session.respond_to_confirmation(
            self.rfq_id, self.quote_id, RfqConfirmationDecision.CONFIRM
        )

    async def decline(self) -> RfqConfirmationAck:
        return await self._session.respond_to_confirmation(
            self.rfq_id, self.quote_id, RfqConfirmationDecision.DECLINE
        )


RfqEvent = (
    RfqQuoteRequestEvent | RfqConfirmationRequestEvent | RfqExecutionUpdateEvent | RfqTradeEvent
)


class RfqQuoteRejectedError(PolymarketError):
    def __init__(self, message: str, *, rfq_id: RfqId, code: RfqErrorCode | None = None) -> None:
        super().__init__(message)
        self.rfq_id = rfq_id
        self.code = code


class RfqCancelQuoteRejectedError(PolymarketError):
    def __init__(
        self,
        message: str,
        *,
        rfq_id: RfqId,
        quote_id: RfqQuoteId,
        code: RfqErrorCode | None = None,
    ) -> None:
        super().__init__(message)
        self.rfq_id = rfq_id
        self.quote_id = quote_id
        self.code = code


class RfqConfirmationRejectedError(PolymarketError):
    def __init__(
        self,
        message: str,
        *,
        rfq_id: RfqId,
        quote_id: RfqQuoteId,
        code: RfqErrorCode | None = None,
    ) -> None:
        super().__init__(message)
        self.rfq_id = rfq_id
        self.quote_id = quote_id
        self.code = code


@runtime_checkable
class RfqSession(Protocol):
    def __await__(self) -> Generator[Any, None, RfqSession]: ...
    def __aiter__(self) -> AsyncIterator[RfqEvent]: ...
    async def __anext__(self) -> RfqEvent: ...
    async def close(self) -> None: ...
    async def cancel_quote(self, quote: RfqQuoteReference) -> RfqCancelQuoteAck: ...
    async def quote(
        self,
        request: RfqQuoteRequestEvent,
        *,
        price: Decimal | int | float | str,
        size: Decimal | int | float | str | None = None,
        source: RfqQuoteSource | str = RfqQuoteSource.COLLATERAL,
    ) -> RfqQuoteReference: ...
    async def respond_to_confirmation(
        self,
        rfq_id: RfqId,
        quote_id: RfqQuoteId,
        decision: RfqConfirmationDecision,
    ) -> RfqConfirmationAck: ...
    async def __aenter__(self) -> RfqSession: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


__all__ = [
    "RfqCancelQuoteAck",
    "RfqCancelQuoteRejectedError",
    "RfqConfirmationAck",
    "RfqConfirmationDecision",
    "RfqConfirmationRejectedError",
    "RfqConfirmationRequestEvent",
    "RfqDirection",
    "RfqErrorCode",
    "RfqEvent",
    "RfqExecutionStatus",
    "RfqExecutionUpdateEvent",
    "RfqId",
    "RfqQuoteId",
    "RfqQuoteReference",
    "RfqQuoteRejectedError",
    "RfqQuoteRequestEvent",
    "RfqQuoteSource",
    "RfqRequestedSize",
    "RfqRequestedSizeUnit",
    "RfqRequestorPublicId",
    "RfqSession",
    "RfqSide",
    "RfqTradeEvent",
]
