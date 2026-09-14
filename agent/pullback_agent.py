"""The Pullback agent.

What the model is for: reading. A recall notice is a paragraph written by a
lawyer describing packaging, and a receipt line is whatever a retailer felt
like printing. Deciding those are the same object is reading comprehension.

What the model is not for: deciding. Whether the purchase falls inside the
notice's sold window, price band and retailer list is arithmetic, and it is
done in agent/engine/verdict.py where no prompt can reach it.

The seam between those two facts is enforced twice, on purpose:

  1. `judge_identity` accepts the model's read but returns the verdict computed
     from it, so the model learns the outcome instead of choosing it.
  2. `RemedyVeto`, a BeforeToolCallEvent hook, cancels `dispatch_remedy` unless
     the ledger holds a MATCH verdict and a claim for that exact case. A model
     that decides to file a claim anyway does not file a claim.

Delete the hook and Pullback becomes a program that emails strangers about
products they may not own. That is the test this design is built to pass.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.vended_interventions import HumanInTheLoop
from strands.models.anthropic import AnthropicModel

from agent.engine.scan import Finding, candidates, load_household
from agent.engine.verdict import IdentityAssertion, Outcome, Purchase, Verdict, decide
from agent.feeds.base import Recall

MODEL_ID = os.environ.get("PULLBACK_MODEL", "claude-sonnet-4-5-20250929")
DATA = Path(__file__).parent.parent / "data"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def case_id(household: str, purchase_id: str, recall_number: str) -> str:
    """Same purchase, same notice, same case, however many times we run."""
    import hashlib

    return hashlib.sha256(f"{household}|{purchase_id}|{recall_number}".encode()).hexdigest()[:16]


@dataclass
class Ledger:
    """What this run has established, and the only thing the veto trusts."""

    household: str
    purchases: dict[str, Purchase]
    recalls: dict[str, Recall]
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    claims: dict[str, str] = field(default_factory=dict)
    cases: dict[str, dict] = field(default_factory=dict)
    dispatched: set[str] = field(default_factory=set)
    approvals: set[str] = field(default_factory=set)
    pending_approval: set[str] = field(default_factory=set)
    considered: int = 0

    def record(self, cid: str, verdict: Verdict) -> None:
        self.verdicts[cid] = verdict

    def may_dispatch(self, cid: str) -> str | None:
        """Returns the reason dispatch is refused, or None if it may proceed."""
        verdict = self.verdicts.get(cid)
        if verdict is None:
            return f"no verdict has been computed for case {cid}"
        if verdict.outcome is not Outcome.MATCH:
            failed = ", ".join(c.name for c in verdict.failed) or "insufficient evidence"
            return (
                f"case {cid} is {verdict.outcome.value}, not MATCH "
                f"(failing: {failed}). A claim may only be filed on a MATCH."
            )
        if cid not in self.claims:
            return f"case {cid} has no claim text written yet"
        if cid in self.dispatched:
            return f"case {cid} was already dispatched; it will not be sent twice"
        return None


class RemedyVeto(HookProvider):
    """The check that cannot be argued with, because it is not in the prompt."""

    def __init__(self, ledger: Ledger, log: Callable[[str, str], None]) -> None:
        self.ledger = ledger
        self.log = log

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.inspect)

    def inspect(self, event: BeforeToolCallEvent) -> None:
        if event.tool_use.get("name") != "dispatch_remedy":
            return
        cid = (event.tool_use.get("input") or {}).get("case_id", "")
        refusal = self.ledger.may_dispatch(cid)
        if refusal:
            self.log("veto", refusal)
            event.cancel_tool = f"REFUSED by the remedy veto: {refusal}"


def approval_gate(ledger: Ledger, log: Callable[[str, str], None]) -> HumanInTheLoop:
    """The one call a person has to make.

    Everything else the agent does is reversible: reading notices, computing a
    verdict, opening a case, drafting a claim. Sending a message to a company in
    someone's name is not, so it is the single tool that can never be trusted
    away. `allowed_tools` is a wildcard with `dispatch_remedy` negated, which in
    Strands means it always requires approval even if a caller has trusted
    everything else in this session.

    In an unattended run nobody is at a terminal, so the gate does not block. It
    records the case as waiting for a person and lets the pass continue to the
    next purchase. The console is where the answer comes back: an approved case
    id is handed to the next run, and the same gate then lets it through.

    The veto hook still runs underneath this. Approval is permission to send a
    claim that already passed every check; it is not permission to skip them.
    """

    def ask(prompt: str, **_: Any) -> str:
        try:
            payload = json.loads(prompt.split("Input: ", 1)[1])
            cid = payload.get("case_id", "")
        except (IndexError, ValueError):
            cid = ""
        if cid and cid in ledger.approvals:
            log("approved", f"{cid} was approved by the household")
            return "yes"
        ledger.pending_approval.add(cid)
        case = ledger.cases.get(cid)
        if case is not None:
            case["status"] = "awaiting_approval"
            case["timeline"].append(
                {
                    "at": _now(),
                    "event": "approval_requested",
                    "detail": "The claim is written and waiting for the household to send it.",
                }
            )
        log("awaiting_approval", f"{cid} is drafted and waiting for a person")
        return "no"

    def evaluate(response: Any, **_: Any) -> bool:
        return str(response).strip().lower() in {"y", "yes", "approve", "approved"}

    return HumanInTheLoop(allowed_tools=["*", "!dispatch_remedy"], ask=ask, evaluate=evaluate)


class CaseSink:
    """Where cases go when the run ends. Both implementations are real."""

    def write(self, case: dict) -> str:
        raise NotImplementedError


class FileSink(CaseSink):
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DATA / "cases"
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, case: dict) -> str:
        path = self.root / f"{case['case_id']}.json"
        path.write_text(json.dumps(case, indent=2, default=str))
        return str(path)


class DynamoSink(CaseSink):
    def __init__(self) -> None:
        from agent.store import CaseStore

        self.store = CaseStore()

    def write(self, case: dict) -> str:
        self.store.put_case(case)
        return f"dynamodb://pullback-cases/{case['household']}/{case['case_id']}"


SYSTEM_PROMPT = """You work for one household. Your job is to find out whether anything they own has been recalled, and if so, to get the manufacturer's remedy actually delivered.

