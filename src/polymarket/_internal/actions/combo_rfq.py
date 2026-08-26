"""Requester-side combo RFQ actions over the builder gateway."""

from __future__ import annotations

import asyncio
import math
import re
import secrets
import time
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Literal, cast
from urllib.parse import quote as quote_path_segment

import httpx
from pydantic import ValidationError

from polymarket._internal.actions.orders.typed_data import (
    build_order_signature,
    build_order_typed_data,
)
from polymarket._internal.actions.orders.types import BYTES32_ZERO, UnsignedOrder
from polymarket._internal.context import AsyncSecureClientContext, SyncSecureClientContext
from polymarket._internal.wallet import signature_type_for
from polymarket.auth import BuilderApiKey
from polymarket.errors import (
    RequestRejectedError,
    SigningError,
    TimeoutError,
    TransportError,
    UnexpectedResponseError,
    UserInputError,
)
from polymarket.models.types import ComboConditionId, PositionId, TokenId, to_combo_condition_id
from polymarket.rfq import (
    ComboAcceptFailureReason,
    ComboFillResult,
    ComboQuote,
    ComboQuoteAcceptance,
    ComboQuoteResult,
    ComboQuoteUnavailableReason,
    RfqDirection,
    RfqErrorCode,
    RfqErrorDetail,
    RfqExecutionStatus,
    RfqRejectionCode,
    RfqRequestedSizeUnit,
    RfqRequestRejectedError,
    RfqSide,
    RfqStatus,
    RfqStatusResult,
)
from polymarket.types import EvmAddress, HexString, TransactionHash

_E6 = 1_000_000
_POLY_1271_SIGNATURE_TYPE = 3
_PROTOCOL_VERSION_V3 = "3"
_MIN_LEGS = 2
_MAX_LEGS = 50

_REQUESTS_PATH = "/v1/builder/rfq/requests"
_ACCEPT_OUTCOME_TIMEOUT_S = 30.0
_ACCEPT_OUTCOME_POLL_INTERVAL_S = 0.5
_DEFAULT_FILL_TIMEOUT_S = 30.0
_DEFAULT_FILL_POLL_INTERVAL_S = 1.0

# Create and accept are held through the quote competition and maker last
# look respectively, so allow generous read timeouts.
_HELD_REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

_MISSING_API_KEY_MESSAGE = (
    "Combo RFQ requests require a Builder API Key. Pass api_key= when constructing the client."
)

_SecureContext = AsyncSecureClientContext | SyncSecureClientContext


async def request_combo_quote(
    ctx: AsyncSecureClientContext,
    *,
    leg_position_ids: list[str] | tuple[str, ...],
    direction: RfqDirection | str,
    amount: Decimal | int | float | str | None = None,
    size: Decimal | int | float | str | None = None,
    side: RfqSide | str = RfqSide.YES,
) -> ComboQuoteResult:
    assert_combos_supported(ctx)
    _, body = build_combo_quote_request_body(
        ctx,
        leg_position_ids=leg_position_ids,
        direction=direction,
        amount=amount,
        size=size,
        side=side,
    )
    _require_builder_api_key(ctx)
    try:
        data = await ctx.builder_gateway.post_json(
            _REQUESTS_PATH, json=body, timeout=_HELD_REQUEST_TIMEOUT
        )
    except RequestRejectedError as error:
        raise _to_rfq_request_rejected(error) from error
    return _parse_combo_quote_result(data, request=body)


