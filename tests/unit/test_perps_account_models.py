"""Perps account and funds model validation contracts."""

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import get_type_hints

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.perps.account import (
    PerpsAccountStats,
    PerpsBalance,
    PerpsEquityPoint,
    PerpsFundingPayment,
    PerpsMarginSummary,
    PerpsPnlPoint,
    PerpsPortfolio,
    PerpsPosition,
    PerpsProxyKey,
)
from polymarket.models.perps.funds import (
    PerpsDeposit,
    PerpsDepositUpdate,
    PerpsWithdrawal,
    PerpsWithdrawalUpdate,
)

_EPOCH_MS = 1_747_660_800_123
_TIMESTAMP = datetime(2025, 5, 19, 13, 20, 0, 123000, tzinfo=UTC)


def test_account_and_funds_annotations_expose_canonical_types_with_extras() -> None:
    expected_fields = {
        PerpsBalance: {"balance": Decimal, "value": Decimal},
        PerpsAccountStats: {
            "volume_7d": Decimal,
            "taker_volume_7d": Decimal,
            "maker_volume_7d": Decimal,
            "account_maker_share_7d": Decimal,
            "entity_maker_share_7d": Decimal | None,
        },
        PerpsPosition: {
            "size": Decimal,
            "entry_price": Decimal,
            "initial_margin": Decimal,
            "maintenance_margin": Decimal,
            "position_value": Decimal,
            "liquidation_price": Decimal,
            "unrealized_pnl": Decimal,
            "return_on_equity": Decimal,
            "cumulative_funding": Decimal,
        },
        PerpsMarginSummary: {
            "total_account_value": Decimal,
            "total_initial_margin": Decimal,
            "total_maintenance_margin": Decimal,
            "total_position_value": Decimal,
        },
        PerpsPortfolio: {"withdrawable": Decimal, "timestamp": datetime},
        PerpsFundingPayment: {
            "size": Decimal,
            "funding_rate": Decimal,
            "funding": Decimal,
            "timestamp": datetime,
        },
        PerpsEquityPoint: {"timestamp": datetime, "equity": Decimal},
        PerpsPnlPoint: {"timestamp": datetime, "pnl": Decimal},
        PerpsProxyKey: {"expires_at": datetime},
        PerpsDeposit: {
            "amount": Decimal,
            "created_at": datetime,
            "confirmed_at": datetime | None,
        },
        PerpsDepositUpdate: {"hash": str | None, "amount": Decimal},
        PerpsWithdrawal: {
            "amount": Decimal,
            "fee": Decimal,
            "hash": str | None,
            "created_at": datetime,
            "confirmed_at": datetime | None,
        },
        PerpsWithdrawalUpdate: {
            "amount": Decimal,
            "fee": Decimal,
            "hash": str | None,
        },
    }

    for model, expected in expected_fields.items():
        hints = get_type_hints(model, include_extras=True)
        assert {field: hints[field] for field in expected} == expected


def test_model_signatures_expose_canonical_types_and_wire_aliases() -> None:
    balance = inspect.signature(PerpsBalance).parameters
    assert balance["balance"].annotation is Decimal

    funding = inspect.signature(PerpsFundingPayment).parameters
    assert funding["funding"].annotation is Decimal
    assert funding["timestamp"].annotation is datetime

    proxy = inspect.signature(PerpsProxyKey).parameters
    assert "expiry" in proxy
    assert proxy["expiry"].annotation is datetime

    deposit = inspect.signature(PerpsDeposit).parameters
    assert deposit["amount"].annotation is Decimal
    assert deposit["created_timestamp"].annotation is datetime
    assert deposit["confirmed_timestamp"].annotation == (datetime | None)

    withdrawal = inspect.signature(PerpsWithdrawal).parameters
    assert "withdraw_id" in withdrawal
    assert withdrawal["hash"].annotation == (str | None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.25", Decimal("1.25")),
        (2, Decimal("2")),
        (1.5, Decimal("1.5")),
        (Decimal("3.75"), Decimal("3.75")),
    ],
)
def test_decimal_fields_preserve_perps_number_or_string_grammar(
    raw: object, expected: Decimal
) -> None:
    balance = PerpsBalance.parse_response({"asset": "USDC", "balance": raw, "value": raw})
    assert balance.balance == expected
    assert balance.value == expected


def test_decimal_fields_reject_booleans() -> None:
    with pytest.raises(UnexpectedResponseError):
        PerpsBalance.parse_response({"asset": "USDC", "balance": True, "value": "1"})


