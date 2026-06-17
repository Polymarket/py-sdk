from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Generator, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, Self, cast

from eth_account.signers.local import LocalAccount

from polymarket._internal.actions.orders.typed_data import (
    build_order_signature,
    build_order_typed_data,
)
from polymarket._internal.actions.orders.types import BYTES32_ZERO, UnsignedOrder
from polymarket._internal.wallet import WalletType, signature_type_for
from polymarket._internal.ws.connection import AsyncWebSocketConnection
from polymarket.errors import (
    SigningError,
    TransportError,
    UnexpectedResponseError,
    UserInputError,
)
from polymarket.errors import (
    TimeoutError as SDKTimeoutError,
)
from polymarket.models import ApiKeyCreds
from polymarket.models.types import (
    ComboConditionId,
    OrderSide,
    PositionId,
    TokenId,
    to_combo_condition_id,
)
from polymarket.rfq import (
    RfqCancelQuoteAck,
    RfqCancelQuoteRejectedError,
    RfqConfirmationAck,
    RfqConfirmationDecision,
    RfqConfirmationRejectedError,
    RfqConfirmationRequestEvent,
    RfqDirection,
    RfqErrorCode,
    RfqEvent,
    RfqExecutionStatus,
    RfqExecutionUpdateEvent,
    RfqId,
    RfqQuoteId,
    RfqQuoteReference,
    RfqQuoteRejectedError,
    RfqQuoteRequestEvent,
    RfqQuoteSource,
    RfqRequestedSize,
    RfqRequestedSizeUnit,
    RfqSide,
    RfqTradeEvent,
)
from polymarket.types import EvmAddress, HexString, TransactionHash

_E6 = 1_000_000
_POLY_1271_SIGNATURE_TYPE = 3
_ACK_TIMEOUT_S = 30.0
_QUEUE_SIZE = 1024
_PROTOCOL_VERSION_V3 = "3"


@dataclass(frozen=True, slots=True)
class _PendingAck:
    future: asyncio.Future[Any]
    waiter: asyncio.Future[Any]


class RfqSessionContext:
    def __init__(self, open_session: Callable[[], Awaitable[RfqQuoterSession]]) -> None:
        self._open_session = open_session
        self._session: RfqQuoterSession | None = None

    def __await__(self) -> Generator[Any, None, RfqQuoterSession]:
        return self._ensure_open().__await__()

    def __aiter__(self) -> AsyncIterator[RfqEvent]:
        return self

    async def __anext__(self) -> RfqEvent:
        session = await self._ensure_open()
        return await session.__anext__()

    async def __aenter__(self) -> RfqQuoterSession:
        return await self._ensure_open()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def cancel_quote(self, quote: RfqQuoteReference) -> RfqCancelQuoteAck:
        session = await self._ensure_open()
        return await session.cancel_quote(quote)

    async def quote(
        self,
        request: RfqQuoteRequestEvent,
        *,
        price: Decimal | int | float | str,
        size: Decimal | int | float | str | None = None,
        source: RfqQuoteSource | str = RfqQuoteSource.COLLATERAL,
    ) -> RfqQuoteReference:
        session = await self._ensure_open()
        return await session.quote(request, price=price, size=size, source=source)

    async def respond_to_confirmation(
        self,
        rfq_id: RfqId,
        quote_id: RfqQuoteId,
        decision: RfqConfirmationDecision,
    ) -> RfqConfirmationAck:
        session = await self._ensure_open()
        return await session.respond_to_confirmation(rfq_id, quote_id, decision)

    async def _ensure_open(self) -> RfqQuoterSession:
        if self._session is None:
            self._session = await self._open_session()
        return self._session


class _EndSentinel:
    __slots__ = ()


_END = _EndSentinel()