def request_combo_quote_sync(
    ctx: SyncSecureClientContext,
    *,
    leg_position_ids: list[str] | tuple[str, ...],
    direction: RfqDirection | str,
    amount: Decimal | int | float | str | None = None,
    size: Decimal | int | float | str | None = None,
    side: RfqSide | str = RfqSide.YES,
) -> ComboQuoteResult:
    assert_combos_supported(ctx)
    _, body = build_combo_quote_request_body(
        ctx,
        leg_position_ids=leg_position_ids,
        direction=direction,
        amount=amount,
        size=size,
        side=side,
    )
    _require_builder_api_key(ctx)
    try:
        data = ctx.builder_gateway.post_json(
            _REQUESTS_PATH, json=body, timeout=_HELD_REQUEST_TIMEOUT
        )
    except RequestRejectedError as error:
        raise _to_rfq_request_rejected(error) from error
    return _parse_combo_quote_result(data, request=body)


async def accept_combo_quote(
    ctx: AsyncSecureClientContext, quote: ComboQuote | Mapping[str, object]
) -> ComboQuoteAcceptance:
    assert_combos_supported(ctx)
    quote = _parse_combo_quote_input(quote)
    _require_builder_api_key(ctx)
    body = _build_accept_request_body(ctx, quote)
    path = f"{_REQUESTS_PATH}/{_encode_path_segment(quote.rfq_id)}/accept"
    try:
        try:
            data = await ctx.builder_gateway.post_json(
                path, json=body, timeout=_HELD_REQUEST_TIMEOUT
            )
            status = _parse_rfq_status(data, expected_rfq_id=quote.rfq_id)
        except (TransportError, UnexpectedResponseError):
            # Acceptance is idempotent server-side. Retry the same signed order
            # once when the request or response is interrupted during the maker
            # last-look hold.
            data = await ctx.builder_gateway.post_json(
                path, json=body, timeout=_HELD_REQUEST_TIMEOUT
            )
            status = _parse_rfq_status(data, expected_rfq_id=quote.rfq_id)
    except RequestRejectedError as error:
        expired = _to_expired_acceptance(quote.rfq_id, error)
        if expired is not None:
            return expired
        raise _to_rfq_request_rejected(error) from error

    # Only the accept response carries the taker order hash; status polls do
    # not, so capture it before entering the poll loop.
    taker_order_hash = status.taker_order_hash
    deadline = time.monotonic() + _ACCEPT_OUTCOME_TIMEOUT_S
    while status.status == RfqStatus.AWAITING_MAKER_CONFIRMATION:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out waiting for the acceptance outcome of RFQ {quote.rfq_id}."
            )
        await asyncio.sleep(_ACCEPT_OUTCOME_POLL_INTERVAL_S)
        status = await fetch_rfq_status(ctx, rfq_id=quote.rfq_id)
    return _to_acceptance(status, taker_order_hash=taker_order_hash)


def accept_combo_quote_sync(
    ctx: SyncSecureClientContext, quote: ComboQuote | Mapping[str, object]
) -> ComboQuoteAcceptance:
    assert_combos_supported(ctx)
    quote = _parse_combo_quote_input(quote)
    _require_builder_api_key(ctx)
    body = _build_accept_request_body(ctx, quote)
    path = f"{_REQUESTS_PATH}/{_encode_path_segment(quote.rfq_id)}/accept"
    try:
        try:
            data = ctx.builder_gateway.post_json(path, json=body, timeout=_HELD_REQUEST_TIMEOUT)
            status = _parse_rfq_status(data, expected_rfq_id=quote.rfq_id)
        except (TransportError, UnexpectedResponseError):
            # Acceptance is idempotent server-side. Retry the same signed order
            # once when the request or response is interrupted during the maker
            # last-look hold.
            data = ctx.builder_gateway.post_json(path, json=body, timeout=_HELD_REQUEST_TIMEOUT)
            status = _parse_rfq_status(data, expected_rfq_id=quote.rfq_id)
    except RequestRejectedError as error:
        expired = _to_expired_acceptance(quote.rfq_id, error)
        if expired is not None:
            return expired
        raise _to_rfq_request_rejected(error) from error

    # Only the accept response carries the taker order hash; status polls do
    # not, so capture it before entering the poll loop.
    taker_order_hash = status.taker_order_hash
    deadline = time.monotonic() + _ACCEPT_OUTCOME_TIMEOUT_S
    while status.status == RfqStatus.AWAITING_MAKER_CONFIRMATION:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out waiting for the acceptance outcome of RFQ {quote.rfq_id}."
            )
        time.sleep(_ACCEPT_OUTCOME_POLL_INTERVAL_S)
        status = fetch_rfq_status_sync(ctx, rfq_id=quote.rfq_id)
    return _to_acceptance(status, taker_order_hash=taker_order_hash)


