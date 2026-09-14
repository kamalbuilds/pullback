"""Decisions are tested against real notices, not invented ones.

data/nhtsa_sample.json is captured from
api.nhtsa.gov/recalls/recallsByVehicle for make=honda&model=accord&
modelYear=2021 (2026-09-14), plus one real record for a 2014 Jeep Cherokee
appended from the same live endpoint so the sample includes a genuine
parkOutSide=true campaign (23V338000, the power liftgate fire recall).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from agent.feeds.nhtsa import _parse_report_date, _sold_window, parse_recall

RAW = json.loads((Path(__file__).parent.parent / "data" / "nhtsa_sample.json").read_text())["results"]
BY_CAMPAIGN = {r["NHTSACampaignNumber"]: r for r in RAW}


@pytest.fixture
def seatbelt_recall():
    return parse_recall(BY_CAMPAIGN["21V900000"])


@pytest.fixture
def liftgate_fire_recall():
    """23V338000: Jeep Cherokee power liftgate fire, real parkOutSide=true campaign."""
    return parse_recall(BY_CAMPAIGN["23V338000"])


def test_the_notice_parsed_the_way_the_test_assumes(seatbelt_recall):
    r = seatbelt_recall
    assert r.source == "NHTSA"
    assert r.recall_id == "21V900000"
    assert r.recall_number == "21V900000"
    assert r.recall_date == date(2021, 11, 18)
    assert "SEAT BELTS" in r.title or "seat belt" in r.description.lower()
    assert r.url == "https://www.nhtsa.gov/recalls?nhtsaId=21V900000"
    assert r.contact_phone == "888-234-2138"
    assert "repair" in r.remedy_kinds


def test_a_notice_with_no_park_flags_carries_no_park_hazard(seatbelt_recall):
    assert not any("PARK" in h.upper() and "DRIVE" in h.upper() for h in seatbelt_recall.hazards)
    assert not any("PARK OUTSIDE" in h for h in seatbelt_recall.hazards)


def test_sold_window_spans_the_model_year_plus_or_minus_one(seatbelt_recall):
    c = seatbelt_recall.constraints
    assert c.sold_start == date(2020, 1, 1)
    assert c.sold_end == date(2022, 12, 31)
    assert c.models == ("ACCORD",)
    assert c.price_low is None and c.price_high is None
    assert c.retailers == () and c.upcs == ()


def test_sold_window_helper_matches_what_parse_recall_used():
    assert _sold_window(2021) == (date(2020, 1, 1), date(2022, 12, 31))


def test_park_outside_flag_becomes_a_hazard_string_not_a_silent_bit(liftgate_fire_recall):
    """This would fail if the parser dropped the severity signal on the floor."""
    r = liftgate_fire_recall
    assert r.constraints.models == ("CHEROKEE",)
    assert any("PARK OUTSIDE" in h for h in r.hazards)
    assert any("fire" in h.lower() for h in r.hazards)
    assert "repair" in r.remedy_kinds


def test_report_received_date_is_ddmmyyyy_not_iso():
    """18/11/2021 must parse as November 18, not day-18-of-a-13th-month error."""
    assert _parse_report_date("18/11/2021") == date(2021, 11, 18)
    assert _parse_report_date("01/02/2024") == date(2024, 2, 1)


def test_no_vin_fetch_function_is_exposed():
    """The module docstring says there is no VIN-scoped recalls endpoint;
    the module must not pretend otherwise by shipping a fake fetch_by_vin."""
    import agent.feeds.nhtsa as nhtsa

    assert not hasattr(nhtsa, "fetch_by_vin")


@pytest.mark.parametrize("payload", RAW, ids=lambda p: p["NHTSACampaignNumber"])
def test_every_real_record_parses_without_raising(payload):
    r = parse_recall(payload)
    assert r.source == "NHTSA"
    assert r.recall_date.year >= 2000
    assert r.constraints.checkable
