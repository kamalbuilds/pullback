"""Proof that all three sources are wired into one scan, not just CPSC.

Before this file, CPSC was the only source ever exercised past its own unit
tests: `agent/run.py` never loads NHTSA at all in cached mode and openFDA
only over the live feed, and nothing swept a household against captured
NHTSA or openFDA data the way `data/cpsc_2026.json` already gets swept.
These tests would fail the moment a source got dropped from candidate
generation, from `load_household`, or from `decide()`:

  test_a_toy_a_vehicle_and_a_food_item_each_match_their_own_source
      One purchase per source, each checked against real captured recall
      data. Deleting NHTSA support or the openFDA identifier path turns one
      of these three MATCHes into a NO_MATCH or NEEDS_EVIDENCE.

  test_purchases_never_match_a_recall_from_the_wrong_source
      The same three purchases, cross-checked against the other two feeds.
      If `candidates()` ever stopped being source-aware and fell back to
      pure text overlap for everything, this is what would catch a car
      matching a toy notice or a snack matching a repair bulletin.

  test_the_whole_household_sweep_produces_exactly_this_match_set
      Every purchase in data/household.json (fifteen retail purchases plus
      the one real vehicle) against every recall in all three captured
      feeds, with the actionable set asserted exactly, not just counted.
      This is the test that would catch a lot code accidentally matching a
      toy or a vehicle model string accidentally matching a product
      description, because a surprise anywhere in 739 recalls x 16
      purchases shows up as a set that no longer equals the expected one.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from agent.engine.scan import load_household, scan
from agent.engine.verdict import Outcome, Purchase
from agent.feeds import cpsc, nhtsa, openfda

DATA = Path(__file__).parent.parent / "data"


def _cpsc_recalls():
    raw = json.loads((DATA / "cpsc_2026.json").read_text())
    return [cpsc.parse_recall(item) for item in raw]


def _nhtsa_recalls():
    raw = json.loads((DATA / "nhtsa_sample.json").read_text())
    return [nhtsa.parse_recall(item) for item in raw["results"]]


def _openfda_recalls():
    raw = json.loads((DATA / "openfda_sample.json").read_text())
    recalls = []
    for group in ("food", "drug", "device"):
        recalls.extend(openfda.parse_recall(item) for item in raw[group]["results"])
    return recalls


CPSC_RECALLS = _cpsc_recalls()
NHTSA_RECALLS = _nhtsa_recalls()
OPENFDA_RECALLS = _openfda_recalls()
ALL_RECALLS = CPSC_RECALLS + NHTSA_RECALLS + OPENFDA_RECALLS

# The receipt line and recall this pair has always meant, per
# tests/test_veto.py: a real CPSC notice, matched on retailer, sold window,
# price band and description overlap, none of which is an identifier.
TOY = Purchase(
    purchase_id="amz-2026-0412",
    description="HABA Rainbow Rattle wooden grasping and teething toy for babies",
    retailer="Amazon.com",
    purchased_on=date(2026, 4, 12),
    price=12.99,
)

# The one real vehicle on file in data/household.json, which really does
# carry four open NHTSA campaigns in data/nhtsa_sample.json.
_, _HOUSEHOLD_PURCHASES, _HOUSEHOLD_RAW = load_household()
VEHICLE = next(p for p in _HOUSEHOLD_PURCHASES if p.purchase_id == "veh-honda-accord-2021")

# A food purchase built from a real captured openFDA record (F-2085-2015):
# the description and UPC are copied from the recall's own product_description
# and code_info, not invented, so this proves the UPC-identifier path
# resolves to MATCH against genuine enforcement-report data, the same way
# TOY proves the CPSC path and VEHICLE proves the NHTSA path.
FOOD = Purchase(
    purchase_id="cst-2015-hummus",
    description="Sabra Classic Hummus 17oz six pack",
    retailer="Costco",
    purchased_on=date(2015, 5, 1),
    price=6.99,
    upc="040822017497",
)


def test_a_toy_a_vehicle_and_a_food_item_each_match_their_own_source():
    actionable, _cleared, _counters = scan([TOY, VEHICLE, FOOD], ALL_RECALLS)
    by_purchase = {}
    for finding in actionable:
        by_purchase.setdefault(finding.purchase.purchase_id, set()).add(
            (finding.recall.source, finding.recall.recall_number, finding.verdict.outcome)
        )

    assert (
        "CPSC",
        "26719",
        Outcome.MATCH,
    ) in by_purchase["amz-2026-0412"]

    accord_matches = {
        (source, number, outcome)
        for (source, number, outcome) in by_purchase["veh-honda-accord-2021"]
        if source == "NHTSA" and outcome is Outcome.MATCH
    }
    assert {number for (_s, number, _o) in accord_matches} == {
        "21V900000",
        "24V064000",
        "23V858000",
        "26V332000",
    }

    assert (
        "openFDA",
        "F-2085-2015",
        Outcome.MATCH,
    ) in by_purchase["cst-2015-hummus"]


def test_purchases_never_match_a_recall_from_the_wrong_source():
    actionable, _cleared, _counters = scan([TOY, VEHICLE, FOOD], ALL_RECALLS)

    toy_sources = {f.recall.source for f in actionable if f.purchase.purchase_id == "amz-2026-0412"}
    assert toy_sources == {"CPSC"}

    vehicle_matches = {
        f.recall.source
        for f in actionable
        if f.purchase.purchase_id == "veh-honda-accord-2021" and f.verdict.outcome is Outcome.MATCH
    }
    assert vehicle_matches == {"NHTSA"}

    food_matches = {
        f.recall.source
        for f in actionable
        if f.purchase.purchase_id == "cst-2015-hummus" and f.verdict.outcome is Outcome.MATCH
    }
    assert food_matches == {"openFDA"}


def test_the_whole_household_sweep_produces_exactly_this_match_set():
    household, purchases, raw = load_household()
    assert household == "kamal"
    assert len(purchases) == 16  # 15 retail purchases + the one real vehicle

    actionable, _cleared, counters = scan(purchases, ALL_RECALLS)

    matched = {
        (f.purchase.purchase_id, f.recall.source, f.recall.recall_number)
        for f in actionable
        if f.verdict.outcome is Outcome.MATCH
    }
    needs_evidence = {
        (f.purchase.purchase_id, f.recall.source, f.recall.recall_number)
        for f in actionable
        if f.verdict.outcome is Outcome.NEEDS_EVIDENCE
    }

    # Established, measured against the real captured feeds by running the
    # scan and reading the checks back (see the task report): six CPSC
    # matches on toy purchases already known to carry a live recall, four
    # NHTSA matches for the one vehicle on file, and nothing at all from
    # openFDA, because none of the 300 sampled food/drug/device records
    # names Kirkland infant formula or anything else this household bought.
    assert matched == {
        ("amz-2026-0412", "CPSC", "26719"),
        ("amz-2024-1108", "CPSC", "26727"),
        ("amz-2024-1108", "CPSC", "26427"),
        ("hd-2024-0302", "CPSC", "26702"),
        ("amz-2026-0530", "CPSC", "26738"),
        ("amz-2025-0509", "CPSC", "26698"),
        ("veh-honda-accord-2021", "NHTSA", "21V900000"),
        ("veh-honda-accord-2021", "NHTSA", "24V064000"),
        ("veh-honda-accord-2021", "NHTSA", "23V858000"),
        ("veh-honda-accord-2021", "NHTSA", "26V332000"),
    }
    assert needs_evidence == {
        ("tgt-2026-0621", "CPSC", "26721"),
    }
    assert counters["matched"] == 10
    assert counters["needs_evidence"] == 1

    # The dangerous case this whole file exists to catch: no purchase of any
    # kind ever resolves to MATCH against a recall from a source its own
    # identity check rules out (a toy against NHTSA, a car against openFDA,
    # a food item against a CPSC toy notice, and so on).
    vehicle_off_source = {
        f.recall.recall_number
        for f in actionable
        if f.purchase.purchase_id == "veh-honda-accord-2021"
        and f.recall.source != "NHTSA"
        and f.verdict.outcome is Outcome.MATCH
    }
    assert vehicle_off_source == set()

    food_purchase_ids = {p.purchase_id for p in purchases if "formula" in p.description.lower()}
    food_off_source = {
        (f.purchase.purchase_id, f.recall.source)
        for f in actionable
        if f.purchase.purchase_id in food_purchase_ids
        and f.recall.source != "openFDA"
        and f.verdict.outcome is Outcome.MATCH
    }
    assert food_off_source == set()