async def wait_for_combo_fill(
    ctx: AsyncSecureClientContext,
    *,
    rfq_id: str,
    timeout: float = _DEFAULT_FILL_TIMEOUT_S,
    polling_interval: float = _DEFAULT_FILL_POLL_INTERVAL_S,
) -> ComboFillResult:
    assert_combos_supported(ctx)
    _validate_wait_params(timeout=timeout, polling_interval=polling_interval)
    deadline = time.monotonic() + timeout
    while True:
        status = await fetch_rfq_status(ctx, rfq_id=rfq_id)
        result = _to_fill_result(status)
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out after {timeout}s waiting for RFQ {rfq_id} to reach a terminal state."
            )
        await asyncio.sleep(polling_interval)


def wait_for_combo_fill_sync(
    ctx: SyncSecureClientContext,
    *,
    rfq_id: str,
    timeout: float = _DEFAULT_FILL_TIMEOUT_S,
    polling_interval: float = _DEFAULT_FILL_POLL_INTERVAL_S,
) -> ComboFillResult:
    assert_combos_supported(ctx)
    _validate_wait_params(timeout=timeout, polling_interval=polling_interval)
    deadline = time.monotonic() + timeout
    while True:
        status = fetch_rfq_status_sync(ctx, rfq_id=rfq_id)
        result = _to_fill_result(status)
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out after {timeout}s waiting for RFQ {rfq_id} to reach a terminal state."
            )
        time.sleep(polling_interval)


async def fetch_rfq_status(ctx: AsyncSecureClientContext, *, rfq_id: str) -> RfqStatusResult:
    assert_combos_supported(ctx)
    _require_rfq_id(rfq_id)
    try:
        data = await ctx.builder_gateway.get_json(
            f"{_REQUESTS_PATH}/{_encode_path_segment(rfq_id)}"
        )
    except RequestRejectedError as error:
        raise _to_rfq_request_rejected(error) from error
    return _parse_rfq_status(data, expected_rfq_id=rfq_id)


def fetch_rfq_status_sync(ctx: SyncSecureClientContext, *, rfq_id: str) -> RfqStatusResult:
    assert_combos_supported(ctx)
    _require_rfq_id(rfq_id)
    try:
        data = ctx.builder_gateway.get_json(f"{_REQUESTS_PATH}/{_encode_path_segment(rfq_id)}")
    except RequestRejectedError as error:
        raise _to_rfq_request_rejected(error) from error
    return _parse_rfq_status(data, expected_rfq_id=rfq_id)


def build_combo_quote_request_body(
    ctx: _SecureContext,
    *,
    leg_position_ids: list[str] | tuple[str, ...],
    direction: RfqDirection | str,
    amount: Decimal | int | float | str | None,
    size: Decimal | int | float | str | None,
    side: RfqSide | str,
) -> tuple[RfqDirection, dict[str, object]]:
    parsed_direction = _parse_direction(direction)
    parsed_side = _parse_side(side)
    legs = _validate_legs(leg_position_ids)

    if parsed_direction is RfqDirection.BUY:
        if amount is None:
            raise UserInputError("BUY combo quote requests are sized in collateral; pass amount=.")
        if size is not None:
            raise UserInputError("BUY combo quote requests take amount=, not size=.")
        requested = {"unit": "notional", "value_e6": str(_decimal_to_e6("amount", amount))}
    else:
        if size is None:
            raise UserInputError(
                "SELL combo quote requests are sized in outcome tokens; pass size=."
            )
        if amount is not None:
            raise UserInputError("SELL combo quote requests take size=, not amount=.")
        requested = {"unit": "shares", "value_e6": str(_decimal_to_e6("size", size))}

    body: dict[str, object] = {
        "signer_address": _order_signer_address(ctx),
        "maker_address": ctx.wallet,
        "signature_type": signature_type_for(ctx.wallet_type),
        "leg_position_ids": legs,
        "direction": parsed_direction.value,
        "side": parsed_side.value,
        "requested_size": requested,
    }
    return parsed_direction, body


