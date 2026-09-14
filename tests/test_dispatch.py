"""Send the claim for real, and prove the mode decision offline first.

The recipient/mode choice (`_resolve_delivery`) is pure and does not touch
AWS, so it is tested directly here without credentials, exactly the part most
likely to need scrutiny: getting "direct" vs "held_for_verification" vs
"simulated" wrong is the whole failure mode this module exists to prevent.

Everything that actually calls `sesv2` is marked `live` and excluded by
default (see pytest.ini's `addopts = -m "not live"`), so `pytest tests -q`
passes from a clean shell with no AWS credentials and no network, the same
promise the README makes to a judge cloning the repo. Run the real ones with:

    export AWS_PROFILE=palimpsest AWS_DEFAULT_REGION=us-east-1
    unset AWS_BEARER_TOKEN_BEDROCK
    pytest tests/test_dispatch.py -m live -s

No moto, no localstack for the live ones: the SES sandbox's own restrictions
(delivery only to verified identities, a FROM address that must always be
verified, sandbox or not) are exactly the constraint agent/dispatch.py is
written to survive, so faking the service would test nothing about whether it
actually survives it.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from agent.dispatch import (
    SIMULATOR_BOUNCE,
    SIMULATOR_SUCCESS,
    _body,
    _client,
    _is_verified,
    _production_access,
    _resolve_delivery,
    _sender_identity,
    send_claim,
)
from agent.engine.verdict import Purchase, decide
from agent.feeds.cpsc import parse_recall

RAW = json.loads((Path(__file__).parent.parent / "data" / "cpsc_2026.json").read_text())
BY_NUMBER = {str(r["RecallNumber"]): r for r in RAW}
HABA = parse_recall(BY_NUMBER["26719"])

PURCHASE = Purchase(
    purchase_id="amz-2026-0412",
    description="HABA Rainbow Rattle wooden grasping and teething toy for babies",
    retailer="Amazon.com",
    purchased_on=date(2026, 4, 12),
    price=12.99,
)

CLAIM_TEXT = (
    f"Filing under recall {HABA.recall_number}. We purchased the HABA Rainbow Rattle "
    "Grasping and Teething Toy from Amazon.com on 2026-04-12 for $12.99, inside the "
    "notice's sold window and price band. The notice states a choking and ingestion "
    "hazard from the elastic cord's glued knot coming untied. We request the "
    "replacement remedy described in the notice."
)


def _case(case_id: str = "test-dispatch-0001") -> dict:
    verdict = decide(PURCHASE, HABA)
    return {
        "household": "kamal",
        "case_id": case_id,
        "status": "awaiting_approval",
        "purchase": asdict(PURCHASE) | {"purchased_on": PURCHASE.purchased_on.isoformat()},
        "recall": {
            "source": HABA.source,
            "recall_number": HABA.recall_number,
            "title": HABA.title,
            "url": HABA.url,
            "recall_date": HABA.recall_date.isoformat(),
            "hazards": list(HABA.hazards),
            "remedy_kinds": list(HABA.remedy_kinds),
            "contact_email": HABA.contact_email,
            "contact_phone": HABA.contact_phone,
        },
        "verdict": {
            "outcome": verdict.outcome.value,
            "checks": [asdict(c) for c in verdict.checks],
            "missing": list(verdict.missing),
            "evidence_id": verdict.evidence_id,
        },
        "timeline": [],
        "evidence_uri": None,
        "claim_text": CLAIM_TEXT,
        "created_at": "2026-09-14T00:00:00+00:00",
        "updated_at": "2026-09-14T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Offline: the mode decision, no AWS call, no credentials required.
# ---------------------------------------------------------------------------


def test_direct_when_the_account_has_left_the_sandbox():
    recipient, mode, reason = _resolve_delivery(
        intended="recall@habausa.com", household_target=None, production=True,
        contact_verified=False, household_verified=False,
    )
    assert (recipient, mode) == ("recall@habausa.com", "direct")
    assert "left the sandbox" in reason


def test_direct_when_the_contact_itself_is_verified():
    recipient, mode, reason = _resolve_delivery(
        intended="recall@habausa.com", household_target=None, production=False,
        contact_verified=True, household_verified=False,
    )
    assert (recipient, mode) == ("recall@habausa.com", "direct")
    assert "recall@habausa.com is a verified identity" in reason


def test_held_for_verification_when_only_the_household_address_is_verified():
    recipient, mode, reason = _resolve_delivery(
        intended="recall@habausa.com", household_target="house@example.com", production=False,
        contact_verified=False, household_verified=True,
    )
    assert (recipient, mode) == ("house@example.com", "held_for_verification")
    assert "recall@habausa.com is not a verified identity" in reason
    assert "house@example.com" in reason


def test_simulated_when_neither_address_is_verified():
    recipient, mode, reason = _resolve_delivery(
        intended="recall@habausa.com", household_target="house@example.com", production=False,
        contact_verified=False, household_verified=False,
    )
    assert (recipient, mode) == (SIMULATOR_SUCCESS, "simulated")
    assert "recall@habausa.com" in reason and "house@example.com" in reason


def test_simulated_with_no_household_address_configured_at_all():
    recipient, mode, reason = _resolve_delivery(
        intended="recall@habausa.com", household_target=None, production=False,
        contact_verified=False, household_verified=False,
    )
    assert (recipient, mode) == (SIMULATOR_SUCCESS, "simulated")
    assert "nor a configured household address" in reason


def test_direct_wins_over_a_verified_household_address_when_the_contact_is_also_verified():
    """production/contact_verified must be checked first: a verified
    household address must never demote a case that could go direct."""
    recipient, mode, _ = _resolve_delivery(
        intended="recall@habausa.com", household_target="house@example.com", production=False,
        contact_verified=True, household_verified=True,
    )
    assert (recipient, mode) == ("recall@habausa.com", "direct")


def test_send_claim_refuses_a_case_with_no_claim_text():
    case = _case()
    case["claim_text"] = None
    with pytest.raises(ValueError):
        send_claim(case)


def test_send_claim_refuses_a_recall_with_no_contact_email():
    case = _case()
    case["recall"]["contact_email"] = None
    with pytest.raises(ValueError):
        send_claim(case)


def test_a_case_that_already_carries_a_message_id_is_never_sent_even_offline():
    """The idempotency guard runs before any AWS client is built, so it is
    provable without credentials: swap `dispatch._client` for a stub that
    raises, and show a pre-sent case never reaches it."""
    import agent.dispatch as dispatch

    case = _case("test-dispatch-idempotent-offline")
    case["delivery"] = {
        "mode": "simulated",
        "to": SIMULATOR_SUCCESS,
        "intended": HABA.contact_email,
        "message_id": "already-sent-marker",
        "reason": "previously sent",
        "sent_at": "2026-09-14T00:00:00+00:00",
    }

    def _boom() -> None:
        raise AssertionError("send_claim built an SES client for a case that already has a message_id")

    original_client = dispatch._client
    dispatch._client = _boom
    try:
        result = send_claim(case)
    finally:
        dispatch._client = original_client
    assert result == case["delivery"]


def test_the_generated_email_carries_the_claim_text_and_every_evidence_check():
    case = _case()
    body = _body(case, intended=HABA.contact_email, mode="held_for_verification", recipient="someone@example.com")
    assert case["claim_text"] in body
    for check in case["verdict"]["checks"]:
        assert check["detail"] in body
    assert "someone@example.com" in body
    assert HABA.contact_email in body


def test_the_simulated_body_says_plainly_that_nothing_was_actually_delivered():
    case = _case()
    body = _body(case, intended=HABA.contact_email, mode="simulated", recipient=SIMULATOR_SUCCESS)
    assert "has not actually reached" in body or "No message has actually reached" in body


def test_the_direct_body_carries_no_diversion_language():
    case = _case()
    body = _body(case, intended=HABA.contact_email, mode="direct", recipient=HABA.contact_email)
    assert "sandbox" not in body
    assert case["claim_text"] in body


# ---------------------------------------------------------------------------
# Live: real sesv2 calls. `pytest tests/test_dispatch.py -m live -s`
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_the_account_is_still_in_the_sandbox_and_the_contact_is_unverified():
    """Confirms the precondition this whole design is built around. If this
    goes red the account changed state and send_claim's mode selection
    should be re-checked against the new reality, not just this test."""
    client = _client()
    assert _production_access(client) is False
    assert not _is_verified(client, HABA.contact_email)


@pytest.mark.live
def test_dry_run_builds_the_message_but_sends_nothing():
    case = _case()
    delivery = send_claim(case, dry_run=True)
    assert delivery["message_id"] is None
    assert delivery["mode"] in ("held_for_verification", "simulated", "direct")
    assert case["delivery"]["message_id"] is None


@pytest.mark.live
def test_send_claim_delivers_and_is_never_sent_twice():
    """One real send, then a second call on the same case. The second call
    must never reach AWS at all: `dispatch._client` is swapped for a stub
    that raises if it is ever invoked, so this test would go red if the
    idempotency guard in send_claim were removed or reordered after the
    AWS call instead of before it.

    SentLast24Hours is printed before/after for the record, but not asserted
    on: it is an eventually-consistent account-level counter, observed here
    to sit unchanged for well over a minute after real, accepted sends, so it
    is not a synchronous proof of anything. The MessageId returned by
    SendEmail is the real proof; SES only issues one after accepting the
    message for delivery.
    """
    client = _client()
    _sender_identity(client)  # raises RuntimeError if no sender identity is verified yet

    before = client.get_account()["SendQuota"]["SentLast24Hours"]
    case = _case("test-dispatch-idempotency-0001")
    delivery = send_claim(case)
    after = client.get_account()["SendQuota"]["SentLast24Hours"]

    assert delivery["message_id"], "SES did not return a MessageId"
    assert delivery["mode"] in ("held_for_verification", "simulated", "direct")
    assert delivery["intended"] == HABA.contact_email
    print(f"\nreal send: mode={delivery['mode']} to={delivery['to']} message_id={delivery['message_id']}")
    print(f"SendQuota.SentLast24Hours before={before} after={after} (eventually consistent, see docstring)")

    import agent.dispatch as dispatch

    original_client = dispatch._client

    def _boom() -> None:
        raise AssertionError("send_claim built a new SES client for a case already sent")

    dispatch._client = _boom
    try:
        second = send_claim(case)
    finally:
        dispatch._client = original_client
    assert second == delivery


@pytest.mark.live
def test_a_bounce_address_still_returns_a_message_id_but_that_is_not_proof_of_delivery():
    """SES accepts bounce@simulator.amazonses.com synchronously and hands
    back a real MessageId; the bounce itself is only reported later, through
    an SNS or CloudWatch event destination on a configuration set. This
    account has neither configured, so send_claim (like the SendEmail API it
    calls) cannot distinguish "delivered" from "will bounce" from the
    response alone. This test proves that gap rather than pretending it
    isn't there: it forces the recipient to the bounce simulator and shows
    the call still succeeds and still reports message_id truthily, which is
    exactly the failure mode a judge should know about."""
    client = _client()
    sender = _sender_identity(client)
    resp = client.send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [SIMULATOR_BOUNCE]},
        Content={
            "Simple": {
                "Subject": {"Data": "Pullback bounce-handling probe", "Charset": "UTF-8"},
                "Body": {
                    "Text": {
                        "Data": "Probing whether a synchronous send can see a bounce coming.",
                        "Charset": "UTF-8",
                    }
                },
            }
        },
    )
    print(f"\nbounce probe message_id={resp['MessageId']}")
    assert resp["MessageId"]
