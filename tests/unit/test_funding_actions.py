import pytest

from polymarket._internal.actions.funding import (
    build_create_deposit_addresses_request,
    build_create_withdrawal_addresses_request,
    build_funding_quote_request,
    build_list_funding_transactions_request,
    parse_funding_transactions_page,
)
from polymarket.errors import UnexpectedResponseError, UserInputError

_WALLET_LOWER = "0x52908400098527886e0f7030069857d2e4169ee7"
_WALLET_CHECKSUM = "0x52908400098527886E0F7030069857D2E4169EE7"
_BUILDER_CODE = "0x" + "ab" * 32


def test_funding_request_builders_serialize_protocol_fields() -> None:
    deposit_path, deposit_body, deposit_headers = build_create_deposit_addresses_request(
        wallet=_WALLET_LOWER,
        builder_code=_BUILDER_CODE,
    )
    withdrawal_path, withdrawal_body, withdrawal_headers = (
        build_create_withdrawal_addresses_request(
            wallet=_WALLET_LOWER,
            destination_chain_id=728126428,
            destination_token_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
            recipient_address="TP1mjRAUVe5qXfCnpczdWhSrGpos2Arzir",
            builder_code=_BUILDER_CODE,
        )
    )
    quote_path, quote_body = build_funding_quote_request(
        amount=10_000_000,
        source_chain_id=137,
        source_token_address="source-token",
        destination_chain_id=137,
        destination_token_address="destination-token",
        recipient_address=_WALLET_CHECKSUM,
    )

    assert (deposit_path, deposit_body, deposit_headers) == (
        "/deposit",
        {"address": _WALLET_CHECKSUM},
        {"X-Builder-Code": _BUILDER_CODE},
    )
    assert (withdrawal_path, withdrawal_body, withdrawal_headers) == (
        "/withdraw",
        {
            "address": _WALLET_CHECKSUM,
            "toChainId": "728126428",
            "toTokenAddress": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
            "recipientAddr": "TP1mjRAUVe5qXfCnpczdWhSrGpos2Arzir",
        },
        {"X-Builder-Code": _BUILDER_CODE},
    )
    assert (quote_path, quote_body) == (
        "/quote",
        {
            "fromAmountBaseUnit": "10000000",
            "fromChainId": "137",
            "fromTokenAddress": "source-token",
            "recipientAddress": _WALLET_CHECKSUM,
            "toChainId": "137",
            "toTokenAddress": "destination-token",
        },
    )


@pytest.mark.parametrize(
    "builder_code",
    ["", "ab" * 32, "0x" + "ab" * 31, "0x" + "zz" * 32],
)
def test_deposit_builder_rejects_malformed_builder_codes(builder_code: str) -> None:
    with pytest.raises(UserInputError, match="builder_code"):
        build_create_deposit_addresses_request(
            wallet=_WALLET_LOWER,
            builder_code=builder_code,
        )


@pytest.mark.parametrize("amount", [0, -1, True, 1.5])
def test_quote_builder_rejects_non_positive_integer_amounts(amount: object) -> None:
    with pytest.raises(UserInputError, match="amount"):
        build_funding_quote_request(
            amount=amount,  # type: ignore[arg-type]
            source_chain_id=137,
            source_token_address="source-token",
            destination_chain_id=137,
            destination_token_address="destination-token",
            recipient_address="recipient",
        )


def test_status_builder_preserves_opaque_cursor_and_maps_page_size_to_limit() -> None:
    path, params = build_list_funding_transactions_request(
        address="tron/address with space",
        page_size=100,
        cursor="opaque+/=cursor",
    )

    assert path == "/status/tron%2Faddress%20with%20space"
    assert params == {"limit": 100, "cursor": "opaque+/=cursor"}
    assert "paginate" not in params


@pytest.mark.parametrize("page_size", [0, 101, True, 1.5])
def test_status_builder_rejects_invalid_page_sizes(page_size: object) -> None:
    with pytest.raises(UserInputError, match="page_size"):
        build_list_funding_transactions_request(
            address=_WALLET_CHECKSUM,
            page_size=page_size,  # type: ignore[arg-type]
        )


def test_status_page_stops_only_on_absent_or_null_next_cursor() -> None:
    continued = parse_funding_transactions_page({"transactions": [], "nextCursor": "LTE="})
    terminal = parse_funding_transactions_page({"transactions": [], "nextCursor": None})
    legacy_terminal = parse_funding_transactions_page({"transactions": []})

    assert continued.items == ()
    assert continued.has_more is True
    assert continued.next_cursor == "LTE="
    assert terminal.has_more is False
    assert terminal.next_cursor is None
    assert legacy_terminal.has_more is False
    assert legacy_terminal.next_cursor is None


@pytest.mark.parametrize(
    "payload",
    [
        {"transactions": [], "nextCursor": ""},
        {"transactions": [], "nextCursor": 42},
    ],
)
def test_status_page_rejects_malformed_next_cursor(
    payload: dict[str, object],
) -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_funding_transactions_page(payload)