def _build_accept_request_body(ctx: _SecureContext, quote: ComboQuote) -> dict[str, object]:
    _require_rfq_id(quote.rfq_id)
    if not quote.quote_id:
        raise UserInputError("quote.quote_id must be a non-empty string.")
    direction = _parse_direction(quote.direction)
    position_id = _validate_position_id("quote.position_id", quote.position_id)
    builder_code = _validate_builder_code(quote.builder_code)
    if quote.expires_at < 0:
        raise UserInputError("quote.expires_at must be non-negative.")

    signed_order = _sign_acceptance_order(
        ctx,
        direction=direction,
        position_id=position_id,
        builder_code=builder_code,
        maker_amount_e6=_decimal_to_e6("quote.maker_amount", quote.maker_amount),
        taker_amount_e6=_decimal_to_e6("quote.taker_amount", quote.taker_amount),
    )
    return {
        "quote_id": quote.quote_id,
        "signed_order": signed_order,
    }


def _sign_acceptance_order(
    ctx: _SecureContext,
    *,
    direction: RfqDirection,
    position_id: PositionId,
    builder_code: HexString,
    maker_amount_e6: int,
    taker_amount_e6: int,
) -> dict[str, object]:
    unsigned = UnsignedOrder(
        builder=builder_code,
        chain_id=ctx.environment_config.chain_id,
        exchange_address=EvmAddress(ctx.environment_config.exchange_v3),
        expiration=0,
        maker=ctx.wallet,
        maker_amount=maker_amount_e6,
        metadata=BYTES32_ZERO,
        order_type="GTC",
        salt=secrets.randbits(64),
        side="BUY" if direction is RfqDirection.BUY else "SELL",
        signature_type=signature_type_for(ctx.wallet_type),
        signer=_order_signer_address(ctx),
        taker_amount=taker_amount_e6,
        timestamp=int(time.time()),
        token_id=TokenId(position_id),
    )
    typed_data = build_order_typed_data(unsigned, protocol_version=_PROTOCOL_VERSION_V3)
    try:
        signed_message = ctx.signer.sign_typed_data(full_message=typed_data)
    except Exception as error:
        raise SigningError(f"Could not sign the combo quote acceptance order: {error}") from error
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


def _order_signer_address(ctx: _SecureContext) -> EvmAddress:
    if signature_type_for(ctx.wallet_type) == _POLY_1271_SIGNATURE_TYPE:
        return ctx.wallet
    return EvmAddress(ctx.signer.address)


def _require_builder_api_key(ctx: _SecureContext) -> None:
    if not isinstance(ctx.api_key, BuilderApiKey):
        raise UserInputError(_MISSING_API_KEY_MESSAGE)


def _require_rfq_id(rfq_id: str) -> None:
    if not rfq_id:
        raise UserInputError("rfq_id must be a non-empty string.")


def _parse_combo_quote_input(quote: ComboQuote | Mapping[str, object]) -> ComboQuote:
    try:
        return ComboQuote.model_validate(quote)
    except ValidationError as error:
        raise UserInputError("quote must be a valid self-contained combo quote.") from error


def _validate_wait_params(*, timeout: float, polling_interval: float) -> None:
    _validate_positive_finite_number("timeout", timeout)
    _validate_positive_finite_number("polling_interval", polling_interval)


