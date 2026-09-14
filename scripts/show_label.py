"""The question only the object can answer, answered by photographing it."""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.engine.verdict import Purchase, decide  # noqa: E402
from agent.feeds.cpsc import parse_recall  # noqa: E402
from agent.label import apply_reading, read_label, settle  # noqa: E402

ROOT = Path(__file__).parent.parent
RAW = json.loads((ROOT / "data" / "cpsc_2026.json").read_text())
recall = parse_recall(next(r for r in RAW if str(r["RecallNumber"]) == "26331"))

purchase = Purchase(
    purchase_id="h-2025-0091",
    description="BUILT LUUM Festive Forest 20 oz stainless tumbler",
    retailer="Winn-Dixie",
    purchased_on=date(2025, 1, 14),
)

before = decide(purchase, recall)
print(f"BEFORE   {before.outcome.value}")
for c in before.checks:
    print(f"  {c}")
print(f"  missing: {', '.join(before.missing)}")
print()

image = ROOT / "data" / "labels" / "luum_upc_label.png"
print(f"$ photograph of the label: {image.name}")
reading = read_label(image, asking_for="the UPC printed on the box")
print(f"  legible: {reading.image_legible}")
print(f"  {reading.summary[:180]}")
if reading.upc:
    print(f"  upc: {reading.upc.status} {reading.upc.value!r} (confidence {reading.upc.confidence})")
print()

enriched = apply_reading(
    {
        "purchase_id": purchase.purchase_id,
        "description": purchase.description,
        "retailer": purchase.retailer,
        "purchased_on": purchase.purchased_on.isoformat(),
        "price": None,
        "quantity": 1,
        "upc": None,
        "model": None,
    },
    reading,
)
after = settle(enriched, recall, reading)
print(f"AFTER    {after.outcome.value}")
for c in after.checks:
    print(f"  {c}")

print()
print("$ the same code against an unrelated recall")
other = parse_recall(next(r for r in RAW if str(r["RecallNumber"]) == "26702"))
print(f"         {settle(enriched, other, reading).outcome.value}   (an identifier settles it both ways)")
