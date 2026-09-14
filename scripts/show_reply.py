"""What the company wrote back, and where the case stands now."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.reply import apply_reply, classify_reply  # noqa: E402

case = {
    "household": "kamal",
    "case_id": "43f87bbe8aaf308d",
    "status": "dispatched",
    "purchase": {"purchase_id": "amz-2026-0412", "description": "HABA Rainbow Rattle"},
    "recall": {"recall_number": "26719", "title": "HABA USA Recalls Rainbow Rattle"},
    "verdict": {"outcome": "MATCH", "checks": [], "missing": []},
    "timeline": [],
}

replies = {
    "a refund, confirmed": (
        "Thank you for contacting HABA USA regarding recall 26719. We have approved "
        "a full refund of $12.99 to your original payment method. Your reference is "
        "HABA-RF-88213. Please destroy the product as described in the notice."
    ),
    "an autoreply carrying a ticket number": (
        "Thank you for reaching out to HABA USA Consumer Relations. We have received "
        "your message and a representative will respond within 3-5 business days. "
        "Your inquiry reference number is HABA-INQ-004471."
    ),
}

for label, text in replies.items():
    print(f"=== {label} ===")
    print(" ", text[:150])
    classification = classify_reply(dict(case), text)
    updated = apply_reply(json.loads(json.dumps(case)), classification)
    print(f"  read as   {classification.get('outcome')}")
    print(f"  case is   {updated['status']}")
    print()