def _validate_positive_finite_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise UserInputError(f"{name} must be a finite number greater than 0.")
    if value <= 0:
        raise UserInputError(f"{name} must be a finite number greater than 0.")


def _parse_direction(direction: RfqDirection | str) -> RfqDirection:
    try:
        return direction if isinstance(direction, RfqDirection) else RfqDirection(direction)
    except ValueError as error:
        raise UserInputError("direction must be 'BUY' or 'SELL'.") from error


def _parse_side(side: RfqSide | str) -> RfqSide:
    try:
        return side if isinstance(side, RfqSide) else RfqSide(side)
    except ValueError as error:
        raise UserInputError("side must be 'YES'.") from error


def _validate_legs(leg_position_ids: list[str] | tuple[str, ...]) -> list[str]:
    raw_legs = [str(leg) for leg in leg_position_ids]
    if len(raw_legs) < _MIN_LEGS or len(raw_legs) > _MAX_LEGS:
        raise UserInputError(
            f"leg_position_ids must include {_MIN_LEGS} to {_MAX_LEGS} position IDs."
        )
    if any(not leg.isdecimal() for leg in raw_legs):
        raise UserInputError("leg_position_ids must be numeric position ID strings.")
    legs = [str(int(leg)) for leg in raw_legs]
    if len(set(legs)) != len(legs):
        raise UserInputError("leg_position_ids must not contain duplicates.")
    return sorted(legs, key=int)


def _validate_position_id(name: str, value: object) -> PositionId:
    raw = str(value)
    if not raw.isdecimal():
        raise UserInputError(f"{name} must be a numeric position ID string.")
    return PositionId(str(int(raw)))


def _validate_builder_code(value: object) -> HexString:
    raw = str(value)
    if re.fullmatch(r"0x[0-9a-fA-F]{64}", raw) is None:
        raise UserInputError("quote.builder_code must be a 32-byte hex string.")
    return HexString(raw)


def _decimal_to_e6(name: str, value: Decimal | int | float | str) -> int:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise UserInputError(f"{name} must be a valid decimal.") from error
    if not decimal.is_finite():
        raise UserInputError(f"{name} must be a valid decimal.")
    if decimal <= 0:
        raise UserInputError(f"{name} must be greater than 0.")
    scaled = decimal * _E6
    if scaled != scaled.to_integral_value():
        raise UserInputError(f"{name} must have at most 6 decimal places.")
    return int(scaled)


def _e6_to_decimal(value: object) -> Decimal:
    if not isinstance(value, str) or not value.isdecimal():
        raise UnexpectedResponseError("RFQ decimal values must be unsigned base-unit strings.")
    return Decimal(value) / _E6


def _encode_path_segment(value: str) -> str:
    return quote_path_segment(value, safe="")


def _to_rfq_request_rejected(error: RequestRejectedError) -> RfqRequestRejectedError:
    return RfqRequestRejectedError(
        str(error),
        status=error.status,
        code=_parse_rejection_code(error.code),
        retry_after=error.retry_after,
    )


def _parse_rejection_code(code: str | None) -> RfqRejectionCode | str | None:
    if code is None:
        return None
    try:
        return RfqRejectionCode(code)
    except ValueError:
        return code


def _to_expired_acceptance(rfq_id: str, error: RequestRejectedError) -> ComboQuoteAcceptance | None:
    if error.code != RfqErrorCode.EXPIRED_RFQ:
        return None
    return ComboQuoteAcceptance(
        rfq_id=rfq_id,
        status="failed",
        reason=ComboAcceptFailureReason.ACCEPTANCE_WINDOW_EXPIRED,
        error=RfqErrorDetail(code=RfqErrorCode.EXPIRED_RFQ, message=str(error)),
    )


