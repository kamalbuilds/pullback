"""NHTSA vehicle recall feed.

recallsByVehicle returns one flat record per campaign per queried
make/model/year, no nesting. There is no free-text "sold at" sentence like
CPSC notices carry, because a vehicle recall is not identified by where it
was bought, it is identified by make, model and model year (and, once NHTSA
publishes the affected VIN range weeks after the campaign opens, by VIN). So
this adapter does not try to mine a price band or a retailer out of the
Summary text; those fields are structurally absent, not just unparsed.

Probed against the live API (2026-09-14):
  - recallsByVehicle?make=&model=&modelYear=  -> works, no auth, this is
    the endpoint this module uses.
  - recallsByVin, recallsByVin/{vin}          -> both 403 "Missing
    Authentication Token", which is API Gateway's answer for a route that
    does not exist, not an auth failure. There is no VIN-scoped recalls
    endpoint on api.nhtsa.gov. vpic.nhtsa.dot.gov/api/vehicles/decodevin
    exists but decodes a VIN into make/model/year, it does not return
    recalls; a VIN lookup would mean decoding first and then calling
    fetch_by_vehicle, which is a two-endpoint composition this module does
    not perform on the caller's behalf. fetch_by_vin is intentionally not
    implemented rather than faked.

ReportReceivedDate is dd/MM/yyyy, not ISO. Parse it explicitly.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import httpx

from agent.feeds.base import Constraints, Recall

BASE = "https://api.nhtsa.gov/recalls/recallsByVehicle"

_PHONE = re.compile(r"\b(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]\d{4}\b")

# Vehicle remedies are long free-text paragraphs, not a coded list like
# CPSC's Remedies array, so the kind has to be read out of the words the
# same way CPSC's does. In practice almost every campaign maps to "repair"
# because "replace the X, free of charge" is how NHTSA phrases a dealer
# repair, but a few are refunds (buybacks) or pure software updates, so this
# is still derived per record rather than hardcoded to ("repair",).
_REMEDY_WORDS = {
    "repair": ("repair", "replace", "reprogram", "recalibrate", "install", "modify", "service the"),
    "software_update": ("software update", "update the software", "reflash", "over-the-air"),
    "refund": ("refund", "reimburse", "repurchase", "buy back", "buyback"),
    "inspect": ("inspect",),
}


def _remedy_kinds(remedy: str) -> tuple[str, ...]:
    text = remedy.lower()
    return tuple(kind for kind, words in _REMEDY_WORDS.items() if any(w in text for w in words))


def _parse_report_date(s: str) -> date:
    day, month, year = s.strip().split("/")
    return date(int(year), int(month), int(day))


def _sold_window(model_year: int) -> tuple[date, date]:
    # A given model year is on dealer lots and sold across two calendar
    # years either side of it (a 2021 model typically goes on sale in mid
    # to late 2020 and can still be sold new into 2022), so a purchase date
    # falling anywhere in [modelYear-1, modelYear+1] is consistent with the
    # vehicle being this model year. This is a coarse band, not a sold-at
    # sentence, because NHTSA does not publish one.
    return date(model_year - 1, 1, 1), date(model_year + 1, 12, 31)


def parse_recall(payload: dict[str, Any]) -> Recall:
    campaign = str(payload.get("NHTSACampaignNumber") or "")
    make = (payload.get("Make") or "").strip()
    model = (payload.get("Model") or "").strip()
    model_year_raw = payload.get("ModelYear")
    model_year = int(model_year_raw) if model_year_raw else 0
    component = (payload.get("Component") or "").strip()
    summary = (payload.get("Summary") or "").strip()
    consequence = (payload.get("Consequence") or "").strip()
    remedy = (payload.get("Remedy") or "").strip()
    notes = (payload.get("Notes") or "") or ""

    hazards = [h for h in (consequence,) if h]
    if payload.get("parkIt"):
        hazards.append("DO NOT DRIVE: NHTSA parkIt flag is set for this campaign")
    if payload.get("parkOutSide"):
        hazards.append("PARK OUTSIDE: fire risk, NHTSA parkOutSide flag is set for this campaign")

    phone = _PHONE.search(f"{remedy} {notes}")

    title = f"{make} {model} {model_year}: {component}".strip()

    return Recall(
        source="NHTSA",
        recall_id=campaign,
        recall_number=campaign,
        recall_date=_parse_report_date(payload["ReportReceivedDate"]),
        title=title,
        description=summary,
        url=f"https://www.nhtsa.gov/recalls?nhtsaId={campaign}" if campaign else "",
        hazards=tuple(hazards),
        remedies=(remedy,) if remedy else (),
        remedy_kinds=_remedy_kinds(remedy),
        contact_raw=remedy,
        contact_email=None,
        contact_phone=phone.group(0) if phone else None,
        units=None,
        constraints=Constraints(
            *_sold_window(model_year) if model_year else (None, None),
            models=(model,) if model else (),
        ),
    )


def fetch_by_vehicle(make: str, model: str, model_year: int, *, timeout: float = 30.0) -> list[Recall]:
    resp = httpx.get(
        BASE,
        params={"make": make, "model": model, "modelYear": model_year},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    recalls = [parse_recall(item) for item in body.get("results", [])]
    recalls.sort(key=lambda r: r.recall_date, reverse=True)
    return recalls
