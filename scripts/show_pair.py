"""The comparison the whole product turns on, printed side by side."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.engine.scan import load_household  # noqa: E402
from agent.feeds.cpsc import parse_recall  # noqa: E402

RAW = json.loads((Path(__file__).parent.parent / "data" / "cpsc_2026.json").read_text())
notice = parse_recall(next(r for r in RAW if str(r["RecallNumber"]) == "26761"))
_, purchases, _ = load_household()
receipt = next(p for p in purchases if p.purchase_id == "amz-2019-0714")

print("THE NOTICE   CPSC", notice.recall_number, "  ", notice.recall_date)
print(" ", notice.description[:300])
print()
print("THE RECEIPT  ", receipt.purchase_id)
print(" ", receipt.description)
print(f"  {receipt.retailer}, {receipt.purchased_on}, ${receipt.price}")
print()
c = notice.constraints
print("WHAT THE NOTICE SAYS IS CHECKABLE")
print(f"  sold        {c.sold_start} to {c.sold_end}")
print(f"  price       ${c.price_low} to ${c.price_high}")
print(f"  retailers   {', '.join(c.retailers[:2])}")
print(f"  upc         {c.upcs or 'none published'}")
print(f"  model       {c.models or 'none published'}")
print()
print("Shared words between the two:", len(set(receipt.description.lower().split()) & set(notice.description.lower().split())))