You are reading a regulator's prose against a retailer's receipt lines. That comparison is your job and you are good at it: "LED projecting finger lights party favors 50 pieces" and "Finger Light Toys, 50 pieces in a box in white, blue, red and green" are the same object even though they share almost no words.

What is not your job: deciding whether a claim may be filed. Dates, prices and retailers are checked outside you, and you will be told the result. If you are told NO_MATCH, that is the answer. Do not argue, do not retry with different wording, do not file anyway. A wrong claim costs a real person their credibility with a real company.

Work like this, one purchase at a time:

1. Call candidate_notices for the purchase.
2. For each candidate worth considering, call judge_identity with your honest read: is this the same product, how confident are you, and why. Cite the specific wording that convinced you. If a notice is about a different object, say same_product=false and move on.
3. judge_identity returns the computed verdict. On MATCH, call open_case, then write_claim, then dispatch_remedy.

   dispatch_remedy is the one thing you cannot do alone. Sending a message to a company in someone's name is not yours to decide, so it waits for the household to approve it. When the answer comes back "waiting for a person", that is the system working. Say so once and move on to the next purchase. Do not retry it, do not reword the claim to get a different answer, and do not tell the household it was sent.
4. On NEEDS_EVIDENCE, call open_case and then ask_household with the single most useful question. Ask for one thing, not a form.
5. On NO_MATCH, do nothing further with that pair. Silence is the correct output and most of your work will be silence.

When you write a claim, write what a competent adult would send: the recall number, what they own, the evidence that it is inside the recall, and the specific remedy the notice offers. No greetings padded with feeling, no apology, no invented order numbers, no urgency theatre. Six sentences at most.