def test_tuple_points_preprocess_before_field_validation() -> None:
    equity = PerpsEquityPoint.parse_response([_EPOCH_MS, "10.5"])
    pnl = PerpsPnlPoint.parse_response((_EPOCH_MS, -2.25))

    assert equity.timestamp == _TIMESTAMP
    assert equity.equity == Decimal("10.5")
    assert pnl.timestamp == _TIMESTAMP
    assert pnl.pnl == Decimal("-2.25")

    with pytest.raises(UnexpectedResponseError):
        PerpsEquityPoint.parse_response([_EPOCH_MS, "10.5", "extra"])


@pytest.mark.parametrize("raw", [str(_EPOCH_MS), float(_EPOCH_MS), True, None])
def test_required_timestamps_preserve_strict_integer_epoch_ms_grammar(raw: object) -> None:
    with pytest.raises(UnexpectedResponseError):
        PerpsEquityPoint.parse_response([raw, "1"])


def test_required_timestamps_pass_datetime_instances_through() -> None:
    point = PerpsEquityPoint.parse_response([_TIMESTAMP, "1"])
    assert point.timestamp is _TIMESTAMP


def test_funding_payment_preserves_compact_aliases() -> None:
    payment = PerpsFundingPayment.parse_response(
        {
            "id": 3055723280187747,
            "iid": 7,
            "sz": "2",
            "fr": "0.001",
            "fua": "USDC",
            "fund": "0.25",
            "ts": _EPOCH_MS,
        }
    )

    assert payment.id == 3055723280187747
    assert payment.instrument_id == 7
    assert payment.size == Decimal("2")
    assert payment.funding_rate == Decimal("0.001")
    assert payment.funding_asset == "USDC"
    assert payment.funding == Decimal("0.25")
    assert payment.timestamp == _TIMESTAMP


def _deposit_payload(**overrides: object) -> dict[str, object]:
    return {
        "hash": "0xabc",
        "asset": "USDC",
        "amount": "100.5",
        "status": "pending",
        "from": "0xfrom",
        "to": "0xto",
        "confirmations": 0,
        "required_confirmations": 3,
        "created_timestamp": _EPOCH_MS,
        **overrides,
    }


def test_funds_timestamps_preserve_optional_and_datetime_behavior() -> None:
    omitted = PerpsDeposit.parse_response(_deposit_payload())
    explicit_none = PerpsDeposit.parse_response(_deposit_payload(confirmed_timestamp=None))
    datetimes = PerpsDeposit.parse_response(
        _deposit_payload(created_timestamp=_TIMESTAMP, confirmed_timestamp=_TIMESTAMP)
    )

    assert omitted.created_at == _TIMESTAMP
    assert omitted.confirmed_at is None
    assert explicit_none.confirmed_at is None
    assert datetimes.created_at is _TIMESTAMP
    assert datetimes.confirmed_at is _TIMESTAMP


@pytest.mark.parametrize("raw", [str(_EPOCH_MS), float(_EPOCH_MS), True, None])
def test_funds_created_timestamp_preserves_strict_epoch_ms_grammar(raw: object) -> None:
    with pytest.raises(UnexpectedResponseError):
        PerpsDeposit.parse_response(_deposit_payload(created_timestamp=raw))


@pytest.mark.parametrize("placeholder", ["", "0x"])
def test_optional_transaction_hash_placeholders_normalize_to_none(placeholder: str) -> None:
    deposit = PerpsDepositUpdate.parse_response(
        {"hash": placeholder, "asset": "USDC", "amount": "1", "status": "pending"}
    )
    withdrawal = PerpsWithdrawalUpdate.parse_response(
        {
            "withdraw_id": 1,
            "asset": "USDC",
            "amount": "1",
            "fee": "0.1",
            "status": "pending",
            "to": "0xto",
            "hash": placeholder,
        }
    )

    assert deposit.hash is None
    assert withdrawal.hash is None


def test_proxy_expiry_normalizes_nanoseconds_before_epoch_ms_parsing() -> None:
    proxy = PerpsProxyKey.parse_response(
        {"proxy": "0xproxy", "label": "bot", "expiry": _EPOCH_MS * 1_000_000}
    )
    assert proxy.expires_at == _TIMESTAMP


@pytest.mark.parametrize("raw", [str(_EPOCH_MS), float(_EPOCH_MS), True, None])
def test_proxy_expiry_preserves_strict_epoch_ms_grammar(raw: object) -> None:
    with pytest.raises(UnexpectedResponseError):
        PerpsProxyKey.parse_response({"proxy": "0xproxy", "expiry": raw})
