from decimal import Decimal

import pytest
from data_v2_samples import sample

from polymarket import ComboTradeActivity, TipActivity, TradeActivity, UnknownActivity
from polymarket.errors import UnexpectedResponseError
from polymarket.models.data.activity import parse_activities, parse_activity, parse_combo_activities


def test_trade_amount_sentinels_and_combo_discriminator() -> None:
    payload = {
        **sample("activity")[0],
        "type": "TRADE",
        "is_combo": False,
        "usdc_size": 4.2,
        "size": 10,
        "price": 0.42,
        "side": "BUY",
        "outcome_index": 999,
        "title": "",
        "outcome": "",
    }
    trade = parse_activity(payload)
    assert isinstance(trade, TradeActivity)
    assert trade.amount == Decimal("4.2") and trade.shares == Decimal(10)
    assert trade.outcome_index is None and trade.title is None and trade.outcome is None
    direct = TradeActivity.parse_response(payload)
    assert direct == trade
    combo = parse_activity({**payload, "is_combo": True, "condition_id": "0x03" + "ab" * 30})
    assert isinstance(combo, ComboTradeActivity)
    assert combo.position_id == payload["token_id"]
    for field in ("proxy_wallet", "transaction_hash", "condition_id", "usdc_size"):
        broken = dict(payload)
        broken.pop(field)
        with pytest.raises(UnexpectedResponseError):
            parse_activity(broken)


@pytest.mark.parametrize(
    "kind",
    [
        "SPLIT",
        "MERGE",
        "REDEEM",
        "CONVERSION",
        "REWARD",
        "MIGRATION",
        "DEPOSIT",
        "WITHDRAWAL",
        "YIELD",
        "MAKER_REBATE",
        "TAKER_REBATE",
        "REFERRAL_REWARD",
        "TIP",
    ],
)
def test_activity_variants(kind: str) -> None:
    payload = {**sample("activity")[0], "type": kind, "usdc_size": 1.25, "side": ""}
    row = parse_activity(payload)
    assert not isinstance(row, UnknownActivity)
    assert row.type == kind and row.amount == Decimal("1.25")
    if isinstance(row, TipActivity):
        assert row.side is None


def test_unknown_activity_and_bad_shapes() -> None:
    unknown = parse_activity({"type": "FUTURE_EVENT", "new_field": 123, "name": ""})
    assert isinstance(unknown, UnknownActivity) and unknown.raw["new_field"] == 123
    assert unknown.name is None and unknown.raw["name"] == ""
    bad_payloads: tuple[object, ...] = (None, [], 1)
    for payload in bad_payloads:
        with pytest.raises(UnexpectedResponseError):
            parse_activity(payload)
    with pytest.raises(UnexpectedResponseError):
        parse_activities({})


def test_combo_activity_position_and_redeem_payout() -> None:
    base = sample("activity_combos")[0]
    for kind in ("SPLIT", "MERGE", "CONVERT", "COMPRESS", "WRAP", "UNWRAP", "REDEEM"):
        row = parse_combo_activities([{**base, "type": kind, "payout_usdc": 1.5}])[0]
        assert row.position_id == base["combo_position_id"]
        assert ("payout" in type(row).model_fields) == (kind == "REDEEM")
