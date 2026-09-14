"""Decisions are tested against real notices, not invented ones.

data/cpsc_2026.json is the verbatim response from
saferproducts.gov/RestWebServices/Recall for 2026, captured 2026-09-13.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from agent.engine.verdict import Outcome, Purchase, decide
from agent.feeds.cpsc import parse_recall

RAW = json.loads((Path(__file__).parent.parent / "data" / "cpsc_2026.json").read_text())
BY_NUMBER = {str(r["RecallNumber"]): r for r in RAW}


@pytest.fixture
def finger_lights():
    """26761: Amazon.com, March 2015 - July 2026, $5-$16, no UPC, no model."""
    return parse_recall(BY_NUMBER["26761"])


@pytest.fixture
def ceiling_fan():
    """A notice that does carry UPCs, so identifiers decide instead."""
    payload = next(r for r in RAW if r["ProductUPCs"] and "Ceiling Fan" in r["Title"])
    return parse_recall(payload)


def buy(**kw) -> Purchase:
    base = dict(
        purchase_id="p1",
        description="CADE California Electronic Projecting Finger Light Toys 50 pieces",
        retailer="Amazon.com",
        purchased_on=date(2023, 8, 14),
        price=12.99,
    )
    base.update(kw)
    return Purchase(**base)


def test_the_notice_parsed_the_way_the_test_assumes(finger_lights):
    c = finger_lights.constraints
    assert (c.sold_start, c.sold_end) == (date(2015, 3, 1), date(2026, 7, 31))
    assert (c.price_low, c.price_high) == (5.0, 16.0)
    assert c.upcs == () and c.models == ()
    assert finger_lights.contact_email == "ccecamazonservice@gmail.com"
    assert "refund" in finger_lights.remedy_kinds


def test_every_circumstance_agrees_so_the_claim_may_go(finger_lights):
    v = decide(buy(), finger_lights)
    assert v.outcome is Outcome.MATCH
    assert {c.name for c in v.passed} >= {"retailer", "sold_window", "price_band"}
    assert v.evidence_id == "26761:p1:MATCH"


def test_bought_before_the_product_existed(finger_lights):
    v = decide(buy(purchased_on=date(2012, 1, 5)), finger_lights)
    assert v.outcome is Outcome.NO_MATCH
    assert [c.name for c in v.failed] == ["sold_window"]


def test_paid_far_too_much_to_be_this_product(finger_lights):
    v = decide(buy(price=249.00), finger_lights)
    assert v.outcome is Outcome.NO_MATCH
    assert [c.name for c in v.failed] == ["price_band"]


def test_bought_somewhere_the_notice_never_names(finger_lights):
    v = decide(buy(retailer="Walmart"), finger_lights)
    assert v.outcome is Outcome.NO_MATCH


def test_a_different_toy_from_the_same_shop_is_not_this_recall(finger_lights):
    v = decide(buy(description="Melissa & Doug wooden puzzle board"), finger_lights)
    assert v.outcome is Outcome.NO_MATCH
    assert [c.name for c in v.failed] == ["description_overlap"]


def test_too_little_known_to_claim_and_it_says_what_is_missing(finger_lights):
    v = decide(buy(price=None, purchased_on=date(2023, 8, 14)), finger_lights)
    assert v.outcome is Outcome.NEEDS_EVIDENCE
    assert "what it cost" in v.missing


def test_a_upc_on_the_list_settles_it_alone(ceiling_fan):
    upc = ceiling_fan.constraints.upcs[0]
    v = decide(
        buy(
            description="Hampton Bay Halwin 52 in. ceiling fan",
            retailer="The Home Depot",
            purchased_on=date(2024, 3, 2),
            price=179.00,
            upc=upc,
        ),
        ceiling_fan,
    )
    assert v.outcome is Outcome.MATCH


def test_a_upc_off_the_list_overrides_every_circumstance(ceiling_fan):
    v = decide(
        buy(
            description="Hampton Bay Halwin 52 in. ceiling fan",
            retailer="The Home Depot",
            purchased_on=date(2024, 3, 2),
            price=179.00,
            upc="000000000000",
        ),
        ceiling_fan,
    )
    assert v.outcome is Outcome.NO_MATCH


@pytest.mark.parametrize("payload", RAW, ids=lambda p: str(p["RecallNumber"]))
def test_no_notice_in_2026_matches_a_purchase_of_something_else(payload):
    """A dog bed bought at a pet shop must not match any of the 434 notices."""
    recall = parse_recall(payload)
    v = decide(
        Purchase(
            purchase_id="unrelated",
            description="Kirkland Signature orthopedic dog bed large grey",
            retailer="Petco",
            purchased_on=date(2024, 6, 1),
            price=59.99,
        ),
        recall,
    )
    assert v.outcome is not Outcome.MATCH
