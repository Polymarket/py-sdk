from collections.abc import Callable

import pytest

from polymarket._internal.actions.funding import (
    build_create_deposit_addresses_request,
    build_create_withdrawal_addresses_request,
    build_funding_quote_request,
    build_funding_status_request,
    parse_funding_address_set,
    parse_funding_asset_catalog,
    parse_funding_quote,
    parse_funding_transactions,
)
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.funding import (
    FundingAddressSet,
    FundingAssetCatalog,
    FundingQuote,
    FundingTransaction,
)

_WALLET_LOWER = "0x52908400098527886e0f7030069857d2e4169ee7"
_WALLET_CHECKSUM = "0x52908400098527886E0F7030069857D2E4169EE7"
_BUILDER_CODE = "0x" + "ab" * 32


def _address_set_payload() -> dict[str, object]:
    return {
        "address": {
            "evm": _WALLET_CHECKSUM,
            "svm": "CrvTBvzryYxBHbWu2TiQpcqD5M7Le7iBKzVmEj3f36Jb",
            "btc": "bc1q8eau83qffxcj8ht4hsjdza3lha9r3egfqysj3g",
            "tron": "TP1mjRAUVe5qXfCnpczdWhSrGpos2Arzir",
        },
        "note": "Only supported assets should be sent.",
        "warnings": [
            {
                "code": "missing_builder_code",
                "message": "Include X-Builder-Code for attribution.",
            }
        ],
    }


def _asset_catalog_payload() -> dict[str, object]:
    return {
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
                "minCheckoutUsd": 7,
            }
        ],
        "note": "Assets may be used for deposits and withdrawals.",
    }


def _quote_payload() -> dict[str, object]:
    return {
        "estCheckoutTimeMs": 25_000,
        "estFeeBreakdown": {
            "appFeeLabel": "Fun.xyz fee",
            "appFeePercent": 0,
            "appFeeUsd": 0,
            "fillCostPercent": 0,
            "fillCostUsd": 0,
            "gasUsd": 0.003854,
            "maxSlippage": 0,
            "minReceived": 14.488305,
            "swapImpact": 0,
            "swapImpactUsd": 0,
            "totalImpact": 0,
            "totalImpactUsd": 0,
        },
        "estInputUsd": 14.488305,
        "estOutputUsd": 14.488305,
        "estToTokenBaseUnit": "14491203",
        "quoteId": "0xquote",
    }


def _transaction_payload() -> dict[str, object]:
    return {
        "fromChainId": "1151111081099710",
        "fromTokenAddress": "11111111111111111111111111111111",
        "fromAmountBaseUnit": "13566635",
        "toChainId": "137",
        "toTokenAddress": "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB",
        "status": "COMPLETED",
        "txHash": "3atr19NAiNCYt24RHM1WnzZp47RXskpTDzspJoCBBaMFw",
        "createdTimeMs": 1_757_531_217_339,
    }


def test_build_deposit_request_serializes_wallet_and_builder_header() -> None:
    path, body, headers = build_create_deposit_addresses_request(
        wallet=_WALLET_LOWER,
        builder_code=_BUILDER_CODE,
    )

    assert path == "/deposit"
    assert body == {"address": _WALLET_CHECKSUM}
    assert headers == {"X-Builder-Code": _BUILDER_CODE}


def test_build_deposit_request_omits_builder_header_when_unset() -> None:
    _, _, headers = build_create_deposit_addresses_request(wallet=_WALLET_LOWER)

    assert headers == {}


@pytest.mark.parametrize(
    "builder_code",
    [
        "",
        "ab" * 32,
        "0x" + "ab" * 31,
        "0x" + "ab" * 33,
        "0x" + "zz" * 32,
    ],
)
def test_build_deposit_request_rejects_malformed_builder_code(builder_code: str) -> None:
    with pytest.raises(UserInputError, match="builder_code"):
        build_create_deposit_addresses_request(
            wallet=_WALLET_LOWER,
            builder_code=builder_code,
        )