Hazards in these notices include infant death. Say what the hazard is plainly and once. Do not soften it and do not dramatise it."""


def households() -> dict[str, list[dict]]:
    """Every household the scheduled pass should check, in wire shape.

    One file today. This is the seam a second household arrives through, and
    the scheduled Lambda calls it rather than reaching into data/ itself.
    Purchases come back as plain dicts because that is what crosses into the
    Lambda's case records and into DynamoDB; the dataclass is a local detail.
    """
    household, purchases, _ = load_household()
    return {
        household: [
            {
                "purchase_id": p.purchase_id,
                "description": p.description,
                "retailer": p.retailer,
                "purchased_on": p.purchased_on.isoformat(),
                "price": p.price,
                "quantity": p.quantity,
                "upc": p.upc,
                "model": p.model,
            }
            for p in purchases
        ]
    }


def build_agent(
    household: str,
    purchases: list[Purchase],
    recalls: list[Recall],
    *,
    sink: CaseSink | None = None,
    model_id: str = MODEL_ID,
    approvals: set[str] | None = None,
) -> tuple[Agent, Ledger, list[dict]]:
    ledger = Ledger(
        household=household,
        purchases={p.purchase_id: p for p in purchases},
        recalls={r.recall_number: r for r in recalls},
        approvals=set(approvals or ()),
    )
    sink = sink or FileSink()
    events: list[dict] = []

    def log(event: str, detail: str) -> None:
        entry = {"at": _now(), "event": event, "detail": detail}
        events.append(entry)
        print(json.dumps(entry), flush=True)

    @tool
    def candidate_notices(purchase_id: str) -> str:
        """Recall notices worth reading against one purchase, best first.

        Args:
            purchase_id: The household purchase to look for, e.g. amz-2026-0412.
        """
        purchase = ledger.purchases.get(purchase_id)
        if purchase is None:
            return f"No purchase {purchase_id}. Known: {sorted(ledger.purchases)}"
        found = candidates(purchase, list(ledger.recalls.values()))
        ledger.considered += len(found)
        if not found:
            log("cleared", f"{purchase_id}: no notice resembles this purchase")
            return "No candidate notices. This purchase is clear."
        lines = [
            f"purchase: {purchase.description!r} from {purchase.retailer} "
            f"on {purchase.purchased_on} for ${purchase.price}"
        ]
        for c in found:
            r = c.recall
            lines.append(
                f"\n[{r.recall_number}] {r.title}\n"
                f"  hazard: {(r.hazards[0] if r.hazards else 'not stated')[:240]}\n"
                f"  notice describes: {r.description[:400]}\n"
                f"  remedy offered: {', '.join(r.remedy_kinds) or 'not stated'}"
            )
        return "\n".join(lines)

    @tool
    def judge_identity(
        purchase_id: str, recall_number: str, same_product: bool, confidence: float, reason: str
    ) -> str:
        """Record your read on whether a purchase and a notice describe one product, and get the verdict.

        Your read replaces the lexical word-overlap test only. Retailer, sold
        window, price band and UPC are checked regardless of what you say here.

        Args:
            purchase_id: The household purchase.
            recall_number: The notice you are comparing it against.
            same_product: True if the receipt line and the notice describe the same object.
            confidence: 0.0 to 1.0, your honest confidence.
            reason: The specific wording that decided it for you.
        """
        purchase = ledger.purchases.get(purchase_id)
        recall = ledger.recalls.get(recall_number)
        if purchase is None or recall is None:
            return f"Unknown purchase {purchase_id} or notice {recall_number}."
        assertion = IdentityAssertion(
            same_product=same_product,
            confidence=confidence,
            reason=reason,
            asserted_by=model_id,
        )
        verdict = decide(purchase, recall, assertion)
        cid = case_id(household, purchase_id, recall_number)
        ledger.record(cid, verdict)
        log(
            "verdict",
            f"{purchase_id} vs {recall_number}: {verdict.outcome.value} "
            f"({len(verdict.passed)} checks passed, {len(verdict.failed)} failed)",
        )
        detail = "\n".join(f"  {c}" for c in verdict.checks)
        extra = f"\nMissing: {', '.join(verdict.missing)}" if verdict.missing else ""
        return f"case_id {cid}\nverdict {verdict.outcome.value}\n{detail}{extra}"

    @tool
    def open_case(purchase_id: str, recall_number: str) -> str:
        """Persist a case so it survives this run.

        Args:
            purchase_id: The household purchase.
            recall_number: The notice it was checked against.
        """
        cid = case_id(household, purchase_id, recall_number)
        verdict = ledger.verdicts.get(cid)
        if verdict is None:
            return f"Nothing to open: call judge_identity for {purchase_id} and {recall_number} first."
        purchase = ledger.purchases[purchase_id]
        recall = ledger.recalls[recall_number]
        status = "awaiting_approval" if verdict.outcome is Outcome.MATCH else "needs_evidence"
        case = {
            "household": household,
            "case_id": cid,
            "status": status,
            "purchase": {
                "purchase_id": purchase.purchase_id,
                "description": purchase.description,
                "retailer": purchase.retailer,
                "purchased_on": purchase.purchased_on.isoformat(),
                "price": purchase.price,
                "quantity": purchase.quantity,
                "upc": purchase.upc,
                "model": purchase.model,
            },
            "recall": {
                "source": recall.source,
                "recall_number": recall.recall_number,
                "title": recall.title,
                "url": recall.url,
                "recall_date": recall.recall_date.isoformat(),
                "hazards": list(recall.hazards),
                "remedy_kinds": list(recall.remedy_kinds),
                "contact_email": recall.contact_email,
                "contact_phone": recall.contact_phone,
            },
            "verdict": {
                "outcome": verdict.outcome.value,
                "checks": [asdict(c) for c in verdict.checks],
                "missing": list(verdict.missing),
                "evidence_id": verdict.evidence_id,
            },
            "timeline": [{"at": _now(), "event": "opened", "detail": f"verdict {verdict.outcome.value}"}],
            "evidence_uri": None,
            "claim_text": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        ledger.cases[cid] = case
        where = sink.write(case)
        log("case_opened", f"{cid} {status} -> {where}")
        return f"Case {cid} open with status {status}."

    @tool
    def write_claim(case_id_arg: str, claim_text: str) -> str:
        """Attach the message that will be sent to the company.

        Args:
            case_id_arg: The case this claim belongs to.
            claim_text: The full message. Must name the recall number.
        """
        case = ledger.cases.get(case_id_arg)
        if case is None:
            return f"No open case {case_id_arg}."
        number = case["recall"]["recall_number"]
        if number not in claim_text:
            return f"Rejected: the claim must cite recall number {number} so the company can route it."
        if len(claim_text.split()) > 220:
            return "Rejected: too long. Six sentences at most."
        ledger.claims[case_id_arg] = claim_text
        case["claim_text"] = claim_text
        case["timeline"].append({"at": _now(), "event": "claim_written", "detail": f"{len(claim_text.split())} words"})
        case["updated_at"] = _now()
        sink.write(case)
        log("claim_written", f"{case_id_arg} cites {number}")
        return "Claim attached."

    @tool
    def dispatch_remedy(case_id: str) -> str:
        """File the claim with the company named on the notice.

        Refused unless the verdict is MATCH and a claim is attached.

        Args:
            case_id: The case to file.
        """
        case = ledger.cases.get(case_id)
        if case is None:
            return f"No open case {case_id}."
        recipient = case["recall"]["contact_email"] or case["recall"]["contact_phone"] or "unlisted"
        ledger.dispatched.add(case_id)
        case["status"] = "dispatched"
        case["timeline"].append(
            {"at": _now(), "event": "dispatched", "detail": f"claim filed with {recipient}"}
        )
        case["updated_at"] = _now()
        sink.write(case)
        log("dispatched", f"{case_id} -> {recipient}")
        return f"Filed with {recipient}. Tracking the reply on this case."

    @tool
    def ask_household(case_id: str, question: str) -> str:
        """Interrupt the human, once, with the single question that settles the case.

        Args:
            case_id: The case that is stuck.
            question: One plain question. Not a form.
        """
        case = ledger.cases.get(case_id)
        if case is None:
            return f"No open case {case_id}."
        case["timeline"].append({"at": _now(), "event": "asked_household", "detail": question})
        case["status"] = "needs_evidence"
        case["updated_at"] = _now()
        sink.write(case)
        log("asked_household", f"{case_id}: {question}")
        return "Asked. The case waits until they answer."

    tools = [
        candidate_notices,
        judge_identity,
        open_case,
        write_claim,
        dispatch_remedy,
        ask_household,
    ]

    agent = Agent(
        model=AnthropicModel(model_id=model_id, max_tokens=4096),
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        hooks=[RemedyVeto(ledger, log)],
        interventions=[approval_gate(ledger, log)],
    )
    return agent, ledger, events
