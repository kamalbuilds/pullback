"""Three regulators, three ways of saying what a thing is."""

import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.engine.scan import load_household, scan  # noqa: E402
from agent.run import load_recalls  # noqa: E402

recalls = load_recalls(since=date(2025, 1, 1), live=False)
household, purchases, _ = load_household()
print("corpus:", dict(Counter(r.source for r in recalls)), " household:", len(purchases), "things")
print()
actionable, cleared, counters = scan(purchases, recalls)
print(counters)
print()
for f in actionable:
    print(f"{f.verdict.outcome.value:14} {f.recall.source:8} {f.recall.recall_number:12} {f.purchase.purchase_id}")
    print(f"               {f.recall.title[:76]}")
print()
vehicle = [f for f in actionable if f.recall.source == "NHTSA"]
if vehicle:
    print("The car, decided on the model rather than on any text:")
    for c in vehicle[0].verdict.checks:
        print(f"  {c}")
