"""semantic_candidates() catches the false negative candidates() cannot.

Purchase amz-2019-0714 ("LED projecting finger lights party favors 50
pieces multicolor") and CPSC recall 26761 ("Cade California Electronic
Projecting Finger Light Toys") describe the same product: sold on
Amazon.com, March 2015 through July 2026, $5-$16, and the purchase falls
inside every one of those. But the two strings share almost no words, so
candidates()'s 18% token-overlap floor rejects the pair before the verdict
engine ever runs on it. test_the_lexical_filter_misses_it below reproduces
that, against the same captured feed used everywhere else in this suite.

data/index/recalls.npz must already exist (built by
scripts/build_index.py) for these tests to run; that artifact is committed
alongside this test file, not generated on the fly.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from agent.engine.retrieval import DEFAULT_FLOOR, semantic_candidates
from agent.engine.scan import candidates, load_household
from agent.engine.verdict import Outcome, Purchase, decide
from agent.feeds.cpsc import parse_recall

RAW = json.loads((Path(__file__).parent.parent / "data" / "cpsc_2026.json").read_text())


@pytest.fixture(scope="module")
def recalls():
    return [parse_recall(r) for r in RAW]


@pytest.fixture(scope="module")
def finger_lights_purchase():
    _, purchases, _ = load_household()
    return next(p for p in purchases if p.purchase_id == "amz-2019-0714")


def test_the_lexical_filter_misses_it(finger_lights_purchase, recalls):
    """The measured defect: candidates() never offers 26761 up at all."""
    numbers = [c.recall.recall_number for c in candidates(finger_lights_purchase, recalls)]
    assert "26761" not in numbers


def test_semantic_retrieval_finds_it(finger_lights_purchase, recalls):
    found = semantic_candidates(finger_lights_purchase, recalls)
    numbers = {c.recall.recall_number for c in found}
    assert "26761" in numbers
    hit = next(c for c in found if c.recall.recall_number == "26761")
    assert hit.overlap >= DEFAULT_FLOOR


def test_the_verdict_engine_now_gets_to_look_at_the_real_pair(finger_lights_purchase, recalls):
    """The downstream consequence: decide() runs on a pair it never saw before.

    Without an IdentityAssertion (out of scope for this module; that is
    judge_identity's job elsewhere in the pipeline), decide() falls back to
    its own hardcoded description_overlap check, which this pair still
    fails at 29% against decide()'s 34% bar. What retrieval changes is that
    the arithmetic gets to run at all: retailer, sold_window and price_band
    all pass, so this purchase now depends on exactly one missing fact --
    an identity read -- instead of being silently discarded before any
    check ran.
    """
    target = next(
        c.recall
        for c in semantic_candidates(finger_lights_purchase, recalls)
        if c.recall.recall_number == "26761"
    )
    v = decide(finger_lights_purchase, target)
    passed = {c.name for c in v.passed}
    assert {"retailer", "sold_window", "price_band"} <= passed
    assert v.outcome is Outcome.NO_MATCH
    assert [c.name for c in v.failed] == ["description_overlap"]


def test_an_unrelated_purchase_does_not_flood_the_semantic_filter(recalls):
    """The Kirkland dog bed pattern: nothing in a household toy recall feed
    should resemble a pet-store dog bed closely enough to clear the floor.
    """
    dog_bed = Purchase(
        purchase_id="unrelated",
        description="Kirkland Signature orthopedic dog bed large grey",
        retailer="Petco",
        purchased_on=date(2024, 6, 1),
        price=59.99,
    )
    found = semantic_candidates(dog_bed, recalls)
    assert found == []


def test_the_floor_is_tuned_between_the_two_measured_points():
    """DEFAULT_FLOOR sits strictly between the dog bed's measured ceiling
    (0.6387, the highest similarity any of the 739 indexed recalls reaches
    against it) and the finger-light pair's measured similarity (0.6568).
    """
    assert 0.6387 < DEFAULT_FLOOR < 0.6568
