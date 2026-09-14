"""Decisions are tested against real notices, not invented ones.

data/openfda_sample.json is three real responses from api.fda.gov
(/food, /drug, /device enforcement.json, ?limit=100 each, no search filter,
captured 2026-09-14), kept under keys "food", "drug", "device" in the raw
meta+results shape the API returns.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from agent.feeds.openfda import _extract_lot_codes, _extract_upcs, parse_recall

RAW = json.loads((Path(__file__).parent.parent / "data" / "openfda_sample.json").read_text())
ALL_RESULTS = [(key, r) for key in ("food", "drug", "device") for r in RAW[key]["results"]]
FOOD_BY_NUMBER = {r["recall_number"]: r for r in RAW["food"]["results"]}


@pytest.fixture
def cytodetox_recall():
    """F-0276-2017: real UPC and real lot code in the same code_info string."""
    return parse_recall(FOOD_BY_NUMBER["F-0276-2017"])


def test_the_notice_parsed_the_way_the_test_assumes(cytodetox_recall):
    r = cytodetox_recall
    assert r.source == "openFDA"
    assert r.recall_number == "F-0276-2017"
    assert r.recall_date == date(2016, 8, 8)
    assert r.hazards == ("Class II",)
    assert r.units == "1,990 bottles"
    assert "Burkholderia cepacia" in r.description
    # url is intentionally empty: openFDA has no stable per-record detail page.
    assert r.url == ""
    assert r.remedies == () and r.remedy_kinds == ()


def test_a_upc_and_a_lot_code_come_out_of_the_same_code_info_string(cytodetox_recall):
    """This would fail if the parser silently returned empty Constraints."""
    c = cytodetox_recall.constraints
    assert c.upcs == ("632687615989",)
    assert c.models == ("30661601",)
    assert c.sold_start is None and c.sold_end is None
    assert c.price_low is None and c.price_high is None


def test_grouped_upc_with_spaces_is_recognized():
    assert _extract_upcs("UPC 635349 000390  Best By dates: 07/01/14") == ("635349000390",)


def test_upc_with_a_unit_size_parenthetical_before_the_digits():
    upcs = _extract_upcs("UPC (5 oz.): 609465693477 UPC (10 0z.): 642147152459")
    assert upcs == ("609465693477", "642147152459")


def test_a_multi_lot_list_does_not_bleed_the_next_items_enumerator_into_the_digits():
    """Regression: a naive greedy digit-run regex previously swallowed a
    trailing ' 3' from '3. best by:' into the UPC of the item before it."""
    text = (
        "1. best by:01/09/2025 UPC: X002SSIRIF "
        "2. best by: 09/21/2025 UPC: 687456214160 "
        "3. best by: 07/25/2025 UPC: 687456215594"
    )
    assert _extract_upcs(text) == ("687456214160", "687456215594")


def test_unlabeled_digit_runs_are_not_treated_as_upcs():
    """A GTIN or serial number is not a consumer UPC just because it is the
    right length; without the UPC label this must return nothing."""
    assert _extract_upcs("GTIN: 20884521128009  LOT Numbers: 2200400154") == ()


def test_upc_falls_back_to_product_description_when_code_info_has_none():
    """H-1265-2026 (Outshine Fruit Bar Watermelon, real record fetched
    2026-09-14): code_info holds only batch/best-before codes with no UPC
    at all, but product_description quotes the UPC directly. Without the
    fallback, extract_constraints would silently return upcs=() here even
    though the recall names an exact retail UPC."""
    from agent.feeds.openfda import extract_constraints

    payload = {
        "code_info": (
            "Batch code/ Best Before (bottom of package): LLA617603   30 JUN 2027 "
            "LLA617703   30 JUN 2027 LLA617803   30 JUN 2027"
        ),
        "product_description": (
            "Outshine Fruit Bar Watermelon, 6-Count 2.5 ounce with UPC 041548413624, "
            "packaged in paper outer cartons; individual fruit bars in plastic wrapper."
        ),
    }
    c = extract_constraints(payload)
    assert c.upcs == ("041548413624",)
    assert c.models == ("LLA617603", "LLA617703", "LLA617803")


def test_lot_extraction_handles_several_real_formats():
    assert _extract_lot_codes("Lot codes: 72746") == ("72746",)
    assert _extract_lot_codes("Batch: 1BK0964, Exp 01/31/2023") == ("1BK0964",)
    assert _extract_lot_codes("Lot #s: 7800929, 7800931, Exp 02/15; 7800962, Exp 03/15") == (
        "7800929",
        "7800931",
    )
    assert _extract_lot_codes("no codes") == ()
    assert _extract_lot_codes("None") == ()


def test_lot_extraction_stops_at_an_adjacent_udi_field_without_a_comma():
    text = "REF (RPN): HNB5.0-38-65-P-NS-RIM  Lot Number: 9890936  UDI: (01)00827002059795(17)220729(10)9890936"
    assert _extract_lot_codes(text) == ("9890936",)


def test_measured_extraction_coverage_across_300_real_records():
    """Real coverage numbers, not estimates: how many of 300 captured
    food/drug/device enforcement reports yield a parseable UPC or lot code."""
    def upc_of(r: dict) -> tuple[str, ...]:
        return _extract_upcs(r.get("code_info") or "") or _extract_upcs(r.get("product_description") or "")

    total = len(ALL_RESULTS)
    upc_hits = sum(1 for _, r in ALL_RESULTS if upc_of(r))
    lot_hits = sum(1 for _, r in ALL_RESULTS if _extract_lot_codes(r.get("code_info") or ""))
    either_hits = sum(1 for _, r in ALL_RESULTS if upc_of(r) or _extract_lot_codes(r.get("code_info") or ""))
    assert total == 300
    # These are floors, not exact pins, so a future re-capture of the same
    # live endpoints (which changes over time) does not spuriously fail.
    # Measured on this exact capture: 36 UPC hits, 137 lot hits, 161 either.
    assert upc_hits >= 20
    assert lot_hits >= 110
    assert either_hits >= upc_hits and either_hits >= lot_hits


@pytest.mark.parametrize("key_and_payload", ALL_RESULTS, ids=lambda kp: f"{kp[0]}:{kp[1]['recall_number']}")
def test_every_real_record_parses_without_raising(key_and_payload):
    _, payload = key_and_payload
    r = parse_recall(payload)
    assert r.source == "openFDA"
    assert r.recall_number == payload["recall_number"]
    assert r.recall_date.year >= 1990
