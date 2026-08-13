from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import get_type_hints

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
        "quoteId": "quote-id",
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


@pytest.mark.parametrize("tron_field", ["tron", "tvm"])
def test_address_set_normalizes_tron_wire_variants_and_advisories(
    tron_field: str,
) -> None:
    result = FundingAddressSet.parse_response(
        {
            "address": {
                "evm": _EVM_ADDRESS,
                "svm": _SVM_ADDRESS,
                "btc": _BTC_ADDRESS,
                tron_field: _TRON_ADDRESS,
            },
            "note": "Only supported assets should be sent.",
            "warnings": [{"code": "missing_builder_code", "message": "Add attribution."}],
        }
    )

    assert result.addresses.tron == _TRON_ADDRESS
    assert result.note == "Only supported assets should be sent."
    assert result.warnings[0].code == "missing_builder_code"


def test_asset_and_quote_wire_numbers_use_canonical_python_types() -> None:
    catalog = FundingAssetCatalog.parse_response(
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
            ]
        }
    )
    quote = FundingQuote.parse_response(_quote_payload())

    assert catalog.assets[0].chain_id == 728126428
    assert catalog.assets[0].minimum_amount_usd == Decimal("7.25")
    assert quote.estimated_checkout_time == timedelta(seconds=25)
    assert quote.estimated_input_usd == Decimal("14.488305")
    assert quote.estimated_destination_amount == 14_491_203


def test_transaction_normalizes_known_status_amount_and_timestamp() -> None:
    result = FundingTransaction.parse_response(
        _transaction_payload(
            txHash="3atr19NAiNCYt24RHM1WnzZp47RXskpTDzspJoCBBaMFw",
            createdTimeMs="1757531217339",
        )
    )

    assert result.source_amount == 13_566_635
    assert result.status is KnownFundingTransactionStatus.COMPLETED
    assert result.created_at == datetime.fromtimestamp(1_757_531_217_339 / 1000, tz=UTC)


def test_transaction_preserves_unknown_status_for_forward_compatibility() -> None:
    result = FundingTransaction.parse_response(_transaction_payload(status="COMPLIANCE_REVIEW"))

    assert result.status == "COMPLIANCE_REVIEW"
    assert not isinstance(result.status, KnownFundingTransactionStatus)


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


def test_public_model_annotations_expose_canonical_python_types() -> None:
    asset_hints = get_type_hints(FundingAsset)
    quote_hints = get_type_hints(FundingQuote)
    transaction_hints = get_type_hints(FundingTransaction)

    assert asset_hints["chain_id"] is int
    assert asset_hints["minimum_amount_usd"] is Decimal
    assert quote_hints["estimated_checkout_time"] is timedelta
    assert transaction_hints["source_amount"] is int
