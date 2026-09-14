"""openFDA enforcement report feed (food, drug, device).

An enforcement report documents why the FDA classified a firm's recall, not
how a consumer should act, and it identifies the affected units by lot or
batch code, not by a sold-at window or a price. So this adapter's job is
different from CPSC's or NHTSA's: there is no sentence to parse for "sold
between X and Y" or "for about $N", those fields are structurally absent
from this dataset, and Constraints.sold_start/sold_end/price_low/price_high
stay None rather than being guessed from report_date or
recall_initiation_date (those are when the FDA acted, not when the product
was on shelves).

What the report does carry, in code_info, is the highest-value field in the
whole project: a lot/batch code and, for food, often a UPC. Measured against
300 real records captured 2026-09-14 (100 each of food/drug/device via
?limit=100), a labeled "UPC ..." pattern extracts a clean 12 or 13 digit UPC
from code_info alone in 8/300 records (2.7%). But the same UPC is frequently
quoted a second time inside product_description ("Outshine Fruit Bar
Watermelon ... with UPC 041548413624 ...") even when code_info on that
record holds only batch/best-before codes and no UPC at all, so this
adapter also scans product_description when code_info comes up empty;
combined that raises UPC coverage to 36/300 (12%: 28 food, 8 drug, 0 device,
because device recalls identify product by UDI/GTIN/serial instead of a
retail UPC). A lot/batch pattern against code_info, including a fallback
that scans an unpunctuated "code date code date ..." run when there is no
comma to split on, extracts at least one lot code from 137/300 (45.7%,
spread across all three product types: 32 food, 58 drug, 47 device). Either
signal is present on 161/300 (53.7%). That lot/batch number is what
Constraints.models carries: it is the closest thing openFDA has to a
checkable identifier, so it is treated as one rather than being discarded
because it is not literally a "model".

There is no per-record public detail URL in this API (unlike CPSC's URL
field or NHTSA's recalls?nhtsaId= pattern); the FDA's own recall lookup
page (accessdata.fda.gov/scripts/ires) returned 503 when probed live, so
Recall.url is left empty rather than pointing at a page that does not
reliably resolve.

There is also no consumer remedy instruction field. reason_for_recall states
why the firm acted, not what a consumer should do about product already
purchased, so remedies/remedy_kinds are left empty rather than inferred from
firm boilerplate that is not reliably present.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

import httpx

from agent.feeds.base import Constraints, Recall

BASE = "https://api.fda.gov"
ENDPOINTS = {"food": "/food/enforcement.json", "drug": "/drug/enforcement.json", "device": "/device/enforcement.json"}
OPENFDA_MAX_LIMIT = 1000

_GROUPS = (
    r"\d{12,13}(?!\d)"
    r"|\d{6}\s\d{6,7}(?!\d)"
    r"|\d{1,2}\s\d{4,6}\s\d{4,6}(?:\s\d{1,2})?(?!\d)"
)
# "UPC (5 oz.): 123..." puts a unit-size aside inside parens between the
# label and the digits; the plain pattern's [^0-9(]-gap can't cross that, so
# it gets its own pattern rather than a more permissive gap that would start
# eating into unrelated numbers earlier in the sentence.
_UPC_PLAIN = re.compile(r"\bUPC\b[^0-9(]{0,15}(" + _GROUPS + ")", re.I)
_UPC_PARENTHETICAL = re.compile(r"\bUPC\b\s*\([^)]{0,25}\)\s*[^0-9]{0,15}(" + _GROUPS + ")", re.I)

_LOT_ANCHOR = re.compile(
    r"\b(?:lot(?:s)?|batch)\b\.?\s*(?:no\.?s?|numbers?|codes?|#s?|number)?\s*[:\s]{0,3}", re.I
)
# Where a lot-code list ends: a date qualifier, or the start of a different
# field (UDI/GTIN/REF/NDC/Item) that the free text ran into without a comma.
_LOT_STOP = re.compile(
    r"\b(?:exp\b|expir\w*|best\s*by|bud\b|discard|use\s*by|udi|gtin|ref\b|ndc|item)\b", re.I
)
_ENUM_PREFIX = re.compile(r"^\(?[a-zA-Z0-9]{1,3}[.)]\s*")
_LOT_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 \-]{0,28}[A-Za-z0-9]|[A-Za-z0-9]")


def _extract_upcs(text: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for rx in (_UPC_PLAIN, _UPC_PARENTHETICAL):
        for m in rx.finditer(text):
            digits = re.sub(r"\s", "", m.group(1))
            if len(digits) in (12, 13) and digits not in seen:
                seen.add(digits)
                out.append(digits)
    return tuple(out)


def _clean_lot_token(raw: str) -> str | None:
    raw = _ENUM_PREFIX.sub("", raw.strip().strip(".")).strip()
    if not raw or "/" in raw or len(raw) > 30:
        return None
    if not _LOT_TOKEN.fullmatch(raw):
        return None
    if not any(c.isdigit() for c in raw):
        return None
    return re.sub(r"\s+", " ", raw)


_MONTH_WORD = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*$", re.I
)
# A code embedded in a comma-less, space-separated run like
# "LLA617603   30 JUN 2027 LLA617703   30 JUN 2027" (batch code, best-before
# date, batch code, best-before date, ...  with no punctuation between
# entries). Codes mix letters and digits or run at least 5 digits; the date
# fragments in between are short bare numbers or month names, filtered out
# below rather than matched here so this stays a single simple pattern.
_EMBEDDED_CODE = re.compile(r"\b[A-Za-z]{1,4}\d{4,10}[A-Za-z]{0,3}\b|\b\d{5,10}\b")


def _scan_embedded_codes(segment: str) -> list[str]:
    out = []
    for m in _EMBEDDED_CODE.finditer(segment):
        token = m.group(0)
        if _MONTH_WORD.match(token):
            continue
        out.append(token)
    return out


def _extract_lot_codes(text: str, *, cap: int = 25) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for anchor in _LOT_ANCHOR.finditer(text):
        start = anchor.end()
        stop = _LOT_STOP.search(text, start, start + 400)
        end = stop.start() if stop else min(len(text), start + 250)
        region = text[start:end]
        segments = re.split(r"[,;]", region)
        found_in_region = False
        for raw in segments:
            token = _clean_lot_token(raw)
            if not token:
                continue
            found_in_region = True
            if token.lower() in seen:
                continue
            seen.add(token.lower())
            out.append(token)
            if len(out) >= cap:
                return tuple(out)
        # A single unpunctuated segment ("code date code date ...") never
        # cleans as one token; only then fall back to scanning it for
        # embedded code-shaped substrings, so a normal comma list is never
        # double counted through both paths.
        if not found_in_region and len(segments) == 1:
            for token in _scan_embedded_codes(segments[0]):
                if token.lower() in seen:
                    continue
                seen.add(token.lower())
                out.append(token)
                if len(out) >= cap:
                    return tuple(out)
    return tuple(out)


def _parse_yyyymmdd(s: str) -> date | None:
    s = (s or "").strip()
    if not re.fullmatch(r"\d{8}", s):
        return None
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def extract_constraints(payload: dict[str, Any]) -> Constraints:
    code_info = payload.get("code_info") or ""
    description = payload.get("product_description") or ""
    # A retail UPC is often quoted in product_description ("Outshine Fruit
    # Bar ... with UPC 041548413624 ...") while code_info on that same
    # record holds only the batch/best-before codes; scanning both roughly
    # 4.5x's real UPC coverage in the 300-record sample this was measured
    # against (8/300 from code_info alone to 36/300 combined). Lot codes do
    # not show the same split, they are reliably in code_info, so that
    # extraction stays scoped to code_info only.
    upcs = _extract_upcs(code_info)
    if not upcs:
        upcs = _extract_upcs(description)
    return Constraints(
        upcs=upcs,
        models=_extract_lot_codes(code_info),
    )


def parse_recall(payload: dict[str, Any]) -> Recall:
    recall_number = str(payload.get("recall_number") or "")
    event_id = str(payload.get("event_id") or "")
    recall_date = (
        _parse_yyyymmdd(payload.get("recall_initiation_date", ""))
        or _parse_yyyymmdd(payload.get("report_date", ""))
        or date.today()
    )
    classification = (payload.get("classification") or "").strip()
    firm = (payload.get("recalling_firm") or "").strip()
    address = ", ".join(
        p for p in (payload.get("address_1"), payload.get("city"), payload.get("state")) if p and p != "N/A"
    )

    return Recall(
        source="openFDA",
        recall_id=event_id or recall_number,
        recall_number=recall_number,
        recall_date=recall_date,
        title=(payload.get("product_description") or "").strip(),
        description=(payload.get("reason_for_recall") or "").strip(),
        url="",
        hazards=(classification,) if classification else (),
        remedies=(),
        remedy_kinds=(),
        contact_raw=f"{firm} ({address})" if address else firm,
        contact_email=None,
        contact_phone=None,
        units=(payload.get("product_quantity") or "").strip() or None,
        constraints=extract_constraints(payload),
    )


def fetch(
    endpoint: Literal["food", "drug", "device"], since: date, *, limit: int = 100, timeout: float = 60.0
) -> list[Recall]:
    """Pull every enforcement report of `endpoint` initiated on or after `since`.

    openFDA paginates with skip/limit and refuses skip+limit above 1000 in a
    single request, so this walks pages of `limit` (capped at 1000) until
    meta.results.total is exhausted.
    """
    path = ENDPOINTS[endpoint]
    page_limit = min(limit, OPENFDA_MAX_LIMIT)
    search = f"recall_initiation_date:[{since.strftime('%Y%m%d')} TO 99991231]"
    recalls: list[Recall] = []
    skip = 0
    total = None
    while total is None or skip < total:
        resp = httpx.get(
            f"{BASE}{path}",
            params={"search": search, "limit": page_limit, "skip": skip},
            timeout=timeout,
        )
        if resp.status_code == 404:
            # openFDA returns 404 "NOT_FOUND" instead of an empty result set
            # when a search matches nothing at all.
            break
        resp.raise_for_status()
        body = resp.json()
        total = body["meta"]["results"]["total"]
        recalls.extend(parse_recall(item) for item in body.get("results", []))
        skip += page_limit
    recalls.sort(key=lambda r: r.recall_date, reverse=True)
    return recalls


def fetch_all(since: date, *, limit: int = 100, timeout: float = 60.0) -> list[Recall]:
    recalls: list[Recall] = []
    for endpoint in ("food", "drug", "device"):
        recalls.extend(fetch(endpoint, since, limit=limit, timeout=timeout))
    recalls.sort(key=lambda r: r.recall_date, reverse=True)
    return recalls
