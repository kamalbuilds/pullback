"""Narrow 434 notices down to the few worth deciding on.

Deciding is cheap, but asking a model about every purchase against every notice
is not, and it is also the wrong shape: most pairs are obviously unrelated. So
the scan does the obvious rejections with arithmetic and hands the model only
the pairs where reading the prose could change the answer.
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
    return raw["household"], purchases, raw


def candidates(
    purchase: Purchase, recalls: list[Recall], *, floor: float = 0.18, top: int = 6
) -> list[Candidate]:
    """Recalls worth spending a decision on, best first.

    The floor is deliberately lower than the verdict engine's own overlap
    threshold. A candidate is a question, not an answer, and a notice that
    shares only a fifth of its words with a receipt can still be the one: "busy
    board" and "activity board" describe the same object.
    """
    mine = _tokens(purchase.description)
    if not mine:
        return []
    scored: list[Candidate] = []
    for recall in recalls:
        theirs = _tokens(f"{recall.title} {recall.description}")
        overlap = len(mine & theirs) / len(mine)
        if overlap >= floor:
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
