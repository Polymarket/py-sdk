import inspect
from decimal import Decimal
from typing import get_type_hints

import pytest

from polymarket._internal.actions.orders.post import (
    build_post_order_request,
    build_post_orders_request,
    parse_order_response,
    parse_order_responses,
)
from polymarket._internal.actions.orders.types import BYTES32_ZERO
from polymarket.errors import UnexpectedResponseError, UserInputError
from polymarket.models.clob.order_response import AcceptedOrder, RawOrderResponse, RejectedOrder
from polymarket.models.clob.orders import SignedOrder
from polymarket.models.types import TokenId
from polymarket.types import EvmAddress, HexString

SIGNER = EvmAddress("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")
WALLET = EvmAddress("0x7754536ecd85c00b2e0cf9c1aa679340d8550756")
EXCHANGE = EvmAddress("0xE111180000d2663C0091e4f400237545B87B996B")  # unused on wire
SIGNATURE = HexString("0x" + "ab" * 65)


def _signed_order(**overrides: object) -> SignedOrder:
    base: dict[str, object] = {
        "builder": BYTES32_ZERO,
        "expiration": 0,
        "maker": WALLET,
        "maker_amount": 1_000_000,
        "metadata": BYTES32_ZERO,
        "order_type": "GTC",
        "salt": 42,
        "side": "BUY",
        "signature": SIGNATURE,
        "signature_type": 1,
        "signer": SIGNER,
        "taker_amount": 500_000,
        "timestamp": 1700000000000,
        "token_id": TokenId("8501497"),
        "post_only": False,
    }
    base.update(overrides)
    return SignedOrder(**base)  # type: ignore[arg-type]


def test_build_post_order_request_targets_order_path() -> None:
    path, _ = build_post_order_request(_signed_order(), owner_api_key="api-key")
    assert path == "/order"


def test_build_post_order_request_sends_salt_as_int_and_strings_for_amounts() -> None:
    _, body = build_post_order_request(_signed_order(), owner_api_key="api-key")
    assert body["order"]["salt"] == 42
    assert isinstance(body["order"]["salt"], int)
    assert body["order"]["makerAmount"] == "1000000"
    assert body["order"]["takerAmount"] == "500000"
    assert body["order"]["expiration"] == "0"
    assert body["order"]["timestamp"] == "1700000000000"


def test_build_post_order_request_wire_field_names_match_clob_contract() -> None:
    _, body = build_post_order_request(_signed_order(), owner_api_key="api-key")
    order = body["order"]
    assert set(order.keys()) == {
        "builder",
        "expiration",
        "maker",
        "makerAmount",
        "metadata",
        "salt",
        "side",
        "signature",
        "signatureType",
        "signer",
        "takerAmount",
        "timestamp",
        "tokenId",
    }
    assert body["deferExec"] is False
    assert body["orderType"] == "GTC"
    assert body["owner"] == "api-key"


def test_build_post_order_request_includes_post_only_only_when_set() -> None:
    _, body_off = build_post_order_request(_signed_order(), owner_api_key="api-key")
    assert "postOnly" not in body_off
    _, body_on = build_post_order_request(_signed_order(post_only=True), owner_api_key="api-key")
    assert body_on["postOnly"] is True


def test_build_post_order_request_rejects_post_only_on_fak() -> None:
    with pytest.raises(UserInputError, match="post-only"):
        build_post_order_request(
            _signed_order(post_only=True, order_type="FAK"), owner_api_key="api-key"
        )


def test_build_post_orders_request_targets_orders_path() -> None:
    path, payload = build_post_orders_request(
        [_signed_order(), _signed_order()], owner_api_key="api-key"
    )
    assert path == "/orders"
    assert len(payload) == 2


def test_build_post_orders_request_rejects_empty_list() -> None:
    with pytest.raises(UserInputError, match="non-empty"):
        build_post_orders_request([], owner_api_key="api-key")


def test_build_post_orders_request_rejects_more_than_fifteen() -> None:
    with pytest.raises(UserInputError, match="15"):
        build_post_orders_request([_signed_order()] * 16, owner_api_key="api-key")


def test_parse_order_response_normalizes_empty_making_taking_for_live_orders() -> None:
    raw: dict[str, object] = {
        "errorMsg": "",
        "makingAmount": "",
        "orderID": "0xLIVE",
        "status": "live",
        "success": True,
        "takingAmount": "",
        "tradeIDs": [],
        "transactionsHashes": [],
    }
    parsed = parse_order_response(raw)
    assert isinstance(parsed, AcceptedOrder)
    assert parsed.making_amount == 0
    assert parsed.taking_amount == 0


