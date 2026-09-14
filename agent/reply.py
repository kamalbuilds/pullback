"""The return leg: reading what a manufacturer actually said back.

`dispatch_remedy` used to be the end of the story, which meant Pullback could
never show a case actually closing. A manufacturer's reply is prose again,
the same problem `agent/engine/verdict.py` exists for on the other end, so the
same discipline applies: a model reads it, but it does not get to decide the
case is won. `classify_reply` returns a structured read; `apply_reply` is the
arithmetic that turns that read into a status a household can trust.

The failure mode this module exists to prevent is a specific one: an
autoreply that says "we received your message" gets read as a refund and the
case closes itself out having accomplished nothing. So the classifier is
told, explicitly and repeatedly, that an outcome without a concrete detail
attached, a dollar amount, a reference number, a scheduled date, is not a
resolution. It is `more_info_needed`, every time, no exceptions. Ambiguity
always resolves toward the household having to wait, never toward the case
marking itself successful.

Bedrock is not reachable on this AWS account (it is AISPL, Bedrock is not
offered there), so this talks to Anthropic directly, same as the rest of
Pullback.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from strands import Agent
from strands.models.anthropic import AnthropicModel

MODEL_ID = os.environ.get("PULLBACK_MODEL", "claude-sonnet-4-5-20250929")

Outcome = Literal[
    "refund_confirmed",
    "replacement_shipped",
    "repair_scheduled",
    "more_info_needed",
    "denied",
    "unrelated",
]

_STATUS_BY_OUTCOME: dict[str, str] = {
    "refund_confirmed": "resolved",
    "replacement_shipped": "resolved",
    "repair_scheduled": "resolved",
    "more_info_needed": "needs_evidence",
    "denied": "dismissed",
}


class ReplyClassification(BaseModel):
    outcome: Outcome = Field(
        description="Exactly one of the six outcomes. Never a resolved outcome unless "
        "the reply confirms a specific remedy action already approved or under way: a "
        "refund amount, a shipping/tracking or RMA number tied to a shipped replacement, "
        "or a specific scheduled repair date. A generic inquiry, ticket, or case number "
        "attached to a bare acknowledgment does not confirm anything and is always "
        "more_info_needed."
    )
    amount: float | None = Field(
        default=None, description="Dollar amount mentioned, if any (e.g. a refund amount), else null."
    )
    reference: str | None = Field(
        default=None, description="Any reference, case, or RMA number the manufacturer cited, else null."
    )
    deadline: str | None = Field(
        default=None,
        description="Any deadline or scheduled date mentioned, in plain text as written, else null.",
    )
    question: str | None = Field(
        default=None,
        description="Set only when outcome is more_info_needed. The single question the "
        "manufacturer is asking, verbatim or close to it. If the reply asks nothing "
        "specific (a bare acknowledgment), state plainly that no substantive answer was "
        "given and the household should wait for a concrete reply.",
    )
    reasoning: str = Field(description="One or two sentences: what in the reply's own wording led to this outcome.")


SYSTEM_PROMPT = """You classify a manufacturer's email reply to a recall claim a household already filed. You are reading, not deciding anything about eligibility; that was already settled before the claim was sent.

Read the original claim and the reply, then choose exactly one outcome:

refund_confirmed     the reply states a refund has been issued, approved, or is being processed, with an amount or an unambiguous commitment.
replacement_shipped  the reply states a replacement unit is being sent or has shipped.
repair_scheduled     the reply states a repair has been scheduled, or a repair kit is being sent with a concrete next step.
more_info_needed     the reply asks for something before it will act (a receipt, a photo, an order number), OR the reply is vague, an autoreply, or an acknowledgment that does not commit to any concrete action.
denied                the reply states plainly that the claim will not be honored, the product is not eligible, or the request is refused.
unrelated             the reply is not actually about this recall claim at all.

Be conservative. The three resolved outcomes (refund_confirmed, replacement_shipped, repair_scheduled) require a concrete detail in the reply's own words: a dollar figure, a reference or RMA number, or a specific scheduled date or shipping confirmation. A reply that only says "we've received your request and will follow up" or "thank you for contacting us" has confirmed nothing and must be more_info_needed, never a resolved outcome, no matter how positive its tone sounds. When genuinely torn between more_info_needed and a resolved outcome, choose more_info_needed. A household should never be told a case is won because a company was polite."""


def classify_reply(case: dict, reply_text: str) -> dict:
    """Classify one manufacturer reply against the claim Pullback sent.

    Returns a plain dict shaped like `ReplyClassification`: outcome, amount,
    reference, deadline, question, reasoning. A fresh Agent is built per call
    so classification carries no memory of other cases.
    """
    model = AnthropicModel(model_id=MODEL_ID, max_tokens=1024)
    agent = Agent(model=model, system_prompt=SYSTEM_PROMPT, structured_output_model=ReplyClassification)
    prompt = (
        f"Recall number: {case.get('recall', {}).get('recall_number', 'unknown')}\n\n"
        f"Claim Pullback sent on the household's behalf:\n{case.get('claim_text') or '(no claim text on file)'}\n\n"
        f"Manufacturer's reply:\n{reply_text}"
    )
    result = agent(prompt)
    classification: ReplyClassification = result.structured_output
    return classification.model_dump()


def apply_reply(case: dict, classification: dict) -> dict:
    """Fold a classified reply into `case`, mutated in place and returned.

    Status changes only for the four outcomes that mean something happened:
    resolved (the three concrete remedies), needs_evidence (more info was
    asked for, the question lands in verdict.missing so the household sees
    what to answer), dismissed (denied). `unrelated` and any future outcome
    leave status untouched but are still logged, because a case's history
    should show every reply it received, not just the ones that moved it.
    """
    outcome = classification["outcome"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    detail_bits = [classification.get("reasoning") or ""]
    if classification.get("amount") is not None:
        detail_bits.append(f"amount ${classification['amount']:,.2f}")
    if classification.get("reference"):
        detail_bits.append(f"ref {classification['reference']}")
    if classification.get("deadline"):
        detail_bits.append(f"deadline {classification['deadline']}")
    detail = f"{outcome}: " + " | ".join(b for b in detail_bits if b)

    case.setdefault("timeline", []).append({"at": now, "event": "reply_classified", "detail": detail})

    case["resolution"] = {
        "outcome": outcome,
        "amount": classification.get("amount"),
        "reference": classification.get("reference"),
        "deadline": classification.get("deadline"),
        "reasoning": classification.get("reasoning"),
        "classified_at": now,
    }

    new_status = _STATUS_BY_OUTCOME.get(outcome)
    if new_status is not None:
        case["status"] = new_status

    if outcome == "more_info_needed":
        question = classification.get("question") or "The manufacturer's reply did not confirm a remedy; awaiting a substantive response."
        verdict = case.setdefault("verdict", {})
        missing = list(verdict.get("missing") or [])
        if question not in missing:
            missing.append(question)
        verdict["missing"] = missing

    case["updated_at"] = now
    return case
