"""What the agent actually sees when it opens a recall notice.

The film opens here rather than on a headline, because the argument is not that
recalls are sad. The argument is that the record a regulator publishes does not
carry the two fields you would need to look your own purchase up by.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.engine.scan import load_household  # noqa: E402
from agent.feeds.cpsc import parse_recall  # noqa: E402

ROOT = Path(__file__).parent.parent
RAW = json.loads((ROOT / "data" / "cpsc_2026.json").read_text())
notice = parse_recall(next(r for r in RAW if str(r["RecallNumber"]) == "26761"))
_, purchases, _ = load_household()
receipt = next(p for p in purchases if p.purchase_id == "amz-2019-0714")


def line(label, value):
    print(f"  {label:<14} {value}")
    time.sleep(0.22)


print(f"$ parse CPSC recall {notice.recall_number}")
print()
time.sleep(0.6)
line("title", notice.title[:62])
line("published", notice.recall_date)
line("description", notice.description[:60])
line("hazard", (notice.hazards[0] if notice.hazards else "")[:60])
line("remedy", ", ".join(notice.remedy_kinds) or "not stated")
line("contact", notice.contact_email or notice.contact_phone or "unlisted")
print()
time.sleep(0.9)

c = notice.constraints
print("  the two fields you would look a purchase up by")
time.sleep(0.5)
line("upc", c.upcs or "EMPTY")
line("model_number", c.models or "EMPTY")
print()
time.sleep(1.4)

print("$ the purchase it is being asked to check")
print()
time.sleep(0.5)
line("description", receipt.description)
line("retailer", receipt.retailer)
line("bought", receipt.purchased_on)
line("price", f"${receipt.price}")
line("upc", receipt.upc or "EMPTY")
print()
time.sleep(0.9)

shared = set(receipt.description.lower().split()) & set(notice.description.lower().split())
print(f"  words in common between the two: {len(shared)}")
time.sleep(1.6)
