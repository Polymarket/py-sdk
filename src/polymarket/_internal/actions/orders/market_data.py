from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from polymarket._internal.actions.orders.types import BYTES32_ZERO
from polymarket._internal.validation import require_nonempty, validate_builder_code
from polymarket.errors import RequestRejectedError, UnexpectedResponseError, UserInputError
from polymarket.models.clob.builder import BuilderFeeRates
from polymarket.models.types import (
    ClobAssetId,
    ConditionId,
    validate_condition_id,
)

if TYPE_CHECKING:
    from polymarket._internal.context import AsyncClientContext, SyncClientContext

_ALLOWED_TICK_SIZES: frozenset[Decimal] = frozenset(
    {
        Decimal("0.1"),
        Decimal("0.01"),
        Decimal("0.005"),
        Decimal("0.0025"),
        Decimal("0.001"),
        Decimal("0.0001"),
    }
)


@dataclass(frozen=True, slots=True)
class PlatformFeeInfo:
    rate: Decimal
    exponent: Decimal


@dataclass(frozen=True, slots=True)
class MarketInfo:
    fee_info: PlatformFeeInfo
    neg_risk: bool
    tick_size: Decimal
    token_ids: frozenset[ClobAssetId]

    @property
    def asset_ids(self) -> frozenset[ClobAssetId]:
        """Canonical alias for the CLOB market's assets."""

        return self.token_ids


async def fetch_tick_size(ctx: AsyncClientContext, *, token_id: str) -> Decimal:
    validated = require_nonempty("token_id", token_id)
    data = await ctx.clob.get_json("/tick-size", params={"token_id": validated})
    return _parse_tick_size(data)


def fetch_tick_size_sync(ctx: SyncClientContext, *, token_id: str) -> Decimal:
    validated = require_nonempty("token_id", token_id)
    data = ctx.clob.get_json("/tick-size", params={"token_id": validated})
    return _parse_tick_size(data)


async def fetch_neg_risk(ctx: AsyncClientContext, *, token_id: str) -> bool:
    validated = require_nonempty("token_id", token_id)
    data = await ctx.clob.get_json("/neg-risk", params={"token_id": validated})
    return _parse_neg_risk(data)


def fetch_neg_risk_sync(ctx: SyncClientContext, *, token_id: str) -> bool:
    validated = require_nonempty("token_id", token_id)
    data = ctx.clob.get_json("/neg-risk", params={"token_id": validated})
    return _parse_neg_risk(data)


async def resolve_condition_by_token(
    ctx: AsyncClientContext, *, token_id: ClobAssetId
) -> ConditionId:
    validated = require_nonempty("token_id", token_id)
    data = await ctx.clob.get_json(f"/markets-by-token/{validated}")
    return _parse_condition_by_token(data)


def resolve_condition_by_token_sync(
    ctx: SyncClientContext, *, token_id: ClobAssetId
) -> ConditionId:
    validated = require_nonempty("token_id", token_id)
    data = ctx.clob.get_json(f"/markets-by-token/{validated}")
    return _parse_condition_by_token(data)


async def fetch_platform_fee_info(
    ctx: AsyncClientContext, *, condition_id: ConditionId
) -> PlatformFeeInfo:
    validated = require_nonempty("condition_id", condition_id)
    try:
        validated = validate_condition_id(validated)
    except ValueError as error:
        raise UserInputError(str(error)) from error
    data = await ctx.clob.get_json(f"/clob-markets/{validated}")
    return _parse_platform_fee_info(data)


def fetch_platform_fee_info_sync(
    ctx: SyncClientContext, *, condition_id: ConditionId
) -> PlatformFeeInfo:
    validated = require_nonempty("condition_id", condition_id)
    try:
        validated = validate_condition_id(validated)
    except ValueError as error:
        raise UserInputError(str(error)) from error
    data = ctx.clob.get_json(f"/clob-markets/{validated}")
    return _parse_platform_fee_info(data)


async def fetch_market_info(ctx: AsyncClientContext, *, condition_id: ConditionId) -> MarketInfo:
    validated = _validate_condition_id(condition_id)
    data = await ctx.clob.get_json(f"/clob-markets/{validated}")
    return _parse_market_info(data)


def fetch_market_info_sync(ctx: SyncClientContext, *, condition_id: ConditionId) -> MarketInfo:
    validated = _validate_condition_id(condition_id)
    data = ctx.clob.get_json(f"/clob-markets/{validated}")
    return _parse_market_info(data)


async def fetch_builder_fee_rates(ctx: AsyncClientContext, *, builder_code: str) -> BuilderFeeRates:
    validated = validate_builder_code(builder_code)
    if validated == BYTES32_ZERO:
        raise UserInputError(
            "builder_code must be a real builder; zero (0x000…000) represents no attribution."
        )
    try:
        data = await ctx.clob.get_json(f"/fees/builder-fees/{validated}")
    except RequestRejectedError as error:
        if error.status == 404:
            raise UserInputError(f"Unknown builder code: {validated}") from error
        raise
    return BuilderFeeRates.parse_response(data)


def fetch_builder_fee_rates_sync(ctx: SyncClientContext, *, builder_code: str) -> BuilderFeeRates:
    validated = validate_builder_code(builder_code)
    if validated == BYTES32_ZERO:
        raise UserInputError(
            "builder_code must be a real builder; zero (0x000…000) represents no attribution."
        )
    try:
        data = ctx.clob.get_json(f"/fees/builder-fees/{validated}")
    except RequestRejectedError as error:
        if error.status == 404:
            raise UserInputError(f"Unknown builder code: {validated}") from error
        raise
    return BuilderFeeRates.parse_response(data)