def test_raw_order_response_annotations_and_signature_expose_decimals() -> None:
    hints = get_type_hints(RawOrderResponse, include_extras=True)
    assert hints["making_amount"] is Decimal
    assert hints["taking_amount"] is Decimal

    parameters = inspect.signature(RawOrderResponse).parameters
    assert parameters["makingAmount"].annotation is Decimal
    assert parameters["takingAmount"].annotation is Decimal


@pytest.mark.parametrize("amount", [1, 1.0])
def test_parse_order_response_rejects_non_string_amounts(amount: object) -> None:
    raw: dict[str, object] = {
        "errorMsg": "",
        "makingAmount": amount,
        "orderID": "ord-1",
        "status": "live",
        "success": True,
        "takingAmount": "1",
    }

    with pytest.raises(UnexpectedResponseError):
        parse_order_response(raw)


def test_parse_order_response_recognizes_accepted_payload() -> None:
    raw = {
        "errorMsg": "",
        "makingAmount": "10",
        "orderID": "ord-1",
        "status": "live",
        "success": True,
        "takingAmount": "20",
        "tradeIDs": ["t1"],
        "transactionsHashes": ["0xabc"],
    }
    parsed = parse_order_response(raw)
    assert isinstance(parsed, AcceptedOrder)
    assert parsed.order_id == "ord-1"
    assert parsed.status == "live"
    assert parsed.trade_ids == ("t1",)


def test_parse_order_response_maps_balance_substring_to_not_enough_balance() -> None:
    raw: dict[str, object] = {
        "errorMsg": "not enough balance / allowance for the trade",
        "makingAmount": "0",
        "orderID": "",
        "status": "",
        "success": False,
        "takingAmount": "0",
        "tradeIDs": [],
        "transactionsHashes": [],
    }
    parsed = parse_order_response(raw)
    assert isinstance(parsed, RejectedOrder)
    assert parsed.code == "not_enough_balance"


def test_parse_order_response_maps_known_error_messages() -> None:
    cases: list[tuple[str, str]] = [
        ("invalid nonce", "invalid_nonce"),
        ("invalid expiration", "invalid_expiration"),
        ("invalid post-only order: order crosses book", "post_only_would_cross"),
        ("post-only mode: only post-only orders and cancels are allowed", "post_only_mode"),
    ]
    for msg, expected in cases:
        raw: dict[str, object] = {
            "errorMsg": msg,
            "makingAmount": "0",
            "orderID": "",
            "status": "",
            "success": False,
            "takingAmount": "0",
        }
        parsed = parse_order_response(raw)
        assert isinstance(parsed, RejectedOrder)
        assert parsed.code == expected


def test_parse_order_response_falls_back_to_unknown_for_unrecognized_error() -> None:
    raw = {
        "errorMsg": "some unexpected failure",
        "makingAmount": "0",
        "orderID": "",
        "status": "",
        "success": False,
        "takingAmount": "0",
    }
    parsed = parse_order_response(raw)
    assert isinstance(parsed, RejectedOrder)
    assert parsed.code == "unknown"


def test_parse_order_response_uses_unmatched_when_status_says_so() -> None:
    raw = {
        "errorMsg": "",
        "makingAmount": "0",
        "orderID": "",
        "status": "unmatched",
        "success": True,
        "takingAmount": "0",
    }
    parsed = parse_order_response(raw)
    assert isinstance(parsed, RejectedOrder)
    assert parsed.code == "unmatched"


def test_parse_order_responses_parses_each_entry() -> None:
    raw = [
        {
            "errorMsg": "",
            "makingAmount": "1",
            "orderID": "a",
            "status": "live",
            "success": True,
            "takingAmount": "2",
        },
        {
            "errorMsg": "invalid nonce",
            "makingAmount": "0",
            "orderID": "",
            "status": "",
            "success": False,
            "takingAmount": "0",
        },
    ]
    parsed = parse_order_responses(raw)
    assert isinstance(parsed[0], AcceptedOrder)
    assert isinstance(parsed[1], RejectedOrder)
    assert parsed[1].code == "invalid_nonce"


def test_parse_order_responses_maps_batch_post_only_rejections() -> None:
    rejection: dict[str, object] = {
        "errorMsg": "post-only mode: only post-only orders and cancels are allowed",
        "orderID": "",
        "takingAmount": "",
        "makingAmount": "",
        "status": "",
        "success": True,
    }
    parsed = parse_order_responses([rejection, dict(rejection)])
    assert len(parsed) == 2
    for entry in parsed:
        assert isinstance(entry, RejectedOrder)
        assert entry.code == "post_only_mode"


def test_parse_order_responses_rejects_non_list() -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_order_responses({"not": "a list"})
