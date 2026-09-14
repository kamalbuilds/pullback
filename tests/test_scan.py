"""Unit tests for the source-aware scan.

CPSC, NHTSA and openFDA each identify a product differently, and these tests
pin down that `candidates()` reads the right field per source: text overlap
for CPSC, an exact model match only for NHTSA, and an identifier-first,
text-fallback read for openFDA, where the identifier is what actually
decides the case and the text fallback only ever gets a household as far as
NEEDS_EVIDENCE. Everything here runs against real captured feed data, the
same three files the household sweep in test_cross_feed.py uses, because a
synthetic notice can accidentally validate a rule the real prose would break.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from agent.engine.scan import Finding, candidates, load_household, scan
from agent.engine.verdict import Outcome, Purchase, decide
from agent.feeds import cpsc, nhtsa, openfda

DATA = Path(__file__).parent.parent / "data"
CPSC_RAW = json.loads((DATA / "cpsc_2026.json").read_text())
CPSC_BY_NUMBER = {str(r["RecallNumber"]): r for r in CPSC_RAW}
HABA = cpsc.parse_recall(CPSC_BY_NUMBER["26719"])

NHTSA_RAW = json.loads((DATA / "nhtsa_sample.json").read_text())["results"]
NHTSA_RECALLS = [nhtsa.parse_recall(r) for r in NHTSA_RAW]
ACCORD_CAMPAIGNS = [r for r in NHTSA_RECALLS if r.title.upper().startswith("HONDA ACCORD")]
CHEROKEE = next(r for r in NHTSA_RECALLS if "CHEROKEE" in r.title.upper())

OPENFDA_RAW = json.loads((DATA / "openfda_sample.json").read_text())
OPENFDA_FOOD = {r["recall_number"]: r for r in OPENFDA_RAW["food"]["results"]}
HUMMUS = openfda.parse_recall(OPENFDA_FOOD["F-2085-2015"])
COOKIES = openfda.parse_recall(OPENFDA_FOOD["F-2473-2016"])

TOY = Purchase(
    purchase_id="amz-2026-0412",
    description="HABA Rainbow Rattle wooden grasping and teething toy for babies",
    retailer="Amazon.com",
    purchased_on=date(2026, 4, 12),
    price=12.99,
)
ACCORD = Purchase(
    purchase_id="veh-honda-accord-2021",
    description="2021 Honda Accord Sedan",
    retailer="",
    purchased_on=date(2021, 6, 1),
    model="accord",
)


def test_load_household_includes_the_vehicle_as_a_purchase():
    household, purchases, raw = load_household()
    assert household == "kamal"
    assert len(purchases) == len(raw["purchases"]) + len(raw["vehicles"])
    vehicle = next(p for p in purchases if p.purchase_id == "veh-honda-accord-2021")
    assert vehicle.model == "accord"
    assert vehicle.description == "2021 Honda Accord Sedan"
    # Neither field is a real fact on file; both are inert once model carries
    # the identifier decide() actually settles a vehicle case on.
    assert vehicle.retailer == ""
    assert vehicle.price is None


def test_cpsc_candidate_generation_is_unchanged_pure_text_overlap():
    found = candidates(TOY, [HABA])
    assert len(found) == 1
    assert found[0].recall.recall_number == "26719"
    assert found[0].overlap == 0.875


def test_nhtsa_candidate_requires_an_exact_model_match():
    found = candidates(ACCORD, NHTSA_RECALLS)
    assert {c.recall.recall_number for c in found} == {r.recall_number for r in ACCORD_CAMPAIGNS}
    assert all(c.overlap == 1.0 for c in found)


def test_nhtsa_never_matches_on_description_text_alone():
    # The Cherokee's title and summary share real English words with a
    # sentence about a different car ("vehicles", "recalling", "2021" is
    # even absent here), but a purchase whose model does not say "cherokee"
    # must produce nothing: NHTSA candidates never fall back to text.
    assert candidates(ACCORD, [CHEROKEE]) == []


def test_a_purchase_with_no_model_never_becomes_an_nhtsa_candidate():
    assert candidates(TOY, NHTSA_RECALLS) == []


def test_openfda_upc_identifier_wins_over_text_and_settles_a_match():
    receipt = Purchase(
        purchase_id="cst-hummus",
        description="Sabra Classic Hummus 17oz six pack",
        retailer="Costco",
        purchased_on=date(2015, 5, 1),
        price=6.99,
        upc="040822017497",
    )
    found = candidates(receipt, [HUMMUS])
    assert len(found) == 1
    assert found[0].recall.recall_number == "F-2085-2015"
    assert found[0].overlap == 1.0
    assert decide(receipt, HUMMUS).outcome is Outcome.MATCH


def test_openfda_lot_code_identifier_also_settles_a_match():
    receipt = Purchase(
        purchase_id="cst-cookies",
        description="Savory Foods peanut butter cookies",
        retailer="Local bakery",
        purchased_on=date(2016, 1, 1),
        price=4.99,
        model="16033",
    )
    found = candidates(receipt, [COOKIES])
    assert len(found) == 1
    assert found[0].recall.recall_number == "F-2473-2016"
    assert decide(receipt, COOKIES).outcome is Outcome.MATCH


def test_openfda_text_without_an_identifier_is_a_candidate_but_never_a_match():
    # Same receipt, no UPC on file: candidates() still surfaces it (a lot
    # code or UPC recorded on a physical label is the exception, not the
    # rule, at 12%/45.7% real-feed coverage), but decide() has no identifier
    # and openFDA carries no retailer, window or price to fall back on, so
    # the strongest this can ever reach is NEEDS_EVIDENCE. Description
    # overlap is weak evidence for this source, exactly as designed: it can
    # raise a question, never answer one.
    receipt = Purchase(
        purchase_id="cst-hummus-no-upc",
        description="Sabra Classic Hummus 17oz six pack",
        retailer="Costco",
        purchased_on=date(2015, 5, 1),
        price=6.99,
    )
    found = candidates(receipt, [HUMMUS])
    assert len(found) == 1
    verdict = decide(receipt, HUMMUS)
    assert verdict.outcome is Outcome.NEEDS_EVIDENCE
    assert "the UPC printed on the box" in verdict.missing


def test_scan_returns_the_documented_shapes():
    actionable, cleared, counters = scan([ACCORD], ACCORD_CAMPAIGNS + [CHEROKEE])
    assert counters["purchases"] == 1
    assert counters["recalls"] == len(ACCORD_CAMPAIGNS) + 1
    assert counters["matched"] == len(ACCORD_CAMPAIGNS)
    assert counters["needs_evidence"] == 0
    assert all(isinstance(f, Finding) for f in actionable)
    assert {f.recall.recall_number for f in actionable} == {r.recall_number for r in ACCORD_CAMPAIGNS}
    assert all(f.verdict.outcome is Outcome.MATCH for f in actionable)
    # The Cherokee never even reached decide(): candidates() filtered it out.
    assert all(f.recall.recall_number != CHEROKEE.recall_number for f in cleared)
