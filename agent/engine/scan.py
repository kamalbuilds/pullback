"""Narrow 434+ notices down to the few worth deciding on.

Deciding is cheap, but asking a model about every purchase against every
notice is not, and it is also the wrong shape: most pairs are obviously
unrelated. So the scan does the obvious rejections with arithmetic and hands
the model only the pairs where reading the prose could change the answer.

The three sources do not represent identity the same way, and candidate
generation has to know that or it silently breaks on two of them:

  CPSC     prose. 3% of notices carry a UPC, 0% a model number, so a receipt
           line is checked against a notice by shared vocabulary.
  NHTSA    a field, not a paragraph. A vehicle's identity is make, model and
           model year; there is no sold-at sentence to parse, and a car's
           description shares no vocabulary with a repair bulletin that means
           anything ("Honda Accord Sedan" against "SEAT BELTS:REAR/OTHER" is
           noise either way it scores). So NHTSA candidates come from an
           exact model match, never from text.
  openFDA  also a field: a lot/batch code or a UPC pulled out of code_info,
           never a sold window or a price (those are structurally absent from
           the schema, not just unparsed). Measured on 300 real records, 12%
           carry a UPC and 45.7% carry a lot code, so most food and drug
           purchases will not carry the identifier either, since a receipt
           does not usually record a lot code. Text is kept as a fallback for
           the records that do, weighted the same as CPSC's, but it is weak
           evidence next to an identifier: a lawyer's "reason for recall" is
           not a marketing description, and two lines sharing a few words is
           much less telling here than it is for CPSC prose.

One scoring function, `_score`, carries all three rules instead of three
copies of the scan loop: it tries an exact identifier match first (this is
never wrong when it fires, for any source, since it is the same field
`decide()` itself treats as dispositive), and only falls back to text when
the source in question actually publishes text worth reading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from agent.engine.verdict import Outcome, Purchase, Verdict, _tokens, decide
from agent.feeds.base import Recall

DATA = Path(__file__).parent.parent.parent / "data"


@dataclass(frozen=True)
class Candidate:
    purchase: Purchase
    recall: Recall
    overlap: float

    @property
    def key(self) -> str:
        return f"{self.purchase.purchase_id}|{self.recall.recall_number}"


@dataclass(frozen=True)
class Finding:
    purchase: Purchase
    recall: Recall
    verdict: Verdict


def _vehicle_purchases(vehicles: list[dict]) -> list[Purchase]:
    """A household vehicle recast as a `Purchase`, so it flows through the one
    scan loop everything else does.

    A vehicle has no retailer and no receipt date in the CPSC sense, and
    `Purchase` has no field for "make", so the two facts that actually settle
    a vehicle recall have to travel through fields built for something else:

      retailer     left "" (no dealer is on file). `_retailer_check` only
                   fires when a recall lists retailers, and NHTSA never does,
                   so this never gates anything.
      purchased_on set to the mid-point of the model year, since no delivery
                   date is on file either. NHTSA's own sold-window constraint
                   is a coarse [year-1, year+1] band built for exactly this
                   uncertainty (see `nhtsa._sold_window`), so any date inside
                   the model year clears it; the exact day is inert.
      model        the vehicle's model ("accord"), so `_model_check` can
                   compare it against the campaign's `constraints.models`
                   the same exact-string way it already compares a CPSC
                   model number. This is the field that actually decides a
                   vehicle case: once it is set, `decide()` treats it as an
                   identifier and settles the verdict on it alone, so
                   retailer and purchased_on never get consulted.

    `_model_check` matches on model text only, not make, which is the
    identifier NHTSA's own feed provides for a vehicle recall; the feed
    carries no make-scoped identifier for this adapter to check against
    instead. Real households rarely reuse another manufacturer's model word,
    and it is not a risk any captured recall data exercises: the bound is
    set by what NHTSA's data contains, not by a choice scan.py makes.
    """
    return [
        Purchase(
            purchase_id=v["purchase_id"],
            description=v["description"],
            retailer="",
            purchased_on=date(v["model_year"], 6, 1),
            model=v["model"],
        )
        for v in vehicles
    ]


def load_household(path: Path | None = None) -> tuple[str, list[Purchase], dict]:
    raw = json.loads((path or DATA / "household.json").read_text())
    purchases = [
        Purchase(
            purchase_id=p["purchase_id"],
            description=p["description"],
            retailer=p["retailer"],
            purchased_on=date.fromisoformat(p["purchased_on"]),
            price=p.get("price"),
            quantity=p.get("quantity", 1),
            upc=p.get("upc"),
            model=p.get("model"),
        )
        for p in raw["purchases"]
    ]
    purchases.extend(_vehicle_purchases(raw.get("vehicles", [])))
    return raw["household"], purchases, raw


def _text_overlap(purchase: Purchase, recall: Recall) -> float:
    mine = _tokens(purchase.description)
    if not mine:
        return 0.0
    theirs = _tokens(f"{recall.title} {recall.description}")
    return len(mine & theirs) / len(mine)


def _identifier_overlap(purchase: Purchase, recall: Recall) -> float | None:
    """An exact UPC or model/lot match, whichever field the source populated.

    Returns 1.0 (never a partial score) so an identifier hit always outranks
    every text-scored candidate, or None if neither identifier is checkable,
    so the caller knows to fall through to text instead of reading a 1.0 as
    "no identifier, but a perfect text match".
    """
    constraints = recall.constraints
    if purchase.upc and constraints.upcs:
        if purchase.upc.strip() in {u.strip() for u in constraints.upcs}:
            return 1.0
    if purchase.model and constraints.models:
        mine = purchase.model.strip().lower()
        if any(mine == m.strip().lower() for m in constraints.models):
            return 1.0
    return None


def _score(purchase: Purchase, recall: Recall) -> float | None:
    """One purchase-to-notice score, however this source represents identity.

    None means "not worth deciding on"; `candidates()` drops it before it
    ever reaches the model or `decide()`.
    """
    identifier = _identifier_overlap(purchase, recall)
    if identifier is not None:
        return identifier
    if recall.source == "NHTSA":
        # No identifier means no vehicle match: NHTSA text is a repair
        # bulletin, not a product description, and scoring it against a
        # receipt line would only manufacture noise.
        return None
    return _text_overlap(purchase, recall)


def candidates(
    purchase: Purchase, recalls: list[Recall], *, floor: float = 0.18, top: int = 6
) -> list[Candidate]:
    """Recalls worth spending a decision on, best first.

    The floor is deliberately lower than the verdict engine's own overlap
    threshold for text-scored pairs. A candidate is a question, not an
    answer, and a notice that shares only a fifth of its words with a receipt
    can still be the one: "busy board" and "activity board" describe the same
    object. An identifier match always scores 1.0, so it always clears the
    floor and is never filtered out by it.
    """
    scored: list[Candidate] = []
    for recall in recalls:
        overlap = _score(purchase, recall)
        if overlap is not None and overlap >= floor:
            scored.append(Candidate(purchase, recall, overlap))
    scored.sort(key=lambda c: c.overlap, reverse=True)
    return scored[:top]


def scan(
    purchases: list[Purchase], recalls: list[Recall]
) -> tuple[list[Finding], list[Finding], dict[str, int]]:
    """Returns (actionable, silently_cleared, counters).

    Actionable means MATCH or NEEDS_EVIDENCE: a human may hear about these.
    Silently cleared means the engine looked and said no, which is most of the
    work and none of the noise.
    """
    actionable: list[Finding] = []
    cleared: list[Finding] = []
    counters = {"purchases": len(purchases), "recalls": len(recalls), "pairs_considered": 0}

    for purchase in purchases:
        for candidate in candidates(purchase, recalls):
            counters["pairs_considered"] += 1
            verdict = decide(purchase, candidate.recall)
            finding = Finding(purchase, candidate.recall, verdict)
            if verdict.outcome is Outcome.NO_MATCH:
                cleared.append(finding)
            else:
                actionable.append(finding)

    counters["actionable"] = len(actionable)
    counters["cleared"] = len(cleared)
    counters["matched"] = sum(1 for f in actionable if f.verdict.outcome is Outcome.MATCH)
    counters["needs_evidence"] = sum(
        1 for f in actionable if f.verdict.outcome is Outcome.NEEDS_EVIDENCE
    )
    return actionable, cleared, counters