def _parse_tick_size(data: object) -> Decimal:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("tick-size response did not match expected shape")
    raw = cast(dict[str, object], data).get("minimum_tick_size")
    return _parse_tick_size_value(raw, "tick-size 'minimum_tick_size'")


def _parse_tick_size_value(raw: object, field: str) -> Decimal:
    if isinstance(raw, bool):
        raise UnexpectedResponseError(f"{field} must be numeric, got bool {raw!r}")
    if isinstance(raw, int | float):
        value = Decimal(str(raw))
    elif isinstance(raw, str):
        try:
            value = Decimal(raw)
        except (ValueError, ArithmeticError) as error:
            raise UnexpectedResponseError(f"{field} is not a valid number: {raw!r}") from error
    else:
        raise UnexpectedResponseError(f"{field} must be numeric, got {type(raw).__name__}")
    if value not in _ALLOWED_TICK_SIZES:
        raise UnexpectedResponseError(f"Unsupported tick size received: {value}")
    return value


def _parse_neg_risk(data: object) -> bool:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("neg-risk response did not match expected shape")
    raw = cast(dict[str, object], data).get("neg_risk")
    if not isinstance(raw, bool):
        raise UnexpectedResponseError(
            f"neg-risk 'neg_risk' must be a bool, got {type(raw).__name__}"
        )
    return raw


def _parse_condition_by_token(data: object) -> ConditionId:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("markets-by-token response did not match expected shape")
    raw = cast(dict[str, object], data).get("condition_id")
    if not isinstance(raw, str) or not raw:
        raise UnexpectedResponseError("markets-by-token response missing or invalid 'condition_id'")
    try:
        return validate_condition_id(raw)
    except ValueError as error:
        raise UnexpectedResponseError(
            "markets-by-token response missing or invalid 'condition_id'"
        ) from error


def _parse_platform_fee_info(data: object) -> PlatformFeeInfo:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("clob-markets response did not match expected shape")
    payload = cast(dict[str, object], data)
    raw_fee = payload.get("fd")
    if raw_fee is None:
        return PlatformFeeInfo(rate=Decimal(0), exponent=Decimal(0))
    if not isinstance(raw_fee, dict):
        raise UnexpectedResponseError(
            f"clob-markets 'fd' must be an object, got {type(raw_fee).__name__}"
        )
    fee = cast(dict[str, object], raw_fee)
    return PlatformFeeInfo(
        rate=_coerce_decimal(fee.get("r"), "fd.r"),
        exponent=_coerce_decimal(fee.get("e"), "fd.e"),
    )


def _parse_market_info(data: object) -> MarketInfo:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("clob-markets response did not match expected shape")
    payload = cast(dict[str, object], data)
    raw_neg_risk = payload.get("nr", False)
    if not isinstance(raw_neg_risk, bool):
        raise UnexpectedResponseError(
            f"clob-markets 'nr' must be a bool, got {type(raw_neg_risk).__name__}"
        )
    raw_tokens = payload.get("t")
    if not isinstance(raw_tokens, list):
        raise UnexpectedResponseError(
            f"clob-markets 't' must be an array, got {type(raw_tokens).__name__}"
        )
    asset_ids: set[ClobAssetId] = set()
    for index, raw_token in enumerate(cast(list[object], raw_tokens)):
        if not isinstance(raw_token, dict):
            raise UnexpectedResponseError(f"clob-markets 't[{index}]' must be an object")
        raw_token_id = cast(dict[str, object], raw_token).get("t")
        if not isinstance(raw_token_id, str) or not raw_token_id:
            raise UnexpectedResponseError(f"clob-markets 't[{index}].t' must be a non-empty string")
        asset_ids.add(cast(ClobAssetId, raw_token_id))
    return MarketInfo(
        fee_info=_parse_platform_fee_info(payload),
        neg_risk=raw_neg_risk,
        tick_size=_parse_tick_size_value(payload.get("mts"), "clob-markets 'mts'"),
        token_ids=frozenset(asset_ids),
    )


def _validate_condition_id(condition_id: ConditionId) -> ConditionId:
    validated = require_nonempty("condition_id", condition_id)
    try:
        return validate_condition_id(validated)
    except ValueError as error:
        raise UserInputError(str(error)) from error


def _coerce_decimal(value: object, field: str) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        raise UnexpectedResponseError(f"{field} must be numeric, got bool")
    if isinstance(value, int | float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except (ValueError, ArithmeticError) as error:
            raise UnexpectedResponseError(f"{field} is not a valid number: {value!r}") from error
    raise UnexpectedResponseError(f"{field} must be numeric, got {type(value).__name__}")


__all__ = [
    "MarketInfo",
    "PlatformFeeInfo",
    "fetch_builder_fee_rates",
    "fetch_builder_fee_rates_sync",
    "fetch_neg_risk",
    "fetch_neg_risk_sync",
    "fetch_market_info",
    "fetch_market_info_sync",
    "fetch_platform_fee_info",
    "fetch_platform_fee_info_sync",
    "fetch_tick_size",
    "fetch_tick_size_sync",
    "resolve_condition_by_token",
    "resolve_condition_by_token_sync",
]
