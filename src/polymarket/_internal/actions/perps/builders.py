"""Perps builder validation, reporting, and owner consent."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from eth_account.signers.local import LocalAccount
from eth_utils.address import is_address

from polymarket._internal.actions.perps.paging import as_json_dict, to_epoch_ms
from polymarket._internal.actions.perps.signing import now_ms, random_perps_salt, sign_perps_op
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.perps._validators import _require_builder_fee_rate
from polymarket.models.perps.builders import (
    PerpsBuilderApproval,
    PerpsBuilderAttribution,
    PerpsBuilderEarning,
    PerpsBuilderEarningsPage,
    PerpsBuilderEarningsPaginator,
    PerpsBuilderEarningsSnapshot,
    PerpsBuilderEarningsSummary,
    PerpsBuilderStatus,
)


def validate_attribution(value: object) -> PerpsBuilderAttribution | None:
    if value is not None and not isinstance(value, PerpsBuilderAttribution):
        raise UserInputError("builder_attribution must be a PerpsBuilderAttribution or None")
    return value


def validate_address(name: str, value: object) -> str:
    if not isinstance(value, str) or not is_address(value):
        raise UserInputError(f"{name} must be an EVM address")
    return value


def validate_fee_rate(value: Decimal | str) -> str:
    try:
        rate = _require_builder_fee_rate(Decimal(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise UserInputError(
            "max_fee_rate must be a non-negative decimal with at most 28 decimal places"
        ) from error
    return format(rate, "f")


async def fetch_status(api: AsyncTransport, *, address: str) -> PerpsBuilderStatus:
    address = validate_address("address", address)
    return PerpsBuilderStatus.parse_response(
        await api.get_json("/v1/info/builder", params={"address": address})
    )


async def fetch_approvals(
    api: AsyncTransport, *, builder: str | None = None
) -> tuple[PerpsBuilderApproval, ...]:
    if builder is not None:
        validate_address("builder", builder)
    data = as_json_dict(
        await api.get_json("/v1/account/builder-approvals", params={"builder": builder})
    )
    if data is None:
        raise UnexpectedResponseError("Invalid builder approvals response")
    return PerpsBuilderApproval.parse_response_list(data.get("data"))


async def approve_fee(
    api: AsyncTransport,
    *,
    signer: LocalAccount,
    chain_id: int,
    builder: str,
    max_fee_rate: str,
    approval_version: int,
) -> PerpsBuilderApproval:
    salt, timestamp = random_perps_salt(), now_ms()
    op = ["approveBuilder", [builder, max_fee_rate, approval_version]]
    signature = sign_perps_op(signer, chain_id=chain_id, op=op, salt=salt, timestamp_ms=timestamp)
    data = await api.post_json(
        "/v1/account/builder-approvals",
        json={
            "op": {
                "type": "approveBuilder",
                "args": {
                    "builder": builder,
                    "max_fee_rate": max_fee_rate,
                    "approval_version": approval_version,
                },
            },
            "salt": salt,
            "sig": signature,
            "ts": timestamp,
        },
    )
    return PerpsBuilderApproval.parse_response(data)


def build_builder_reporting_params(
    *, start: datetime | int | None, end: datetime | int | None, as_of_sequence: int | None
) -> dict[str, Any]:
    start_ms, end_ms = to_epoch_ms("start", start), to_epoch_ms("end", end)
    if start_ms is not None and end_ms is not None and not 0 <= end_ms - start_ms <= 90 * 86400000:
        raise UserInputError("Reporting window must be ordered and at most 90 days")
    if as_of_sequence is not None and (
        isinstance(as_of_sequence, bool) or type(as_of_sequence) is not int or as_of_sequence < 0
    ):
        raise UserInputError("as_of_sequence must be a non-negative integer")
    return {"start_timestamp": start_ms, "end_timestamp": end_ms, "as_of_sequence": as_of_sequence}


def list_earnings(
    api: AsyncTransport,
    *,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
    as_of_sequence: int | None = None,
) -> PerpsBuilderEarningsPaginator:
    params = build_builder_reporting_params(start=start, end=end, as_of_sequence=as_of_sequence)

    async def fetch(cursor: str | None) -> PerpsBuilderEarningsPage:
        data = as_json_dict(
            await api.get_json(
                "/v1/account/builder-earnings",
                params=params if cursor is None else {"cursor": cursor},
            )
        )
        if data is None or not isinstance(data.get("more"), bool):
            raise UnexpectedResponseError("Invalid builder earnings response")
        next_cursor = data.get("cursor")
        if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor):
            raise UnexpectedResponseError("Invalid builder earnings cursor")
        if data["more"] and (not next_cursor or next_cursor == cursor):
            raise UnexpectedResponseError("Builder earnings require a new continuation cursor")
        return PerpsBuilderEarningsPage(
            items=PerpsBuilderEarning.parse_response_list(data.get("data")),
            has_more=data["more"],
            next_cursor=next_cursor,
            snapshot=PerpsBuilderEarningsSnapshot.parse_response(data),
        )

    return PerpsBuilderEarningsPaginator(fetch)


async def fetch_summary(
    api: AsyncTransport,
    *,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
    as_of_sequence: int | None = None,
) -> PerpsBuilderEarningsSummary:
    params = build_builder_reporting_params(start=start, end=end, as_of_sequence=as_of_sequence)
    return PerpsBuilderEarningsSummary.parse_response(
        await api.get_json("/v1/account/builder-earnings-summary", params=params)
    )
