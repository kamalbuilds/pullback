"""Shared shape for every recall source.

CPSC, NHTSA and openFDA publish different documents about the same thing: a
product that must come back. Each adapter reduces its source to this shape, so
the verdict engine never learns which regulator it is talking about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Constraints:
    """What a purchase record must satisfy for a recall to possibly apply."""

    sold_start: date | None = None
    sold_end: date | None = None
    price_low: float | None = None
    price_high: float | None = None
    retailers: tuple[str, ...] = ()
    upcs: tuple[str, ...] = ()
    models: tuple[str, ...] = ()

    @property
    def checkable(self) -> bool:
        return bool(
            self.upcs
            or self.models
            or (self.sold_start and self.sold_end)
            or (self.price_low is not None)
        )


@dataclass(frozen=True)
class Recall:
    recall_id: int
    recall_number: str
    recall_date: date
    title: str
    description: str
    url: str
    hazards: tuple[str, ...]
    remedies: tuple[str, ...]
    remedy_kinds: tuple[str, ...]
    contact_raw: str
    contact_email: str | None
    contact_phone: str | None
    units: str | None
    constraints: Constraints = field(default_factory=Constraints)

    @property
    def child_related(self) -> bool:
        text = f"{self.title} {self.description}".lower()
        return bool(
            re.search(
                r"\b(child|children|toddler|infant|baby|babies|nursery|crib|bassinet|"
                r"stroller|car seat|highchair|high chair|toy|toys|youth|kids)\b",
                text,
            )
        )



@dataclass(frozen=True)
class Recall:
    source: str
    recall_id: str
    recall_number: str
    recall_date: date
    title: str
    description: str
    url: str
    hazards: tuple[str, ...] = ()
    remedies: tuple[str, ...] = ()
    remedy_kinds: tuple[str, ...] = ()
    contact_raw: str = ""
    contact_email: str | None = None
    contact_phone: str | None = None
    units: str | None = None
    constraints: Constraints = field(default_factory=Constraints)

    @property
    def child_related(self) -> bool:
        import re

        return bool(
            re.search(
                r"\b(child|children|toddler|infant|baby|babies|nursery|crib|bassinet|"
                r"stroller|car seat|highchair|high chair|toy|toys|youth|kids)\b",
                f"{self.title} {self.description}".lower(),
            )
        )
