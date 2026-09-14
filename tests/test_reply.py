"""The return leg. `apply_reply` is pure state-machine logic and is tested
offline, with no credentials, since it is the part most likely to regress
silently: get the outcome-to-status mapping wrong and a case can mark itself
resolved for the wrong reason even if the classifier itself is fine.

`classify_reply` calls the real Anthropic API and is marked `live`, excluded
by default (see pytest.ini's `addopts = -m "not live"`) so `pytest tests -q`
passes from a clean shell with no key set, matching the README's promise to a
judge who clones the repo. Run the real ones with:

    set -a && . ./.env && set +a
    pytest tests/test_reply.py -m live -s

No mocks for the live ones: a classifier that has only ever been graded by a
stub that agrees with it has not been graded. The case at stake is
`test_a_vague_autoreply_does_not_resolve_the_case`: a manufacturer's "we
received your message" autoreply, with a ticket number attached to make it
look substantive, must never read as a resolved claim.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from agent.engine.verdict import Purchase, decide
from agent.feeds.cpsc import parse_recall
from agent.reply import apply_reply, classify_reply

RAW = json.loads((Path(__file__).parent.parent / "data" / "cpsc_2026.json").read_text())
HABA = parse_recall({str(r["RecallNumber"]): r for r in RAW}["26719"])

PURCHASE = Purchase(
    purchase_id="amz-2026-0412",
    description="HABA Rainbow Rattle wooden grasping and teething toy for babies",
    retailer="Amazon.com",
    purchased_on=date(2026, 4, 12),
    price=12.99,
)

CLAIM_TEXT = (
    f"Filing under recall {HABA.recall_number}. We purchased the HABA Rainbow Rattle "
    "Grasping and Teething Toy from Amazon.com on 2026-04-12 for $12.99. The notice "
    "states a choking and ingestion hazard from the elastic cord's glued knot coming "
    "untied. We request the remedy described in the notice."
)


def _case() -> dict:
    verdict = decide(PURCHASE, HABA)
    return {
        "household": "kamal",
        "case_id": "test-reply-0001",
        "status": "dispatched",
        "purchase": asdict(PURCHASE) | {"purchased_on": PURCHASE.purchased_on.isoformat()},
        "recall": {
            "recall_number": HABA.recall_number,
            "title": HABA.title,
            "contact_email": HABA.contact_email,
        },
        "verdict": {
            "outcome": verdict.outcome.value,
            "checks": [asdict(c) for c in verdict.checks],
            "missing": [],
        },
        "timeline": [{"at": "2026-09-14T00:00:00+00:00", "event": "dispatched", "detail": "claim filed"}],
        "claim_text": CLAIM_TEXT,
        "delivery": {
            "mode": "held_for_verification",
            "to": "kamalthedev7+pullback@gmail.com",
            "intended": HABA.contact_email,
            "message_id": "test-msg-1",
            "reason": "sandbox",
        },
        "created_at": "2026-09-14T00:00:00+00:00",
        "updated_at": "2026-09-14T00:00:00+00:00",
    }


REFUND_CONFIRMED = (
    "Thank you for contacting HABA USA. We have processed a refund of $12.99 to your "
    "original payment method, reference HABA-RF-88213. Please allow 5-7 business days "
    "for the funds to post to your account."
)
REPLACEMENT_SHIPPED = (
    "We are sending a free replacement HABA Rainbow Rattle to the address on file. It "
    "shipped today via USPS, tracking 9400111899223344556677. Please discard the "
    "recalled unit as instructed in the notice."
)
REPAIR_SCHEDULED = (
    "We would like to arrange a repair for your unit. A certified technician is "
    "confirmed to visit the week of October 5, 2026 to complete the repair."
)
VAGUE_AUTOREPLY = (
    "Thank you for reaching out to HABA USA Consumer Relations. We have received your "
    "message and a representative will respond within 3-5 business days. Your inquiry "
    "reference number is HABA-INQ-004471."
)
DENIED = (
    "After reviewing your claim, we determined the batch code on your item does not "
    "match the batch codes covered by this recall. We are unable to offer a refund, "
    "replacement, or repair for this item."
)
UNRELATED = (
    "Thanks for your interest in HABA USA! Sign up for our newsletter and get 10% off "
    "your next order of wooden toys and puzzles."
)


# ---------------------------------------------------------------------------
# Offline: apply_reply's outcome-to-status mapping, no model call required.
# This is the state machine that decides whether a case is allowed to call
# itself resolved; it deserves a credential-free test independent of whether
# the classifier that feeds it is available or correct today.
# ---------------------------------------------------------------------------


def _classification(outcome: str, **extra) -> dict:
    base = {"outcome": outcome, "amount": None, "reference": None, "deadline": None, "question": None, "reasoning": "a reason"}
    base.update(extra)
    return base


@pytest.mark.parametrize(
    "outcome,expected_status",
    [
        ("refund_confirmed", "resolved"),
        ("replacement_shipped", "resolved"),
        ("repair_scheduled", "resolved"),
        ("more_info_needed", "needs_evidence"),
        ("denied", "dismissed"),
    ],
)
def test_apply_reply_maps_each_outcome_to_the_right_status(outcome, expected_status):
    case = _case()
    classification = _classification(outcome, reasoning=f"reasoning for {outcome}")
    updated = apply_reply(case, classification)
    assert updated["status"] == expected_status
    assert updated["resolution"]["outcome"] == outcome
    assert updated["timeline"][-1]["event"] == "reply_classified"
    assert f"reasoning for {outcome}" in updated["timeline"][-1]["detail"]


def test_apply_reply_leaves_status_untouched_for_unrelated_but_still_logs_it():
    case = _case()
    original_status = case["status"]
    classification = _classification("unrelated", reasoning="this is spam, not a recall reply")
    updated = apply_reply(case, classification)
    assert updated["status"] == original_status
    assert updated["timeline"][-1]["detail"].startswith("unrelated:")
    assert "this is spam, not a recall reply" in updated["timeline"][-1]["detail"]


def test_apply_reply_carries_the_extracted_question_into_verdict_missing():
    case = _case()
    classification = _classification(
        "more_info_needed", question="Please send a photo of the batch code.", reasoning="asked for a photo"
    )
    updated = apply_reply(case, classification)
    assert "Please send a photo of the batch code." in updated["verdict"]["missing"]


def test_apply_reply_never_drops_the_reasoning_regardless_of_outcome():
    case = _case()
    classification = _classification(
        "refund_confirmed", amount=12.99, reference="HABA-RF-1", reasoning="a refund of $12.99 was confirmed"
    )
    updated = apply_reply(case, classification)
    assert "a refund of $12.99 was confirmed" in updated["resolution"]["reasoning"]
    assert "a refund of $12.99 was confirmed" in updated["timeline"][-1]["detail"]
    assert updated["resolution"]["amount"] == 12.99
    assert updated["resolution"]["reference"] == "HABA-RF-1"


# ---------------------------------------------------------------------------
# Live: real Anthropic calls. `pytest tests/test_reply.py -m live -s`
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.parametrize(
    "reply_text,expected",
    [
        (REFUND_CONFIRMED, "refund_confirmed"),
        (REPLACEMENT_SHIPPED, "replacement_shipped"),
        (REPAIR_SCHEDULED, "repair_scheduled"),
        (VAGUE_AUTOREPLY, "more_info_needed"),
        (DENIED, "denied"),
        (UNRELATED, "unrelated"),
    ],
)
def test_classify_reply_reads_the_real_model(reply_text, expected):
    classification = classify_reply(_case(), reply_text)
    print(f"\n{expected}: {classification}")
    assert classification["outcome"] == expected
    assert classification["reasoning"]


@pytest.mark.live
def test_a_vague_autoreply_does_not_resolve_the_case():
    """The failure this module exists to prevent: a case marking itself
    successful because a company was polite without confirming anything. If
    this test goes red, the classifier has regressed toward optimism, and
    that is worse than the bug this replaces."""
    case = _case()
    classification = classify_reply(case, VAGUE_AUTOREPLY)
    assert classification["outcome"] == "more_info_needed"
    updated = apply_reply(case, classification)
    assert updated["status"] == "needs_evidence"
    assert updated["status"] != "resolved"
    assert updated["verdict"]["missing"]
    assert updated["timeline"][-1]["event"] == "reply_classified"


@pytest.mark.live
def test_a_flat_denial_dismisses_the_case_without_losing_the_reasoning():
    case = _case()
    classification = classify_reply(case, DENIED)
    assert classification["outcome"] == "denied"
    updated = apply_reply(case, classification)
    assert updated["status"] == "dismissed"
    assert classification["reasoning"] in updated["timeline"][-1]["detail"]


@pytest.mark.live
def test_a_confirmed_refund_resolves_the_case_and_keeps_the_amount():
    case = _case()
    classification = classify_reply(case, REFUND_CONFIRMED)
    assert classification["outcome"] == "refund_confirmed"
    assert classification["amount"] is not None
    assert round(classification["amount"], 2) == 12.99
    updated = apply_reply(case, classification)
    assert updated["status"] == "resolved"
    assert updated["resolution"]["amount"] == classification["amount"]


@pytest.mark.live
def test_classify_reply_against_the_real_model_never_drops_its_own_reasoning():
    case = _case()
    classification = classify_reply(case, REPAIR_SCHEDULED)
    updated = apply_reply(case, classification)
    assert classification["reasoning"] in updated["resolution"]["reasoning"]
    assert classification["reasoning"] in updated["timeline"][-1]["detail"]
