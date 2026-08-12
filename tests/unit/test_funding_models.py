from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import get_args, get_type_hints

import pytest

from polymarket.errors import UnexpectedResponseError
from polymarket.models.funding import (
    FundingAddressSet,
    FundingAsset,
    FundingAssetCatalog,
    FundingQuote,
    FundingTransaction,
    KnownFundingTransactionStatus,
)

_EVM_ADDRESS = "0x23566f8b2E82aDfCf01846E54899d110e97AC053"
_SVM_ADDRESS = "CrvTBvzryYxBHbWu2TiQpcqD5M7Le7iBKzVmEj3f36Jb"
_BTC_ADDRESS = "bc1q8eau83qffxcj8ht4hsjdza3lha9r3egfqysj3g"
_TRON_ADDRESS = "TP1mjRAUVe5qXfCnpczdWhSrGpos2Arzir"


def _address_set_payload(*, tron_field: str = "tron") -> dict[str, object]:
    return {
        "address": {
            "evm": _EVM_ADDRESS,
            "svm": _SVM_ADDRESS,
            "btc": _BTC_ADDRESS,
            tron_field: _TRON_ADDRESS,
        },
        "note": "Only certain chains and tokens are supported.",
        "warnings": [
            {
                "code": "missing_builder_code",
                "message": "Include the X-Builder-Code header for attribution.",
            }
        ],
    }


def _quote_payload() -> dict[str, object]:
    return {
        "estCheckoutTimeMs": "25000",
        "estFeeBreakdown": {
            "appFeeLabel": "Fun.xyz fee",
            "appFeePercent": "0",
            "appFeeUsd": 0,
            "fillCostPercent": "0.1",
            "fillCostUsd": 0.01,
            "gasUsd": 0.003854,
            "maxSlippage": "0.5",
            "minReceived": 14.488305,
            "swapImpact": "0.05",
            "swapImpactUsd": 0.005,
            "totalImpact": "0.6",
            "totalImpactUsd": 0.06,
        },
        "estInputUsd": "14.488305",
        "estOutputUsd": 14.4,
        "estToTokenBaseUnit": "14491203",
        "quoteId": "0x00c34ba467184b0146406d62b0e60aaa24ed52460bd456222b6155a0d9de0ad5",
    }


def _transaction_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "fromChainId": "1151111081099710",
        "fromTokenAddress": "11111111111111111111111111111111",
        "fromAmountBaseUnit": "13566635",
        "toChainId": "137",
        "toTokenAddress": "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB",
        "status": "COMPLETED",
    }
    payload.update(overrides)
    return payload


def test_address_set_parses_live_tron_and_warning_shape() -> None:
    result = FundingAddressSet.parse_response(_address_set_payload())

    assert result.addresses.evm == _EVM_ADDRESS
    assert result.addresses.svm == _SVM_ADDRESS
    assert result.addresses.btc == _BTC_ADDRESS
    assert result.addresses.tron == _TRON_ADDRESS
    assert result.note == "Only certain chains and tokens are supported."
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "missing_builder_code"


@pytest.mark.parametrize("wire_field", ["tron", "tvm"])
def test_address_set_normalizes_tron_and_tvm_wire_fields(wire_field: str) -> None:
    result = FundingAddressSet.parse_response(_address_set_payload(tron_field=wire_field))

    assert result.addresses.tron == _TRON_ADDRESS
    dumped = result.model_dump()
    assert dumped["addresses"]["tron"] == _TRON_ADDRESS
    assert "tvm" not in dumped["addresses"]


def test_address_set_prefers_live_tron_field_when_both_variants_are_present() -> None:
    payload = _address_set_payload()
    addresses = payload["address"]
    assert isinstance(addresses, dict)
    addresses["tvm"] = "legacy-tvm-address"

    result = FundingAddressSet.parse_response(payload)

    assert result.addresses.tron == _TRON_ADDRESS


def test_address_set_defaults_optional_advisories() -> None:
    result = FundingAddressSet.parse_response(
        {"address": {"evm": _EVM_ADDRESS, "svm": _SVM_ADDRESS, "btc": _BTC_ADDRESS}}
    )

    assert result.addresses.tron is None
    assert result.note is None
    assert result.warnings == ()


def test_address_set_rejects_malformed_evm_address() -> None:
    payload = _address_set_payload()
    addresses = payload["address"]
    assert isinstance(addresses, dict)
    addresses["evm"] = "0x1234"

    with pytest.raises(UnexpectedResponseError, match="FundingAddressSet response"):
        FundingAddressSet.parse_response(payload)


def test_asset_catalog_normalizes_chain_minimum_and_note() -> None:
    result = FundingAssetCatalog.parse_response(
        {
            "supportedAssets": [
                {
                    "chainId": "728126428",
                    "chainName": "Tron",
                    "token": {
                        "name": "Tether USD",
                        "symbol": "USDT",
                        "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                        "decimals": 6,
                    },
                    "minCheckoutUsd": "7.25",
                }
            ],
            "note": "These assets support deposits and withdrawals.",
        }
    )

    assert len(result.assets) == 1
    assert result.assets[0].chain_id == 728126428
    assert isinstance(result.assets[0].chain_id, int)
    assert result.assets[0].minimum_amount_usd == Decimal("7.25")
    assert isinstance(result.assets[0].minimum_amount_usd, Decimal)
    assert result.assets[0].token.decimals == 6
    assert result.note == "These assets support deposits and withdrawals."