def _to_acceptance(
    status: RfqStatusResult, *, taker_order_hash: HexString | None
) -> ComboQuoteAcceptance:
    if status.status in (RfqStatus.FAILED, RfqStatus.EXPIRED, RfqStatus.CANCELED):
        return ComboQuoteAcceptance(
            rfq_id=status.rfq_id,
            status="failed",
            reason=_to_accept_failure_reason(status),
            error=status.error,
        )
    return ComboQuoteAcceptance(
        rfq_id=status.rfq_id,
        status="executing",
        taker_order_hash=taker_order_hash,
    )


def _to_accept_failure_reason(status: RfqStatusResult) -> ComboAcceptFailureReason:
    code = status.error.code if status.error is not None else None
    if status.status == RfqStatus.EXPIRED or code == RfqErrorCode.EXPIRED_RFQ:
        return ComboAcceptFailureReason.ACCEPTANCE_WINDOW_EXPIRED
    if code == RfqErrorCode.MAKER_DECLINED:
        return ComboAcceptFailureReason.MAKER_DECLINED
    return ComboAcceptFailureReason.EXECUTION_FAILED


def _to_fill_result(status: RfqStatusResult) -> ComboFillResult | None:
    if status.status in (RfqStatus.FILLED, RfqExecutionStatus.CONFIRMED):
        if status.tx_hash is None:
            raise UnexpectedResponseError(
                f"RFQ {status.rfq_id} reached {status.status} without a transaction hash."
            )
        return ComboFillResult(
            rfq_id=status.rfq_id, status=RfqStatus.FILLED, tx_hash=status.tx_hash
        )
    if status.status in (RfqStatus.FAILED, RfqStatus.EXPIRED, RfqStatus.CANCELED):
        return ComboFillResult(
            rfq_id=status.rfq_id,
            status=cast(
                Literal[RfqStatus.FAILED, RfqStatus.EXPIRED, RfqStatus.CANCELED],
                status.status,
            ),
            error=status.error,
        )
    return None


def _parse_combo_quote_result(data: object, *, request: Mapping[str, object]) -> ComboQuoteResult:
    payload = _expect_object(data)
    rfq_id = _expect_str(payload, "rfq_id")
    status = _parse_status(_expect_str(payload, "status"))
    quote_payload = payload.get("quote")
    if quote_payload is None and status not in (
        RfqStatus.FAILED,
        RfqStatus.EXPIRED,
        RfqStatus.CANCELED,
    ):
        raise UnexpectedResponseError(
            f"RFQ {rfq_id} response reported status {status} without a quote."
        )
    if quote_payload is not None:
        if status is not RfqStatus.AWAITING_REQUESTER_ACCEPTANCE:
            raise UnexpectedResponseError(
                f"RFQ {rfq_id} response included a quote while reporting status {status}."
            )
        request_payload = _expect_object(payload.get("request"))
        quote_object = _expect_object(quote_payload)
        direction = _validate_quote_response_request(
            request_payload,
            expected_rfq_id=rfq_id,
            submitted=request,
        )
        _parse_condition_id(_expect_str(request_payload, "condition_id"))
        _parse_response_position_id(_expect_str(request_payload, "no_position_id"))
        net_receive: Decimal | None = None
        if "net_receive_e6" in quote_object:
            parsed_net_receive = _e6_to_decimal(quote_object.get("net_receive_e6"))
            if direction is RfqDirection.SELL:
                net_receive = parsed_net_receive
        elif direction is RfqDirection.SELL:
            raise UnexpectedResponseError(f"SELL quote for RFQ {rfq_id} omitted net sell proceeds.")
        quote = ComboQuote(
            rfq_id=rfq_id,
            quote_id=_expect_str(quote_object, "quote_id"),
            builder_code=_parse_builder_code(_expect_str(payload, "builder_code")),
            direction=direction,
            position_id=_parse_response_position_id(
                _expect_str(request_payload, "yes_position_id")
            ),
            blended_price=_e6_to_decimal(quote_object.get("blended_price_e6")),
            maker_amount=_e6_to_decimal(quote_object.get("maker_amount_e6")),
            taker_amount=_e6_to_decimal(quote_object.get("taker_amount_e6")),
            total_required=_e6_to_decimal(quote_object.get("total_required_e6")),
            net_receive=net_receive,
            expires_at=_expect_int(payload, "expires_at"),
        )
        return ComboQuoteResult(
            rfq_id=rfq_id,
            quote=quote,
        )

    reason = _parse_quote_unavailable_reason(payload)
    return ComboQuoteResult(rfq_id=rfq_id, quote=None, reason=reason)


