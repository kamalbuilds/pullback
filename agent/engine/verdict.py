"""The part of Pullback that decides.

The model never returns a verdict. It proposes candidate recalls and it reads
prose into `Constraints`. Everything that follows is arithmetic on dates, money
and identifiers, so a claim can always be explained by naming the checks that
passed and the values they passed on.

Three outcomes, and the middle one is the product:

    MATCH           every checkable constraint passed -> remedy may be dispatched
    NEEDS_EVIDENCE  the constraints that passed are not enough to be sure, and a
                    specific missing fact would settle it -> ask the human once
    NO_MATCH        a constraint failed -> say nothing, ever
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from agent.feeds.cpsc import Constraints, Recall

# A receipt's date is when it shipped or posted, not when it left the shelf.
DATE_SLACK = timedelta(days=45)
# Prices in notices are "about $180"; taxes, sales and bundles move the real one.
PRICE_SLACK = 0.25


class Outcome(str, Enum):
    MATCH = "MATCH"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    NO_MATCH = "NO_MATCH"


@dataclass(frozen=True)
class Purchase:
    purchase_id: str
    description: str
    retailer: str
    purchased_on: date
    price: float | None = None
    upc: str | None = None
    model: str | None = None
    quantity: int = 1


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str

    def __str__(self) -> str:
        return f"{'pass' if self.passed else 'FAIL'} {self.name}: {self.detail}"


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    checks: tuple[Check, ...]
    missing: tuple[str, ...] = ()
    recall_number: str = ""
    purchase_id: str = ""

    @property
    def passed(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.passed)

    @property
    def failed(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.passed)

    @property
    def evidence_id(self) -> str:
        """Identifies exactly which decision a dispatched claim rests on."""
        return f"{self.recall_number}:{self.purchase_id}:{self.outcome.value}"


_STOP = {
    "the", "and", "for", "with", "from", "size", "pack", "count", "set", "new",
    "inch", "in", "of", "a", "an", "by", "ct", "pcs", "pc", "piece", "pieces",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def _normalize_retailer(name: str) -> set[str]:
    name = re.sub(r"\b(inc|llc|ltd|co|corp|company|stores?|nationwide|online|com)\b", " ", name.lower())
    return {w for w in re.findall(r"[a-z]+", name) if len(w) > 2}


def _retailer_check(purchase: Purchase, constraints: Constraints) -> Check | None:
    if not constraints.retailers:
        return None
    bought = _normalize_retailer(purchase.retailer)
    if not bought:
        return None
    for listed in constraints.retailers:
        if bought & _normalize_retailer(listed):
            return Check("retailer", True, f"{purchase.retailer!r} appears in the notice")
    return Check(
        "retailer",
        False,
        f"{purchase.retailer!r} is not among {list(constraints.retailers)[:3]}",
    )


def _window_check(purchase: Purchase, constraints: Constraints) -> Check | None:
    start, end = constraints.sold_start, constraints.sold_end
    if not (start and end):
        return None
    lo, hi = start - DATE_SLACK, end + DATE_SLACK
    ok = lo <= purchase.purchased_on <= hi
    return Check(
        "sold_window",
        ok,
        f"bought {purchase.purchased_on} "
        f"{'inside' if ok else 'outside'} sold window {start}..{end}",
    )


def _price_check(purchase: Purchase, constraints: Constraints) -> Check | None:
    if purchase.price is None or constraints.price_low is None:
        return None
    unit = purchase.price / max(purchase.quantity, 1)
    lo = constraints.price_low * (1 - PRICE_SLACK)
    hi = (constraints.price_high or constraints.price_low) * (1 + PRICE_SLACK)
    ok = lo <= unit <= hi
    return Check(
        "price_band",
        ok,
        f"paid ${unit:,.2f} {'inside' if ok else 'outside'} "
        f"${constraints.price_low:,.2f}..${constraints.price_high or constraints.price_low:,.2f}",
    )


def _upc_check(purchase: Purchase, constraints: Constraints) -> Check | None:
    if not (purchase.upc and constraints.upcs):
        return None
    ok = purchase.upc.strip() in {u.strip() for u in constraints.upcs}
    return Check("upc", ok, f"UPC {purchase.upc} {'is' if ok else 'is not'} on the recall list")


def _model_check(purchase: Purchase, constraints: Constraints) -> Check | None:
    if not (purchase.model and constraints.models):
        return None
    mine = purchase.model.strip().lower()
    ok = any(mine == m.strip().lower() for m in constraints.models)
    return Check("model", ok, f"model {purchase.model} {'is' if ok else 'is not'} on the recall list")


def _text_check(purchase: Purchase, recall: Recall) -> Check:
    mine = _tokens(purchase.description)
    theirs = _tokens(f"{recall.title} {recall.description}")
    shared = mine & theirs
    overlap = len(shared) / max(len(mine), 1)
    return Check(
        "description_overlap",
        overlap >= 0.34,
        f"{overlap:.0%} of the receipt's words appear in the notice ({sorted(shared)[:6]})",
    )


def decide(purchase: Purchase, recall: Recall) -> Verdict:
    constraints = recall.constraints
    identifiers = [
        c for c in (_upc_check(purchase, constraints), _model_check(purchase, constraints)) if c
    ]
    circumstantial = [
        c
        for c in (
            _retailer_check(purchase, constraints),
            _window_check(purchase, constraints),
            _price_check(purchase, constraints),
        )
        if c
    ]
    text = _text_check(purchase, recall)
    checks = tuple(identifiers + circumstantial + [text])

    def result(outcome: Outcome, missing: tuple[str, ...] = ()) -> Verdict:
        return Verdict(
            outcome=outcome,
            checks=checks,
            missing=missing,
            recall_number=recall.recall_number,
            purchase_id=purchase.purchase_id,
        )

    # An identifier is the whole answer, in either direction.
    if identifiers:
        if all(c.passed for c in identifiers):
            return result(Outcome.MATCH)
        return result(Outcome.NO_MATCH)

    # Without an identifier, one failed circumstance is enough to stay silent.
    if any(not c.passed for c in circumstantial):
        return result(Outcome.NO_MATCH)
    if not text.passed:
        return result(Outcome.NO_MATCH)

    # Everything available passed. Is what was available enough?
    if len(circumstantial) >= 3:
        return result(Outcome.MATCH)

    missing: list[str] = []
    have = {c.name for c in circumstantial}
    if constraints.upcs and not purchase.upc:
        missing.append("the UPC printed on the box")
    if constraints.models and not purchase.model:
        missing.append("the model number on the product label")
    if "sold_window" not in have:
        missing.append("when it was bought")
    if "price_band" not in have:
        missing.append("what it cost")
    if "retailer" not in have:
        missing.append("where it was bought")
    return result(Outcome.NEEDS_EVIDENCE, tuple(missing) or ("a photo of the product label",))