@pytest.mark.parametrize("minimum", ["NaN", "Infinity", True, -1, -float("inf")])
def test_asset_catalog_rejects_non_finite_or_boolean_minimum(minimum: object) -> None:
    payload = {
        "supportedAssets": [
            {
                "chainId": "1",
                "chainName": "Ethereum",
                "token": {"name": "USD Coin", "symbol": "USDC", "address": "0xUSDC", "decimals": 6},
                "minCheckoutUsd": minimum,
            }
        ]
    }

    with pytest.raises(UnexpectedResponseError, match="FundingAssetCatalog response"):
        FundingAssetCatalog.parse_response(payload)


def test_quote_normalizes_amounts_and_time_to_canonical_types() -> None:
    result = FundingQuote.parse_response(_quote_payload())

    assert result.estimated_checkout_time == timedelta(seconds=25)
    assert isinstance(result.estimated_checkout_time, timedelta)
    assert result.estimated_input_usd == Decimal("14.488305")
    assert result.estimated_output_usd == Decimal("14.4")
    assert isinstance(result.estimated_input_usd, Decimal)
    assert result.estimated_destination_amount == 14_491_203
    assert isinstance(result.estimated_destination_amount, int)
    assert result.estimated_fees.gas_usd == Decimal("0.003854")
    assert result.estimated_fees.minimum_received == Decimal("14.488305")


def test_quote_rejects_boolean_decimal_field() -> None:
    payload = _quote_payload()
    payload["estInputUsd"] = True

    with pytest.raises(UnexpectedResponseError, match="FundingQuote response"):
        FundingQuote.parse_response(payload)


def test_quote_rejects_negative_checkout_time() -> None:
    payload = _quote_payload()
    payload["estCheckoutTimeMs"] = -1

    with pytest.raises(UnexpectedResponseError, match="FundingQuote response"):
        FundingQuote.parse_response(payload)


def test_transaction_normalizes_known_status_amount_and_timestamp() -> None:
    result = FundingTransaction.parse_response(
        _transaction_payload(
            txHash="3atr19NAiNCYt24RHM1WnzZp47RXskpTDzspJoCBBaMFw",
            createdTimeMs="1757531217339",
        )
    )

    assert result.source_chain_id == 1_151_111_081_099_710
    assert isinstance(result.source_chain_id, int)
    assert result.source_amount == 13_566_635
    assert isinstance(result.source_amount, int)
    assert result.status is KnownFundingTransactionStatus.COMPLETED
    assert result.transaction_hash == "3atr19NAiNCYt24RHM1WnzZp47RXskpTDzspJoCBBaMFw"
    assert result.created_at == datetime.fromtimestamp(1_757_531_217_339 / 1000, tz=UTC)
    assert result.created_at is not None and result.created_at.tzinfo is UTC


def test_transaction_maps_wire_origin_confirmation_status() -> None:
    result = FundingTransaction.parse_response(_transaction_payload(status="ORIGIN_TX_CONFIRMED"))

    assert result.status is KnownFundingTransactionStatus.ORIGIN_TRANSACTION_CONFIRMED


def test_transaction_preserves_unknown_status_for_forward_compatibility() -> None:
    result = FundingTransaction.parse_response(_transaction_payload(status="COMPLIANCE_REVIEW"))

    assert result.status == "COMPLIANCE_REVIEW"
    assert not isinstance(result.status, KnownFundingTransactionStatus)


def test_transaction_allows_status_dependent_fields_to_be_absent() -> None:
    result = FundingTransaction.parse_response(_transaction_payload(status="DEPOSIT_DETECTED"))

    assert result.status is KnownFundingTransactionStatus.DEPOSIT_DETECTED
    assert result.transaction_hash is None
    assert result.created_at is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fromChainId", 0),
        ("toChainId", True),
        ("fromAmountBaseUnit", -1),
        ("status", ""),
        ("createdTimeMs", -1),
    ],
)
def test_transaction_rejects_malformed_wire_values(field: str, value: object) -> None:
    with pytest.raises(UnexpectedResponseError, match="FundingTransaction response"):
        FundingTransaction.parse_response(_transaction_payload(**{field: value}))


def test_public_funding_annotations_use_canonical_python_types() -> None:
    asset_hints = get_type_hints(FundingAsset)
    quote_hints = get_type_hints(FundingQuote)
    transaction_hints = get_type_hints(FundingTransaction)

    assert asset_hints["chain_id"] is int
    assert asset_hints["minimum_amount_usd"] is Decimal
    assert quote_hints["estimated_checkout_time"] is timedelta
    assert quote_hints["estimated_input_usd"] is Decimal
    assert quote_hints["estimated_destination_amount"] is int
    assert transaction_hints["source_amount"] is int
    assert datetime in get_args(transaction_hints["created_at"])