class RfqQuoterSession:
    def __init__(
        self,
        *,
        chain_id: int,
        credentials: ApiKeyCreds,
        exchange: EvmAddress,
        headers: Mapping[str, str] | None,
        logger: logging.Logger | None,
        signer: LocalAccount,
        url: str,
        wallet: EvmAddress,
        wallet_type: WalletType,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._chain_id = chain_id
        self._credentials = credentials
        self._exchange = exchange
        self._headers = headers
        self._logger = logger or logging.getLogger("polymarket.rfq")
        self._on_session_close = on_close
        self._signer = signer
        self._url = url
        self._wallet = wallet
        self._wallet_type: WalletType = wallet_type
        self._connection = AsyncWebSocketConnection(logger=self._logger)
        self._queue: asyncio.Queue[RfqEvent | _EndSentinel] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._pending: dict[str, deque[_PendingAck]] = {}
        self._end_error: BaseException | None = None
        self._ended = False
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def __await__(self) -> Generator[Any, None, Self]:
        async def current() -> Self:
            return self

        return current().__await__()

    async def open(self) -> Self:
        await self._connection.connect(
            url=self._url,
            headers=self._headers,
            on_message=self._on_message,
            on_close=self._on_close,
            on_error=self._on_error,
        )
        auth_future = self._wait_for("auth", "Timed out waiting for RFQ authentication.")
        try:
            await self._send(self._auth_message())
            await auth_future
        except BaseException:
            self._remove_pending("auth", auth_future)
            await self.close()
            raise
        return self

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> RfqEvent:
        item = await self._queue.get()
        if isinstance(item, _EndSentinel):
            if self._end_error is not None:
                raise self._end_error
            raise StopAsyncIteration
        return item

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._reject_all_pending(TransportError("RFQ quoter websocket closed."))
        await self._connection.close()
        if self._on_session_close is not None:
            self._on_session_close()
        self._end()

    async def quote(
        self,
        request: RfqQuoteRequestEvent,
        *,
        price: Decimal | int | float | str,
        size: Decimal | int | float | str | None = None,
        source: RfqQuoteSource | str = RfqQuoteSource.COLLATERAL,
    ) -> RfqQuoteReference:
        parsed_price = _decimal_to_e6("price", price)
        if parsed_price >= _E6:
            raise UserInputError("price must be less than 1.")
        parsed_source = _parse_quote_source(source)
        parsed_size = (
            _default_quote_size(request.requested_size, parsed_price)
            if size is None
            else _decimal_to_e6("size", size)
        )
        signed_order = self._sign_quote_order(
            request=request,
            price_e6=parsed_price,
            size_e6=parsed_size,
            source=parsed_source,
        )
        key = _quote_ack_key(request.rfq_id)
        pending = self._wait_for(
            key, f"Timed out waiting for RFQ quote acknowledgement for {request.rfq_id}."
        )
        try:
            await self._send(
                {
                    "type": "RFQ_QUOTE",
                    "rfq_id": request.rfq_id,
                    "price_e6": str(parsed_price),
                    "size_e6": str(parsed_size),
                    "signed_order": signed_order,
                }
            )
            return cast(RfqQuoteReference, await pending)
        except BaseException:
            self._remove_pending(key, pending)
            raise

    async def cancel_quote(self, quote: RfqQuoteReference) -> RfqCancelQuoteAck:
        key = _quote_cancel_ack_key(quote.rfq_id, quote.quote_id)
        pending = self._wait_for(
            key, f"Timed out waiting for RFQ quote cancellation acknowledgement for {quote.rfq_id}."
        )
        try:
            await self._send(
                {
                    "type": "RFQ_QUOTE_CANCEL",
                    "rfq_id": quote.rfq_id,
                    "quote_id": quote.quote_id,
                    "signer_address": self._order_signer_address(),
                    "maker_address": self._wallet,
                }
            )
            return cast(RfqCancelQuoteAck, await pending)
        except BaseException:
            self._remove_pending(key, pending)
            raise

    async def respond_to_confirmation(
        self,
        rfq_id: RfqId,
        quote_id: RfqQuoteId,
        decision: RfqConfirmationDecision,
    ) -> RfqConfirmationAck:
        key = _confirmation_ack_key(rfq_id, quote_id)
        pending = self._wait_for(
            key, f"Timed out waiting for RFQ confirmation acknowledgement for {rfq_id}."
        )
        try:
            await self._send(
                {
                    "type": "RFQ_CONFIRMATION_RESPONSE",
                    "rfq_id": rfq_id,
                    "quote_id": quote_id,
                    "decision": decision.value,
                }
            )
            return cast(RfqConfirmationAck, await pending)
        except BaseException:
            self._remove_pending(key, pending)
            raise

    def _auth_message(self) -> dict[str, object]:
        return {
            "type": "auth",
            "auth": {
                "apiKey": self._credentials.key,
                "passphrase": self._credentials.passphrase,
                "secret": self._credentials.secret,
            },
            "identity": {
                "signer_address": self._order_signer_address(),
                "maker_address": self._wallet,
                "signature_type": signature_type_for(self._wallet_type),
            },
        }

    def _order_signer_address(self) -> EvmAddress:
        signature_type = signature_type_for(self._wallet_type)
        if signature_type == _POLY_1271_SIGNATURE_TYPE:
            return self._wallet
        return EvmAddress(self._signer.address)

    def _sign_quote_order(
        self,
        *,
        request: RfqQuoteRequestEvent,
        price_e6: int,
        size_e6: int,
        source: RfqQuoteSource,
    ) -> dict[str, object]:
        order_price = _quote_order_price(request, source, price_e6)
        side = _quote_order_side(source)
        unsigned = UnsignedOrder(
            builder=BYTES32_ZERO,
            chain_id=self._chain_id,
            exchange_address=self._exchange,
            expiration=0,
            maker=self._wallet,
            maker_amount=_maker_amount(side, order_price, size_e6),
            metadata=BYTES32_ZERO,
            order_type="GTC",
            salt=secrets.randbits(64),
            side=side,
            signature_type=signature_type_for(self._wallet_type),
            signer=self._order_signer_address(),
            taker_amount=_taker_amount(side, order_price, size_e6),
            timestamp=int(time.time()),
            token_id=TokenId(_quote_order_token_id(request, source)),
        )
        typed_data = build_order_typed_data(unsigned, protocol_version=_PROTOCOL_VERSION_V3)
        try:
            signed_message = self._signer.sign_typed_data(full_message=typed_data)
        except Exception as error:
            raise SigningError(f"Could not sign the RFQ quote order: {error}") from error
        raw_hex = signed_message.signature.hex()
        signature = HexString(raw_hex if raw_hex.startswith("0x") else "0x" + raw_hex)
        final_signature = build_order_signature(
            unsigned, signature, protocol_version=_PROTOCOL_VERSION_V3
        )
        return {
            "salt": str(unsigned.salt),
            "maker": unsigned.maker,
            "signer": unsigned.signer,
            "tokenId": unsigned.token_id,
            "makerAmount": str(unsigned.maker_amount),
            "takerAmount": str(unsigned.taker_amount),
            "side": 0 if unsigned.side == "BUY" else 1,
            "signatureType": unsigned.signature_type,
            "timestamp": str(unsigned.timestamp),
            "builder": unsigned.builder,
            "metadata": unsigned.metadata,
            "signature": final_signature,
        }

    def _on_message(self, raw: object) -> None:
        try:
            if not isinstance(raw, dict):
                raise UnexpectedResponseError("Invalid RFQ quoter message.")
            message = cast(dict[str, object], raw)
            message_type = _expect_str(message, "type")
            if message_type == "auth":
                self._handle_auth(message)
            elif message_type == "RFQ_REQUEST":
                self._push(_parse_quote_request(message, self))
            elif message_type == "ACK_RFQ_QUOTE":
                event = RfqQuoteReference(
                    rfq_id=_expect_str(message, "rfq_id"),
                    quote_id=_expect_str(message, "quote_id"),
                )
                self._resolve(_quote_ack_key(event.rfq_id), event)
            elif message_type == "ACK_RFQ_QUOTE_CANCEL":
                event = RfqCancelQuoteAck(
                    rfq_id=_expect_str(message, "rfq_id"),
                    quote_id=_expect_str(message, "quote_id"),
                )
                self._resolve(_quote_cancel_ack_key(event.rfq_id, event.quote_id), event)
            elif message_type == "RFQ_CONFIRMATION_REQUEST":
                self._push(_parse_confirmation_request(message, self))
            elif message_type == "ACK_RFQ_CONFIRMATION_RESPONSE":
                event = RfqConfirmationAck(
                    rfq_id=_expect_str(message, "rfq_id"),
                    quote_id=_expect_str(message, "quote_id"),
                )
                self._resolve(_confirmation_ack_key(event.rfq_id, event.quote_id), event)
            elif message_type == "RFQ_EXECUTION_UPDATE":
                tx_hash = message.get("tx_hash")
                self._push(
                    RfqExecutionUpdateEvent(
                        type="execution_update",
                        rfq_id=_expect_str(message, "rfq_id"),
                        status=RfqExecutionStatus(_expect_str(message, "status")),
                        tx_hash=TransactionHash(tx_hash) if isinstance(tx_hash, str) else None,
                    )
                )
            elif message_type == "RFQ_TRADE":
                self._push(_parse_trade(message))
            elif message_type == "RFQ_ERROR":
                self._handle_rfq_error(message)
        except BaseException as error:
            self._logger.warning("invalid RFQ quoter message: %r", error)
            self._fail(error)

    def _handle_auth(self, raw: dict[str, object]) -> None:
        if raw.get("success") is True:
            self._resolve("auth", None)
            return
        message = raw.get("error")
        self._reject("auth", TransportError(f"RFQ quoter authentication failed: {message}"))

    def _handle_rfq_error(self, raw: dict[str, object]) -> None:
        request_type = raw.get("request_type")
        rfq_id = raw.get("rfq_id")
        quote_id = raw.get("quote_id")
        code = _parse_error_code(raw.get("code"))
        message = raw.get("error")
        text = message if isinstance(message, str) else "RFQ request failed."
        if request_type == "RFQ_QUOTE":
            if not isinstance(rfq_id, str):
                raise TransportError("Uncorrelated RFQ quoter error.")
            self._reject(
                _quote_ack_key(rfq_id),
                RfqQuoteRejectedError(text, rfq_id=rfq_id, code=code),
            )
        elif request_type == "RFQ_QUOTE_CANCEL":
            if not isinstance(rfq_id, str) or not isinstance(quote_id, str):
                raise TransportError("Uncorrelated RFQ quoter error.")
            self._reject(
                _quote_cancel_ack_key(rfq_id, quote_id),
                RfqCancelQuoteRejectedError(
                    text,
                    rfq_id=rfq_id,
                    quote_id=quote_id,
                    code=code,
                ),
            )
        elif request_type == "RFQ_CONFIRMATION_RESPONSE":
            if not isinstance(rfq_id, str) or not isinstance(quote_id, str):
                raise TransportError("Uncorrelated RFQ quoter error.")
            self._reject(
                _confirmation_ack_key(rfq_id, quote_id),
                RfqConfirmationRejectedError(
                    text,
                    rfq_id=rfq_id,
                    quote_id=quote_id,
                    code=code,
                ),
            )

    def _on_close(self) -> None:
        if self._on_session_close is not None:
            self._on_session_close()
        if not self._closed:
            self._closed = True
            self._end(TransportError("RFQ quoter websocket closed."))

    def _on_error(self, exc: BaseException) -> None:
        self._logger.warning("RFQ quoter websocket error: %r", exc)

    async def _send(self, payload: object) -> None:
        if not await self._connection.send(payload):
            raise TransportError("RFQ quoter websocket is not open.")

    def _wait_for(self, key: str, message: str) -> asyncio.Future[Any]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        waiter = asyncio.ensure_future(_with_timeout(future, message))
        self._pending.setdefault(key, deque()).append(_PendingAck(future=future, waiter=waiter))
        waiter.add_done_callback(lambda done: self._remove_pending(key, done))
        return waiter

    def _remove_pending(self, key: str, pending: asyncio.Future[Any]) -> None:
        entries = self._pending.get(key)
        if entries is None:
            pending.cancel()
            return
        remaining = deque(entry for entry in entries if entry.waiter is not pending)
        if remaining:
            self._pending[key] = remaining
        else:
            self._pending.pop(key, None)
        pending.cancel()

    def _resolve(self, key: str, value: object) -> None:
        pending = self._pop_pending(key)
        if pending is not None:
            pending.future.set_result(value)

    def _reject(self, key: str, error: BaseException) -> None:
        pending = self._pop_pending(key)
        if pending is not None:
            pending.future.set_exception(error)

    def _pop_pending(self, key: str) -> _PendingAck | None:
        entries = self._pending.get(key)
        if entries is None:
            return None
        while entries:
            pending = entries.popleft()
            if pending.future.done() or pending.waiter.done():
                continue
            if not entries:
                self._pending.pop(key, None)
            return pending
        self._pending.pop(key, None)
        return None

    def _reject_all_pending(self, error: BaseException) -> None:
        for entries in tuple(self._pending.values()):
            for pending in tuple(entries):
                if not pending.future.done():
                    pending.future.set_exception(error)
        self._pending.clear()

    def _push(self, event: RfqEvent) -> None:
        if self._closed:
            return
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(event)

    def _fail(self, error: BaseException) -> None:
        if self._closed:
            return
        self._closed = True
        self._end(error)
        if self._on_session_close is not None:
            self._on_session_close()
        asyncio.create_task(self._connection.close())

    def _end(self, error: BaseException | None = None) -> None:
        if self._ended:
            return
        self._ended = True
        if error is not None:
            self._end_error = error
            self._reject_all_pending(error)
        try:
            self._queue.put_nowait(_END)
            return
        except asyncio.QueueFull:
            pass
        with contextlib.suppress(asyncio.QueueEmpty):
            self._queue.get_nowait()
        self._queue.put_nowait(_END)


async def _with_timeout(future: asyncio.Future[Any], message: str) -> object:
    try:
        return await asyncio.wait_for(future, timeout=_ACK_TIMEOUT_S)
    except TimeoutError as error:
        raise SDKTimeoutError(message) from error


def _parse_quote_request(raw: dict[str, object], session: RfqQuoterSession) -> RfqQuoteRequestEvent:
    return RfqQuoteRequestEvent(
        type="quote_request",
        rfq_id=_expect_str(raw, "rfq_id"),
        requestor_public_id=_expect_str(raw, "requestor_public_id"),
        leg_position_ids=tuple(
            PositionId(item) for item in _expect_str_list(raw, "leg_position_ids")
        ),
        condition_id=_expect_combo_condition_id(raw, "condition_id"),
        yes_position_id=PositionId(_expect_str(raw, "yes_position_id")),
        no_position_id=PositionId(_expect_str(raw, "no_position_id")),
        direction=RfqDirection(_expect_str(raw, "direction")),
        side=RfqSide(_expect_str(raw, "side")),
        requested_size=_parse_requested_size(_expect_dict(raw, "requested_size")),
        submission_deadline=_expect_int(raw, "submission_deadline"),
        _session=session,
    )


def _parse_confirmation_request(
    raw: dict[str, object], session: RfqQuoterSession
) -> RfqConfirmationRequestEvent:
    return RfqConfirmationRequestEvent(
        type="confirmation_request",
        rfq_id=_expect_str(raw, "rfq_id"),
        quote_id=_expect_str(raw, "quote_id"),
        signer_address=EvmAddress(_expect_str(raw, "signer_address")),
        maker_address=EvmAddress(_expect_str(raw, "maker_address")),
        signature_type=_expect_int(raw, "signature_type"),
        leg_position_ids=tuple(
            PositionId(item) for item in _expect_str_list(raw, "leg_position_ids")
        ),
        condition_id=_expect_combo_condition_id(raw, "condition_id"),
        yes_position_id=PositionId(_expect_str(raw, "yes_position_id")),
        no_position_id=PositionId(_expect_str(raw, "no_position_id")),
        direction=RfqDirection(_expect_str(raw, "direction")),
        side=RfqSide(_expect_str(raw, "side")),
        fill_size=_e6_to_decimal(_expect_str(raw, "fill_size_e6")),
        price=_e6_to_decimal(_expect_str(raw, "price_e6")),
        confirm_by=_expect_int(raw, "confirm_by"),
        _session=session,
    )


def _parse_trade(raw: dict[str, object]) -> RfqTradeEvent:
    return RfqTradeEvent(
        type="trade",
        rfq_id=_expect_str(raw, "rfq_id"),
        requestor_public_id=_expect_str(raw, "requestor_public_id"),
        condition_id=_expect_combo_condition_id(raw, "condition_id"),
        leg_position_ids=tuple(
            PositionId(item) for item in _expect_str_list(raw, "leg_position_ids")
        ),
        direction=RfqDirection(_expect_str(raw, "direction")),
        side=RfqSide(_expect_str(raw, "side")),
        price=_e6_to_decimal(_expect_str(raw, "price_e6")),
        size=_e6_to_decimal(_expect_str(raw, "size_e6")),
        tx_hash=TransactionHash(_expect_str(raw, "tx_hash")),
        executed_at=_expect_int(raw, "executed_at"),
    )


def _parse_requested_size(raw: dict[str, object]) -> RfqRequestedSize:
    return RfqRequestedSize(
        unit=RfqRequestedSizeUnit(_expect_str(raw, "unit")),
        value=_e6_to_decimal(_expect_str(raw, "value_e6")),
    )


def _decimal_to_e6(name: str, value: Decimal | int | float | str) -> int:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise UserInputError(f"{name} must be a valid decimal.") from error
    if decimal <= 0:
        raise UserInputError(f"{name} must be greater than 0.")
    scaled = decimal * _E6
    if scaled != scaled.to_integral_value():
        raise UserInputError(f"{name} must have at most 6 decimal places.")
    return int(scaled)


def _e6_to_decimal(value: str) -> Decimal:
    if not value.isdecimal():
        raise UnexpectedResponseError("RFQ decimal values must be unsigned base-unit strings.")
    return Decimal(value) / _E6


def _parse_quote_source(source: RfqQuoteSource | str) -> RfqQuoteSource:
    try:
        return source if isinstance(source, RfqQuoteSource) else RfqQuoteSource(source)
    except ValueError as error:
        raise UserInputError("source must be 'collateral' or 'inventory'.") from error


def _default_quote_size(requested_size: RfqRequestedSize, price_e6: int) -> int:
    value_e6 = _decimal_to_e6("requested_size", requested_size.value)
    if requested_size.unit == RfqRequestedSizeUnit.SHARES:
        return value_e6
    return (value_e6 * _E6) // price_e6


def _quote_order_token_id(request: RfqQuoteRequestEvent, source: RfqQuoteSource) -> PositionId:
    if request.direction == RfqDirection.BUY:
        if source == RfqQuoteSource.COLLATERAL:
            return request.no_position_id
        return request.yes_position_id
    if source == RfqQuoteSource.COLLATERAL:
        return request.yes_position_id
    return request.no_position_id


def _quote_order_price(request: RfqQuoteRequestEvent, source: RfqQuoteSource, price_e6: int) -> int:
    uses_complement = (
        request.direction == RfqDirection.BUY and source == RfqQuoteSource.COLLATERAL
    ) or (request.direction == RfqDirection.SELL and source == RfqQuoteSource.INVENTORY)
    return _E6 - price_e6 if uses_complement else price_e6


def _quote_order_side(source: RfqQuoteSource) -> OrderSide:
    return "BUY" if source == RfqQuoteSource.COLLATERAL else "SELL"


def _maker_amount(side: OrderSide, price_e6: int, size_e6: int) -> int:
    if side == "SELL":
        return size_e6
    return (price_e6 * size_e6 + _E6 - 1) // _E6


def _taker_amount(side: OrderSide, price_e6: int, size_e6: int) -> int:
    if side == "SELL":
        return (price_e6 * size_e6) // _E6
    return size_e6


def _quote_ack_key(rfq_id: RfqId) -> str:
    return f"ACK_RFQ_QUOTE:{rfq_id}"


def _quote_cancel_ack_key(rfq_id: RfqId, quote_id: RfqQuoteId) -> str:
    return f"ACK_RFQ_QUOTE_CANCEL:{rfq_id}:{quote_id}"


def _confirmation_ack_key(rfq_id: RfqId, quote_id: RfqQuoteId) -> str:
    return f"ACK_RFQ_CONFIRMATION_RESPONSE:{rfq_id}:{quote_id}"


def _expect_combo_condition_id(raw: dict[str, object], field: str) -> ComboConditionId:
    value = _expect_str(raw, field)
    try:
        return to_combo_condition_id(value)
    except TypeError as error:
        raise UnexpectedResponseError(str(error)) from error


def _expect_str(raw: dict[str, object], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value:
        raise UnexpectedResponseError(f"Expected RFQ {field} to be a non-empty string.")
    return value


def _expect_int(raw: dict[str, object], field: str) -> int:
    value = raw.get(field)
    if type(value) is not int:
        raise UnexpectedResponseError(f"Expected RFQ {field} to be an integer.")
    return value


def _expect_dict(raw: dict[str, object], field: str) -> dict[str, object]:
    value = raw.get(field)
    if not isinstance(value, dict):
        raise UnexpectedResponseError(f"Expected RFQ {field} to be an object.")
    return cast(dict[str, object], value)


def _expect_str_list(raw: dict[str, object], field: str) -> tuple[str, ...]:
    value = raw.get(field)
    if not isinstance(value, list):
        raise UnexpectedResponseError(f"Expected RFQ {field} to be a string list.")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise UnexpectedResponseError(f"Expected RFQ {field} to be a string list.")
    return tuple(cast(list[str], items))


def _parse_error_code(value: object) -> RfqErrorCode | None:
    if not isinstance(value, str):
        raise UnexpectedResponseError("Expected RFQ error code to be a string.")
    try:
        return RfqErrorCode(value)
    except ValueError as error:
        raise UnexpectedResponseError(f"Unknown RFQ error code: {value}") from error


__all__ = ["RfqQuoterSession", "RfqSessionContext"]