def _validate_quote_response_request(
    payload: dict[str, object],
    *,
    expected_rfq_id: str,
    submitted: Mapping[str, object],
) -> RfqDirection:
    echoed_rfq_id = _expect_str(payload, "rfq_id")
    echoed_direction = _parse_response_direction(_expect_str(payload, "direction"))
    echoed_side = _parse_response_side(_expect_str(payload, "side"))
    echoed_legs = _expect_position_id_list(payload, "leg_position_ids")
    echoed_size = _expect_object(payload.get("requested_size"))
    echoed_size_unit = _parse_response_requested_size_unit(_expect_str(echoed_size, "unit"))
    echoed_size_e6 = _parse_response_base_units(_expect_str(echoed_size, "value_e6"))

    submitted_legs = cast(list[str], submitted["leg_position_ids"])
    submitted_size = cast(dict[str, object], submitted["requested_size"])
    mismatched_fields: list[str] = []
    if echoed_rfq_id != expected_rfq_id:
        mismatched_fields.append("rfq_id")
    if echoed_direction.value != submitted["direction"]:
        mismatched_fields.append("direction")
    if echoed_side.value != submitted["side"]:
        mismatched_fields.append("side")
    if echoed_legs != tuple(submitted_legs):
        mismatched_fields.append("leg_position_ids")
    if (
        echoed_size_unit.value != submitted_size["unit"]
        or echoed_size_e6 != submitted_size["value_e6"]
    ):
        mismatched_fields.append("requested_size")

    if mismatched_fields:
        raise UnexpectedResponseError(
            "Builder RFQ response did not echo the submitted " + ", ".join(mismatched_fields) + "."
        )
    return echoed_direction


def _parse_quote_unavailable_reason(payload: dict[str, object]) -> ComboQuoteUnavailableReason:
    error = payload.get("error")
    code = _expect_str(_expect_object(error), "code") if error is not None else None
    message = _expect_str(_expect_object(error), "message") if error is not None else None
    try:
        if code is not None:
            return ComboQuoteUnavailableReason(code)
    except ValueError:
        pass
    raise RfqRequestRejectedError(
        message or "The combo quote request failed.",
        status=200,
        code=_parse_rejection_code(code),
    )


def _parse_rfq_status(data: object, *, expected_rfq_id: str) -> RfqStatusResult:
    payload = _expect_object(data)
    rfq_id = _expect_matching_rfq_id(payload, expected_rfq_id=expected_rfq_id)
    error_payload = payload.get("error")
    error: RfqErrorDetail | None = None
    if error_payload is not None:
        error_object = _expect_object(error_payload)
        error = RfqErrorDetail(
            code=_parse_error_code(_expect_str(error_object, "code")),
            message=_expect_str(error_object, "message"),
        )
    tx_hash = _expect_optional_str(payload, "tx_hash")
    taker_order_hash = _expect_optional_str(payload, "taker_order_hash")
    return RfqStatusResult(
        rfq_id=rfq_id,
        status=_parse_status(_expect_str(payload, "status")),
        taker_order_hash=HexString(taker_order_hash) if taker_order_hash is not None else None,
        tx_hash=TransactionHash(tx_hash) if tx_hash is not None else None,
        error=error,
    )


