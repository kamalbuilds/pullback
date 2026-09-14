"""Measure what recall notices actually contain.

Every number in the README comes from here. Run it against the live feed and
the table regenerates itself, which is the only way those figures stay true as
the CPSC publishes more notices.

    python scripts/measure_feed.py            # live
    python scripts/measure_feed.py --cached   # the captured 2026 snapshot
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.feeds import cpsc  # noqa: E402

DATA = Path(__file__).parent.parent / "data"


def measure(recalls: list) -> list[tuple[str, str]]:
    n = len(recalls)
    if not n:
        return []

    def pct(count: int) -> str:
        return f"{count / n:.0%}"

    child = sum(1 for r in recalls if r.child_related)
    death = sum(1 for r in recalls if "death" in r.title.lower())
    upc = sum(1 for r in recalls if r.constraints.upcs)
    model = sum(1 for r in recalls if r.constraints.models)
    window = sum(1 for r in recalls if r.constraints.sold_start and r.constraints.sold_end)
    price = sum(1 for r in recalls if r.constraints.price_low is not None)
    email = sum(1 for r in recalls if r.contact_email)
    checkable = sum(1 for r in recalls if r.constraints.checkable)

    return [
        ("notices measured", str(n)),
        ("involve products for children", pct(child)),
        ('have the word "death" in the title', f"{death} of {n}"),
        ("carry a UPC you could look your purchase up by", pct(upc)),
        ("carry a model number", pct(model)),
        ("state where and when the product was sold", pct(window)),
        ("state what it cost", pct(price)),
        ("print an address to claim the remedy from", pct(email)),
        ("have at least one constraint worth checking", pct(checkable)),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cached", action="store_true", help="use the captured snapshot")
    parser.add_argument("--since", default="2026-01-01")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.cached:
        raw = json.loads((DATA / "cpsc_2026.json").read_text())
        recalls = [cpsc.parse_recall(item) for item in raw]
        source = "captured snapshot data/cpsc_2026.json"
    else:
        recalls = cpsc.fetch(date.fromisoformat(args.since))
        source = f"live CPSC feed since {args.since}"

    rows = measure(recalls)
    if args.as_json:
        print(json.dumps({"source": source, "measurements": dict(rows)}, indent=2))
        return 0

    print(f"source: {source}\n")
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label:<{width}}  {value:>12}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
