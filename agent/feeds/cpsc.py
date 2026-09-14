"""CPSC SaferProducts recall feed.

The feed is prose. Of the 434 notices published in 2026 through September, 3%
carry a UPC and none carry a model number, but 94% state where and when the
product was sold and 99% state what it cost. Those three facts are what a
household purchase record can actually be checked against, so they are what we
extract.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any

import httpx

from agent.feeds.base import Constraints, Recall

BASE = "https://www.saferproducts.gov/RestWebServices/Recall"

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}

_SOLD_AT = re.compile(r"^\s*Sold\s*(?:At|Exclusively at)?\s*:", re.I)
_WINDOW = re.compile(
    r"from\s+(?P<start>[A-Z][a-z]+\s+\d{4}|\d{4})\s+(?:through|to|until)\s+"
    r"(?P<end>[A-Z][a-z]+\s+\d{4}|\d{4}|present)",
    re.I,
)
_PRICE_RANGE = re.compile(
    r"between\s*\$(?P<lo>[\d,]+(?:\.\d\d)?)\s*and\s*\$(?P<hi>[\d,]+(?:\.\d\d)?)", re.I
)
_PRICE_POINT = re.compile(
    r"(?:for|at)\s*(?:about|approximately|around)?\s*\$(?P<p>[\d,]+(?:\.\d\d)?)", re.I
)
_EMAIL = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
_PHONE = re.compile(r"\b(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]\d{4}\b")
_REMEDY_WORDS = {
    "refund": ("refund", "full refund", "credit"),
    "replace": ("replacement", "replace"),
    "repair": ("repair kit", "repair", "free repair"),
    "destroy": ("destroy", "discard", "dispose", "cut the", "throw away"),
    "stop_use": ("stop using", "immediately stop"),
}


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def _parse_month_year(s: str, *, end: bool) -> date | None:
    s = s.strip().lower()
    if s == "present":
        return date.today()
    if re.fullmatch(r"\d{4}", s):
        return date(int(s), 12, 31) if end else date(int(s), 1, 1)
    m = re.fullmatch(r"([a-z]+)\s+(\d{4})", s)
    if not m or m.group(1) not in MONTHS:
        return None
    month, year = MONTHS[m.group(1)], int(m.group(2))
    if not end:
        return date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def _retailer_lines(raw: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Split the Retailers array into seller names and free-text 'Sold At' lines."""
    names: list[str] = []
    sold: list[str] = []
    for item in raw or []:
        name = (item.get("Name") or "").strip()
        if not name:
            continue
        if _SOLD_AT.match(name) or "\n" in name:
            sold.append(_SOLD_AT.sub("", name).strip())
        else:
            names.append(name)
    return names, sold


def extract_constraints(payload: dict[str, Any]) -> Constraints:
    names, sold = _retailer_lines(payload.get("Retailers", []))
    blob = " ".join(sold) or " ".join(names)
    # Some notices put the sold-at sentence in the description instead.
    if not _WINDOW.search(blob):
        blob = f"{blob} {payload.get('Description', '')}"

    start = end = None
    if (m := _WINDOW.search(blob)) is not None:
        start = _parse_month_year(m.group("start"), end=False)
        end = _parse_month_year(m.group("end"), end=True)

    low = high = None
    if (m := _PRICE_RANGE.search(blob)) is not None:
        low, high = _money(m.group("lo")), _money(m.group("hi"))
    elif (m := _PRICE_POINT.search(blob)) is not None:
        point = _money(m.group("p"))
        # "for about $180" is a soft figure; allow a 20% band around it.
        low, high = round(point * 0.8, 2), round(point * 1.2, 2)

    retailers = tuple(
        dict.fromkeys(
            [n for n in names if n]
            + [s.split(" from ")[0].strip(" .,") for s in sold if s]
        )
    )
    upcs = tuple(u["UPC"] for u in payload.get("ProductUPCs", []) if u.get("UPC"))
    models = tuple(
        p["Model"].strip() for p in payload.get("Products", []) if p.get("Model", "").strip()
    )
    return Constraints(
        sold_start=start,
        sold_end=end,
        price_low=low,
        price_high=high,
        retailers=retailers,
        upcs=upcs,
        models=models,
    )


def _remedy_kinds(remedies: tuple[str, ...], description: str) -> tuple[str, ...]:
    text = " ".join(remedies).lower() + " " + description.lower()
    return tuple(kind for kind, words in _REMEDY_WORDS.items() if any(w in text for w in words))


def parse_recall(payload: dict[str, Any]) -> Recall:
    contact = (payload.get("ConsumerContact") or "").strip()
    remedies = tuple(
        r["Name"].strip() for r in payload.get("Remedies", []) if (r.get("Name") or "").strip()
    )
    hazards = tuple(
        h["Name"].strip() for h in payload.get("Hazards", []) if (h.get("Name") or "").strip()
    )
    products = payload.get("Products") or [{}]
    email = _EMAIL.search(contact)
    phone = _PHONE.search(contact)
    return Recall(
        source="CPSC",
        recall_id=str(payload["RecallID"]),
        recall_number=str(payload.get("RecallNumber") or ""),
        recall_date=date.fromisoformat(payload["RecallDate"][:10]),
        title=(payload.get("Title") or "").strip(),
        description=(payload.get("Description") or "").strip(),
        url=payload.get("URL") or "",
        hazards=hazards,
        remedies=remedies,
        remedy_kinds=_remedy_kinds(remedies, payload.get("Description") or ""),
        contact_raw=contact,
        contact_email=email.group(0) if email else None,
        contact_phone=phone.group(0) if phone else None,
        units=products[0].get("NumberOfUnits") or None,
        constraints=extract_constraints(payload),
    )


def fetch(since: date, *, timeout: float = 60.0) -> list[Recall]:
    """Pull every notice published on or after `since`, newest first."""
    resp = httpx.get(
        BASE,
        params={"format": "json", "RecallDateStart": since.isoformat()},
        timeout=timeout,
    )
    resp.raise_for_status()
    recalls = [parse_recall(item) for item in resp.json()]
    recalls.sort(key=lambda r: r.recall_date, reverse=True)
    return recalls
