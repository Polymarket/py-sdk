from datetime import UTC, datetime
from decimal import Decimal
from typing import assert_type

import pytest
from data_v2_samples import sample

from polymarket import (
    ActivityType,
    AsyncPublicClient,
    ComboActivityType,
    ComboConditionId,
    ComboRedemptionActivity,
    ComboTradeActivity,
    ConditionId,
    PublicClient,
    RedeemActivity,
    TipActivity,
    TradeActivity,
    UnknownActivity,
)
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
    assert trade.type is ActivityType.TRADE
    epoch = parse_activity({**payload, "timestamp": 0})
    assert epoch.timestamp == datetime(1970, 1, 1, tzinfo=UTC)
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
    assert row.type is ActivityType(kind) and row.amount == Decimal("1.25")
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
        assert row.type is ComboActivityType(kind)
        assert ("payout" in type(row).model_fields) == (kind == "REDEEM")


# data-api-v2 53a79ac, combo_token_outcomes_survive_projection_and_keyset.
_COMBO_CONDITION = "0x03" + "ab" * 30


def combo_row(kind: str, outcome: str, index: int) -> dict[str, object]:
    return {
        **sample("activity")[0],
        "type": kind,
        "is_combo": True,
        "condition_id": _COMBO_CONDITION,
        "outcome": outcome,
        "outcome_index": index,
        "side": "BUY",
        "size": 17.105871,
        "usdc_size": 0.5,
        "price": 0.03,
        "token_id": str(
            1373525411643998707269718504228978186297414887389368269897738957660941713408
            + (2 if index == 999 else index)
        ),
        "title": "Georgia vs. Arkansas",
        "slug": "",
        "event_slug": "",
    }


@pytest.mark.parametrize(
    "kind,side,outcome,index",
    [
        ("TRADE", "BUY", "Yes", 0),
        ("TRADE", "BUY", "No", 1),
        ("TRADE", "SELL", "Yes", 0),
        ("TRADE", "SELL", "No", 1),
        ("REDEEM", "", "Yes", 0),
        ("REDEEM", "", "No", 1),
    ],
)
def test_combo_token_outcomes(kind: str, side: str, outcome: str, index: int) -> None:
    row = parse_activity({**combo_row(kind, outcome, index), "side": side})
    assert isinstance(row, (ComboTradeActivity, ComboRedemptionActivity))
    assert row.is_combo is True
    assert row.condition_id == _COMBO_CONDITION
    assert row.outcome == outcome
    assert row.outcome_index == index
    assert row.amount == Decimal("0.5")


@pytest.mark.parametrize("kind", ["TRADE", "REDEEM"])
def test_unknown_combo_outcomes_stay_unavailable(kind: str) -> None:
    row = parse_activity(combo_row(kind, "", 999))
    assert isinstance(row, (ComboTradeActivity, ComboRedemptionActivity))
    assert row.outcome is None
    assert row.outcome_index is None


@pytest.mark.parametrize("is_combo", [False, None])
def test_redeem_ctf03_prefix_does_not_imply_combo(is_combo: bool | None) -> None:
    condition_id = "0x03" + "cd" * 30 + "00"
    payload = {**combo_row("REDEEM", "Arkansas", 1), "condition_id": condition_id}
    if is_combo is None:
        payload.pop("is_combo")
    else:
        payload["is_combo"] = is_combo
    row = parse_activity(payload)
    assert isinstance(row, RedeemActivity)
    assert row.is_combo is False
    assert row.condition_id == condition_id
    assert row.outcome == "Arkansas"
    assert row.outcome_index == 1


def test_combo_redemptions_stay_in_the_mixed_activity_feed() -> None:
    rows = parse_activities(
        [
            combo_row("TRADE", "Yes", 0),
            combo_row("REDEEM", "No", 1),
            {**sample("activity")[0], "type": "REWARD"},
        ]
    )
    assert [row.type for row in rows] == ["TRADE", "REDEEM", "REWARD"]
    assert isinstance(rows[1], ComboRedemptionActivity)
    with pytest.raises(UnexpectedResponseError):
        parse_activity({**combo_row("REDEEM", "No", 1), "condition_id": "0x01" + "ab" * 30})


# Checked by Pyright through the real public method annotations; no fabricated client.
def public_activity_types(client: PublicClient) -> None:
    for activity in client.list_activity(user="0x" + "12" * 20).first_page().items:
        if isinstance(activity, ComboTradeActivity):
            assert_type(activity.outcome, str | None)
            assert_type(activity.outcome_index, int | None)
        if isinstance(activity, ComboRedemptionActivity):
            assert_type(activity.condition_id, ComboConditionId)
        if isinstance(activity, RedeemActivity):
            assert_type(activity.condition_id, ConditionId)


async def async_public_activity_types(client: AsyncPublicClient) -> None:
    page = await client.list_activity(user="0x" + "12" * 20).first_page()
    for activity in page.items:
        if isinstance(activity, ComboRedemptionActivity):
            assert_type(activity.condition_id, ComboConditionId)
            assert_type(activity.outcome, str | None)
            assert_type(activity.outcome_index, int | None)


@pytest.mark.parametrize("title", ["", None])
def test_combo_redemption_missing_presentation_keeps_mixed_feed(title: str | None) -> None:
    redemption = combo_row("REDEEM", "No", 1)
    if title is None:
        redemption.pop("title")
    else:
        redemption["title"] = title
    for field in ("icon", "slug", "event_slug"):
        redemption.pop(field, None)
    rows = parse_activities([{**sample("activity")[0], "type": "REWARD"}, redemption])
    assert [row.type for row in rows] == ["REWARD", "REDEEM"]
    assert isinstance(rows[1], ComboRedemptionActivity)
    assert rows[1].title is None and rows[1].icon is None
    assert rows[1].outcome == "No" and rows[1].outcome_index == 1
