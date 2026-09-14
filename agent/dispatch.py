"""Filing the claim for real, against an account that will not let it happen.

The sending account is in the SES sandbox: 200 messages a day, one a second,
and delivery refused to any address that is not itself a verified identity.
That restriction is on the *recipient*. The FROM address has a separate,
unconditional rule that sandbox and production both enforce: SES will never
send a message whose FromEmailAddress is not itself a verified identity or a
verified domain. There is no address, simulator included, that lets a
send_email call skip that check; `success@simulator.amazonses.com` only
relaxes where the account is allowed to deliver *to*, not who it will accept
mail *from*. So a sender identity has to exist and be verified before any of
this can send anything at all, sandbox, simulator, or otherwise.

Given a verified sender, three things can happen to a claim, in order:

  direct                the recall's own contact_email is a verified identity,
                         or the account has left the sandbox: deliver there.
  held_for_verification  contact_email is not verified, but the household's
                         own address is: deliver there instead, unaltered
                         claim text and all, with the true intended recipient
                         stamped into the body and an
                         X-Pullback-Intended-Recipient header.
  simulated              neither address is verified: prove the send actually
                         works against AWS's own mailbox simulator rather
                         than claim a delivery that could not have happened.

The case record says which of the three occurred, in a field the console can
render honestly (`delivery.mode`), never silently collapsing "simulated" or
"held_for_verification" into language that implies the manufacturer was
reached. Verified-ness and sandbox state are both read from the SES API on
every call, never hardcoded, so the day production access is granted this
same code starts filing with manufacturers with no edit, and the day the
household's own address verifies, "simulated" cases start landing in a real
inbox with no edit either.

A case that already carries `delivery.message_id` is never sent again. Filing
the same claim twice is not a retry, it is spam from a household's own agent,
so the guard runs before any AWS call is made, not after.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
DATA = Path(__file__).parent.parent / "data"

# pullback@getava.xyz is the domain Pullback verified with SES (Easy DKIM,
# verified over DNS, no inbox click required). PULLBACK_SENDER overrides it;
# this is only the default so nothing about the sending domain is hardcoded
# into the decision of whether it is actually usable, see _sender_identity.
DEFAULT_SENDER = "pullback@getava.xyz"

# AWS's own recipient addresses for exercising SES without a real inbox on the
# other end. Only the recipient side is fake; the send itself, the quota it
# consumes and the MessageId it returns are all real.
SIMULATOR_SUCCESS = "success@simulator.amazonses.com"
SIMULATOR_BOUNCE = "bounce@simulator.amazonses.com"
SIMULATOR_COMPLAINT = "complaint@simulator.amazonses.com"
SIMULATOR_SUPPRESSED = "suppressionlist@simulator.amazonses.com"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client() -> Any:
    return boto3.client("sesv2", region_name=REGION)


def _production_access(client: Any) -> bool:
    return bool(client.get_account().get("ProductionAccessEnabled"))


def _is_verified(client: Any, email: str) -> bool:
    if not email:
        return False
    try:
        resp = client.get_email_identity(EmailIdentity=email)
    except client.exceptions.NotFoundException:
        return False
    return bool(resp.get("VerifiedForSendingStatus"))


def _sending_identity_ok(client: Any, address: str) -> bool:
    """True if `address` can be used as a FromEmailAddress: either the exact
    address is a verified EMAIL_ADDRESS identity, or its domain is a verified
    DOMAIN identity (SES lets any local-part send once the domain itself is
    verified, which is how a domain identity like getava.xyz is meant to be
    used, rather than verifying every mailbox at it individually)."""
    if _is_verified(client, address):
        return True
    domain = address.rsplit("@", 1)[-1] if "@" in address else None
    return bool(domain) and _is_verified(client, domain)


def _sender_identity(client: Any) -> str:
    """The From address this account is actually allowed to send as.

    `PULLBACK_SENDER` overrides it, defaulting to `DEFAULT_SENDER`. That
    candidate is only used if the account can actually send as it right now
    (checked live, never assumed); otherwise this falls back to scanning the
    account for any other verified identity, an EMAIL_ADDRESS used as-is or a
    DOMAIN used as its default `pullback@` mailbox.
    """
    candidate = os.environ.get("PULLBACK_SENDER", DEFAULT_SENDER)
    if _sending_identity_ok(client, candidate):
        return candidate

    resp = client.list_email_identities()
    for identity in resp.get("EmailIdentities", []):
        if identity.get("VerificationStatus") != "SUCCESS":
            continue
        if identity.get("IdentityType") == "EMAIL_ADDRESS" and identity.get("SendingEnabled", True):
            return identity["IdentityName"]
        if identity.get("IdentityType") == "DOMAIN":
            return f"pullback@{identity['IdentityName']}"
    raise RuntimeError(
        "no verified SES sending identity (address or domain) in this account/region; "
        "verify one with `aws sesv2 create-email-identity --email-identity <addr-or-domain>`"
    )


def _household_email_from_config() -> str | None:
    """The household's real address, read from the same household record the
    rest of Pullback reads purchases from, so send_claim never needs its own
    copy of who the household is."""
    path = DATA / "household.json"
    if not path.exists():
        return None
    contact = (json.loads(path.read_text()).get("contact") or {})
    return contact.get("email")


def _evidence_block(case: dict) -> str:
    checks = (case.get("verdict") or {}).get("checks") or []
    lines = ["Evidence checked before this claim was filed:"]
    for check in checks:
        mark = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"  [{mark}] {check.get('name', '')}: {check.get('detail', '')}")
    return "\n".join(lines)


def _subject(case: dict) -> str:
    number = case["recall"]["recall_number"]
    title = case["recall"]["title"]
    return f"Recall claim {number}: {title}"[:200]


def _resolve_delivery(
    *,
    intended: str,
    household_target: str | None,
    production: bool,
    contact_verified: bool,
    household_verified: bool,
) -> tuple[str, str, str]:
    """The recipient/mode/reason decision, pure and offline-testable.

    Everything that can change the answer, whether the account left the
    sandbox and whether an address is verified, is decided by live SES calls
    before this runs; this function only has to get the three-way choice
    right given those facts, so it is exactly what a credential-free test
    should exercise instead of a real send.
    """
    if production or contact_verified:
        reason = (
            "SES account has left the sandbox; delivering directly"
            if production
            else f"{intended} is a verified identity in this account; delivering directly"
        )
        return intended, "direct", reason
    if household_verified:
        reason = (
            f"SES account is in the sandbox and {intended} is not a verified identity; "
            f"held for {household_target}, the household's own verified address"
        )
        return household_target, "held_for_verification", reason
    who = f"nor {household_target}" if household_target else "nor a configured household address"
    reason = (
        f"SES account is in the sandbox; neither {intended} {who} is a verified "
        "identity, so this send was proven against the AWS SES mailbox simulator "
        "instead of a real inbox"
    )
    return SIMULATOR_SUCCESS, "simulated", reason


def _body(case: dict, *, intended: str, mode: str, recipient: str) -> str:
    parts = [case.get("claim_text") or "", "", _evidence_block(case)]
    if mode == "held_for_verification":
        parts += [
            "",
            f"This message is addressed to {intended}, the contact printed on the "
            "recall notice, but the Pullback sending account is currently in the "
            "Amazon SES sandbox, which only delivers to verified addresses. Until "
            f"{intended} is verified or the account leaves the sandbox, this claim "
            f"is being routed to {recipient}, the household's own verified address, "
            "so the household can see and forward it.",
        ]
    elif mode == "simulated":
        parts += [
            "",
            f"This message is addressed to {intended}, the contact printed on the "
            "recall notice, but the Pullback sending account is currently in the "
            "Amazon SES sandbox and neither that address nor a household address is "
            "yet verified, so this send was proven against the AWS SES mailbox "
            f"simulator ({recipient}) instead of a real inbox. No message has "
            "actually reached the manufacturer or the household yet.",
        ]
    return "\n".join(parts)


def send_claim(case: dict, *, to: str | None = None, dry_run: bool = False) -> dict:
    """Send `case["claim_text"]` toward the recall's contact, honestly.

    `to` is the household's own address, the one this claim should land in
    when the true contact cannot be reached directly. When omitted it comes
    from `PULLBACK_HOUSEHOLD_EMAIL`, then from `data/household.json`'s own
    contact record. Unlike the sender identity, `to` does not need to be
    pre-verified to be *used*: it is always set as Reply-To, since a
    manufacturer replying to a direct send should reach the household
    regardless. It only needs to be verified to be used as the *recipient*
    in `held_for_verification` mode; SES sandbox would otherwise refuse the
    send outright.

    Returns the `delivery` dict to attach to the case: `mode` is "direct",
    "held_for_verification" or "simulated" (see module docstring). Idempotent:
    if `case["delivery"]["message_id"]` is already set, that same dict is
    returned unchanged and no AWS call is made. `dry_run=True` runs every
    check and builds the message but skips the actual `send_email` call,
    returning a delivery record with `message_id: None`.
    """
    existing = case.get("delivery") or {}
    if existing.get("message_id"):
        return existing

    if not case.get("claim_text"):
        raise ValueError(f"case {case.get('case_id')} has no claim_text to send")

    intended = (case.get("recall") or {}).get("contact_email")
    if not intended:
        raise ValueError(
            f"case {case.get('case_id')} recall carries no contact_email; "
            "there is no address send_claim can file this claim with"
        )

    client = _client()
    sender = _sender_identity(client)
    household_target = to or os.environ.get("PULLBACK_HOUSEHOLD_EMAIL") or _household_email_from_config()
    reply_to = household_target or sender

    production = _production_access(client)
    contact_verified = _is_verified(client, intended)
    household_verified = bool(household_target) and _is_verified(client, household_target)

    recipient, mode, reason = _resolve_delivery(
        intended=intended,
        household_target=household_target,
        production=production,
        contact_verified=contact_verified,
        household_verified=household_verified,
    )

    subject = _subject(case)
    body = _body(case, intended=intended, mode=mode, recipient=recipient)
    headers = [{"Name": "X-Pullback-Intended-Recipient", "Value": intended}]

    message_id = None
    if not dry_run:
        try:
            resp = client.send_email(
                FromEmailAddress=sender,
                Destination={"ToAddresses": [recipient]},
                ReplyToAddresses=[reply_to],
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                        "Headers": headers,
                    }
                },
            )
        except ClientError as exc:
            raise RuntimeError(
                f"SES rejected the claim for case {case.get('case_id')}: {exc}"
            ) from exc
        message_id = resp["MessageId"]

    delivery = {
        "mode": mode,
        "to": recipient,
        "intended": intended,
        "message_id": message_id,
        "reason": reason,
        "sent_at": _now(),
    }
    case["delivery"] = delivery
    return delivery