def _expect_matching_rfq_id(payload: dict[str, object], *, expected_rfq_id: str) -> str:
    rfq_id = _expect_str(payload, "rfq_id")
    if rfq_id != expected_rfq_id:
        raise UnexpectedResponseError(
            f"RFQ response ID {rfq_id!r} did not match requested ID {expected_rfq_id!r}."
        )
    return rfq_id


def _expect_optional_str(payload: dict[str, object], key: str) -> str | None:
    if key not in payload:
        return None
    return _expect_str(payload, key)


def _parse_status(value: str) -> RfqStatus | RfqExecutionStatus:
    try:
        return RfqStatus(value)
    except ValueError:
        pass
    try:
        return RfqExecutionStatus(value)
    except ValueError as error:
        raise UnexpectedResponseError(f"Unknown RFQ status: {value}") from error


def _parse_error_code(value: str) -> RfqErrorCode | str:
    # Error codes evolve independently of released clients; unknown codes
    # flow through as plain strings.
    try:
        return RfqErrorCode(value)
    except ValueError:
        return value


def _parse_response_direction(value: str) -> RfqDirection:
    try:
        return RfqDirection(value)
    except ValueError as error:
        raise UnexpectedResponseError(f"Invalid RFQ direction: {value}") from error


def _parse_response_side(value: str) -> RfqSide:
    try:
        return RfqSide(value)
    except ValueError as error:
        raise UnexpectedResponseError(f"Invalid RFQ side: {value}") from error


def _parse_response_requested_size_unit(value: str) -> RfqRequestedSizeUnit:
    try:
        return RfqRequestedSizeUnit(value)
    except ValueError as error:
        raise UnexpectedResponseError(f"Invalid RFQ requested-size unit: {value}") from error


def _parse_response_base_units(value: str) -> str:
    if not value.isdecimal():
        raise UnexpectedResponseError(f"Invalid RFQ requested-size value: {value}")
    return str(int(value))


def _parse_condition_id(value: str) -> ComboConditionId:
    try:
        return to_combo_condition_id(value)
    except TypeError as error:
        raise UnexpectedResponseError(f"Invalid combo condition ID: {value}") from error


def _parse_response_position_id(value: str) -> PositionId:
    if not value.isdecimal():
        raise UnexpectedResponseError(f"Invalid combo position ID: {value}")
    return PositionId(str(int(value)))


def _parse_builder_code(value: str) -> HexString:
    if re.fullmatch(r"0x[0-9a-fA-F]{64}", value) is None:
        raise UnexpectedResponseError(f"Invalid combo builder code: {value}")
    return HexString(value)


def _expect_position_id_list(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise UnexpectedResponseError(f"RFQ response is missing a valid '{key}' field.")
    items = cast(list[object], value)
    if any(not isinstance(item, str) for item in items):
        raise UnexpectedResponseError(f"RFQ response is missing a valid '{key}' field.")
    position_ids = cast(list[str], items)
    for position_id in position_ids:
        _parse_response_position_id(position_id)
    return tuple(position_ids)


def _expect_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise UnexpectedResponseError("RFQ response did not match expected shape.")
    return cast(dict[str, object], value)


def _expect_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise UnexpectedResponseError(f"RFQ response is missing a valid '{key}' field.")
    return value


def _expect_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise UnexpectedResponseError(f"RFQ response is missing a valid '{key}' field.")
    return value


def assert_combos_supported(ctx: _SecureContext) -> None:
    if ctx.signer_type == "SESSION_KEY":
        raise UserInputError("Combos is not supported with Session Keys")


__all__ = [
    "accept_combo_quote",
    "accept_combo_quote_sync",
    "assert_combos_supported",
    "build_combo_quote_request_body",
    "fetch_rfq_status",
    "fetch_rfq_status_sync",
    "request_combo_quote",
    "request_combo_quote_sync",
    "wait_for_combo_fill",
    "wait_for_combo_fill_sync",
]