def test_build_deposit_request_rejects_non_string_builder_code() -> None:
    with pytest.raises(UserInputError, match="builder_code"):
        build_create_deposit_addresses_request(
            wallet=_WALLET_LOWER,
            builder_code=42,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "wallet",
    ["", "0x1234", "not-an-address", "52908400098527886e0f7030069857d2e4169ee7"],
)
def test_build_deposit_request_rejects_invalid_wallet(wallet: str) -> None:
    with pytest.raises(UserInputError, match="wallet"):
        build_create_deposit_addresses_request(wallet=wallet)


def test_build_deposit_request_rejects_non_string_wallet() -> None:
    with pytest.raises(UserInputError, match="wallet"):
        build_create_deposit_addresses_request(wallet=42)  # type: ignore[arg-type]


def test_build_withdrawal_request_uses_wire_names_and_string_chain_id() -> None:
    path, body, headers = build_create_withdrawal_addresses_request(
        wallet=_WALLET_LOWER,
        destination_chain_id=728126428,
        destination_token_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        recipient_address="TP1mjRAUVe5qXfCnpczdWhSrGpos2Arzir",
        builder_code=_BUILDER_CODE,
    )

    assert path == "/withdraw"
    assert body == {
        "address": _WALLET_CHECKSUM,
        "toChainId": "728126428",
        "toTokenAddress": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "recipientAddr": "TP1mjRAUVe5qXfCnpczdWhSrGpos2Arzir",
    }
    assert headers == {"X-Builder-Code": _BUILDER_CODE}


def test_build_withdrawal_request_rejects_invalid_builder_code() -> None:
    with pytest.raises(UserInputError, match="builder_code"):
        build_create_withdrawal_addresses_request(
            wallet=_WALLET_LOWER,
            destination_chain_id=1,
            destination_token_address="USDC",
            recipient_address="recipient",
            builder_code="invalid",
        )


@pytest.mark.parametrize("destination_chain_id", [0, -1, True, 1.5])
def test_build_withdrawal_request_rejects_invalid_chain_id(
    destination_chain_id: object,
) -> None:
    with pytest.raises(UserInputError, match="destination_chain_id"):
        build_create_withdrawal_addresses_request(
            wallet=_WALLET_LOWER,
            destination_chain_id=destination_chain_id,  # type: ignore[arg-type]
            destination_token_address="USDC",
            recipient_address="recipient",
        )


def test_build_withdrawal_request_rejects_empty_destination_token() -> None:
    with pytest.raises(UserInputError, match="destination_token_address"):
        build_create_withdrawal_addresses_request(
            wallet=_WALLET_LOWER,
            destination_chain_id=1,
            destination_token_address="",
            recipient_address="recipient",
        )


def test_build_withdrawal_request_rejects_empty_recipient() -> None:
    with pytest.raises(UserInputError, match="recipient_address"):
        build_create_withdrawal_addresses_request(
            wallet=_WALLET_LOWER,
            destination_chain_id=1,
            destination_token_address="USDC",
            recipient_address="",
        )


def test_build_quote_request_serializes_integers_as_wire_strings() -> None:
    path, body = build_funding_quote_request(
        amount=10_000_000,
        source_chain_id=137,
        source_token_address="0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        destination_chain_id=137,
        destination_token_address="0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB",
        recipient_address=_WALLET_CHECKSUM,
    )

    assert path == "/quote"
    assert body == {
        "fromAmountBaseUnit": "10000000",
        "fromChainId": "137",
        "fromTokenAddress": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        "recipientAddress": _WALLET_CHECKSUM,
        "toChainId": "137",
        "toTokenAddress": "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB",
    }


@pytest.mark.parametrize("amount", [0, -1, True, 1.5])
def test_build_quote_request_rejects_invalid_amount(amount: object) -> None:
    with pytest.raises(UserInputError, match="amount"):
        build_funding_quote_request(
            amount=amount,  # type: ignore[arg-type]
            source_chain_id=1,
            source_token_address="source-token",
            destination_chain_id=137,
            destination_token_address="destination-token",
            recipient_address="recipient",
        )


@pytest.mark.parametrize("source_chain_id", [0, -1, True, 1.5])
def test_build_quote_request_rejects_invalid_source_chain_id(source_chain_id: object) -> None:
    with pytest.raises(UserInputError, match="source_chain_id"):
        build_funding_quote_request(
            amount=1,
            source_chain_id=source_chain_id,  # type: ignore[arg-type]
            source_token_address="source-token",
            destination_chain_id=137,
            destination_token_address="destination-token",
            recipient_address="recipient",
        )


def test_build_quote_request_rejects_empty_source_token() -> None:
    with pytest.raises(UserInputError, match="source_token_address"):
        build_funding_quote_request(
            amount=1,
            source_chain_id=1,
            source_token_address="",
            destination_chain_id=137,
            destination_token_address="destination-token",
            recipient_address="recipient",
        )


def test_build_quote_request_rejects_empty_destination_token() -> None:
    with pytest.raises(UserInputError, match="destination_token_address"):
        build_funding_quote_request(
            amount=1,
            source_chain_id=1,
            source_token_address="source-token",
            destination_chain_id=137,
            destination_token_address="",
            recipient_address="recipient",
        )


def test_build_quote_request_rejects_empty_recipient() -> None:
    with pytest.raises(UserInputError, match="recipient_address"):
        build_funding_quote_request(
            amount=1,
            source_chain_id=1,
            source_token_address="source-token",
            destination_chain_id=137,
            destination_token_address="destination-token",
            recipient_address="",
        )


def test_build_quote_request_trims_generic_chain_addresses() -> None:
    _, body = build_funding_quote_request(
        amount=1,
        source_chain_id=1,
        source_token_address=" source-token ",
        destination_chain_id=137,
        destination_token_address=" destination-token ",
        recipient_address=" recipient ",
    )

    assert body["fromTokenAddress"] == "source-token"
    assert body["toTokenAddress"] == "destination-token"
    assert body["recipientAddress"] == "recipient"


@pytest.mark.parametrize(
    "field", ["source_token_address", "destination_token_address", "recipient_address"]
)
def test_build_quote_request_rejects_whitespace_only_address(field: str) -> None:
    values = {
        "amount": 1,
        "source_chain_id": 1,
        "source_token_address": "source-token",
        "destination_chain_id": 137,
        "destination_token_address": "destination-token",
        "recipient_address": "recipient",
    }
    values[field] = "   "

    with pytest.raises(UserInputError, match=field):
        build_funding_quote_request(**values)  # type: ignore[arg-type]


def test_build_status_request_percent_encodes_non_evm_address() -> None:
    assert build_funding_status_request(address="tron/address with space") == (
        "/status/tron%2Faddress%20with%20space"
    )


@pytest.mark.parametrize("address", ["", "   ", 42])
def test_build_status_request_rejects_invalid_address(address: object) -> None:
    with pytest.raises(UserInputError, match="address"):
        build_funding_status_request(address=address)  # type: ignore[arg-type]


def test_funding_parsers_return_public_models() -> None:
    address_set = parse_funding_address_set(_address_set_payload())
    catalog = parse_funding_asset_catalog(_asset_catalog_payload())
    quote = parse_funding_quote(_quote_payload())
    transactions = parse_funding_transactions({"transactions": [_transaction_payload()]})

    assert isinstance(address_set, FundingAddressSet)
    assert isinstance(catalog, FundingAssetCatalog)
    assert isinstance(quote, FundingQuote)
    assert len(transactions) == 1
    assert isinstance(transactions[0], FundingTransaction)


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (parse_funding_address_set, {}),
        (parse_funding_asset_catalog, {"supportedAssets": "not-a-list"}),
        (parse_funding_quote, {}),
        (parse_funding_transactions, {}),
        (parse_funding_transactions, {"transactions": {}}),
    ],
)
def test_funding_parsers_map_malformed_responses_to_unexpected_response(
    parser: Callable[[object], object],
    payload: object,
) -> None:
    with pytest.raises(UnexpectedResponseError):
        parser(payload)
