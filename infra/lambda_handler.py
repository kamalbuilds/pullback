"""The background run: what makes Pullback work with nobody watching.

Invoked two ways:

  1. EventBridge Scheduler (pullback-daily, pullback-frequent) -> `event` is
     whatever the schedule sends (empty JSON by default). Runs the full
     pass and returns a summary dict.
  2. Lambda Function URL -> `event` carries API Gateway v2 payload shape
     with `requestContext.http`. The console calls this to trigger a run
     on demand. Same pass, wrapped in an HTTP response with CORS headers.

The pass itself, every time: refresh the CPSC recall feed into
pullback-recalls, then for every household the agent brain knows about, run
every purchase against every recall through agent.engine.verdict.decide,
and persist every non-NO_MATCH result as a durable case with an evidence
pack. agent.pullback_agent (the piece that knows which households exist and
what they bought) is being built in parallel and may not be importable yet;
when it isn't, the feed refresh still runs for real and the pass logs
exactly why matching was skipped, rather than inventing households.

Logging is one JSON object per line so CloudWatch Logs Insights (and a demo
screen) can read it without a custom parser.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any

from agent.engine.verdict import Purchase as VerdictPurchase
from agent.engine.verdict import Outcome, decide
from agent.evidence import write_pack
from agent.feeds import cpsc
from agent.feeds.base import Constraints, Recall
from agent.store import CaseStore, RecallStore

FEED_LOOKBACK_DAYS = 120
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _log(event: str, **fields: Any) -> None:
    line = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    print(json.dumps(line, default=str))


def _purchase_to_dict(purchase: Any) -> dict:
    purchased_on = purchase.purchased_on
    return {
        "purchase_id": purchase.purchase_id,
        "description": purchase.description,
        "retailer": purchase.retailer,
        "purchased_on": purchased_on.isoformat() if hasattr(purchased_on, "isoformat") else purchased_on,
        "price": purchase.price,
        "quantity": purchase.quantity,
        "upc": purchase.upc,
        "model": purchase.model,
    }


def _load_households() -> dict[str, list[dict]]:
    """Two sources, tried in order, neither one fabricated:

    1. agent.pullback_agent.households() -- the full LLM-driven agent brain's
       own registry, if and when it defines one. That module is being built
       in parallel and today exposes build_agent(household, purchases,
       recalls, ...) instead, which this Lambda does not drive directly
       because running it needs the `strands` SDK and an Anthropic API key,
       neither of which belongs in this deploy layer (the key is a secret;
       the user wires it in, not this script). This branch exists so that
       once pullback_agent does publish a households() registry, this
       Lambda picks it up with no further change.
    2. agent.engine.scan.load_household() -- the real household purchase
       record at data/household.json (a genuine receipt list, not a
       fixture invented here; see that file's own note field). This is
       the deterministic path exercised today: decide() runs with no
       identity assertion, which is exactly its designed fallback.
    """
    try:
        from agent.pullback_agent import households as _households  # type: ignore
    except ImportError as exc:
        _log("pullback_agent_unavailable", reason=str(exc))
    except AttributeError as exc:
        _log("pullback_agent_no_households_fn", reason=str(exc))
    else:
        try:
            result = _households()
            if isinstance(result, dict) and result:
                return result
            _log("pullback_agent_empty", got=type(result).__name__)
        except Exception as exc:
            _log("pullback_agent_error", reason=str(exc), traceback=traceback.format_exc())

    try:
        from agent.engine.scan import load_household
    except ImportError as exc:
        _log("scan_unavailable", reason=str(exc))
        return {}
    try:
        household_name, purchases, _raw = load_household()
    except Exception as exc:
        _log("load_household_error", reason=str(exc), traceback=traceback.format_exc())
        return {}
    purchase_dicts = [_purchase_to_dict(p) for p in purchases]
    _log("loaded_household_from_scan", household=household_name, purchases=len(purchase_dicts))
    return {household_name: purchase_dicts}


def _recall_from_item(item: dict) -> Recall:
    """Rebuild a Recall dataclass (with real date objects) from the plain
    dict RecallStore.all_recalls() returns, so agent.engine.verdict can
    run its date-arithmetic checks against it."""
    c = item.get("constraints") or {}
    constraints = Constraints(
        sold_start=date.fromisoformat(c["sold_start"]) if c.get("sold_start") else None,
        sold_end=date.fromisoformat(c["sold_end"]) if c.get("sold_end") else None,
        price_low=float(c["price_low"]) if c.get("price_low") is not None else None,
        price_high=float(c["price_high"]) if c.get("price_high") is not None else None,
        retailers=tuple(c.get("retailers") or ()),
        upcs=tuple(c.get("upcs") or ()),
        models=tuple(c.get("models") or ()),
    )
    return Recall(
        source=item.get("source", ""),
        recall_id=item.get("recall_id", ""),
        recall_number=item.get("recall_number", ""),
        recall_date=date.fromisoformat(item["recall_date"]) if item.get("recall_date") else date.today(),
        title=item.get("title", ""),
        description=item.get("description", ""),
        url=item.get("url", ""),
        hazards=tuple(item.get("hazards") or ()),
        remedies=tuple(item.get("remedies") or ()),
        remedy_kinds=tuple(item.get("remedy_kinds") or ()),
        contact_raw=item.get("contact_raw", ""),
        contact_email=item.get("contact_email"),
        contact_phone=item.get("contact_phone"),
        units=item.get("units"),
        constraints=constraints,
    )


def _recall_summary(recall_item: dict) -> dict:
    """The slice of a stored recall that belongs on a case, per the shared
    case-shape contract with the console."""
    return {
        "source": recall_item.get("source", ""),
        "recall_number": recall_item.get("recall_number", ""),
        "title": recall_item.get("title", ""),
        "url": recall_item.get("url", ""),
        "recall_date": recall_item.get("recall_date", ""),
        "hazards": list(recall_item.get("hazards") or ()),
        "remedy_kinds": list(recall_item.get("remedy_kinds") or ()),
        "contact_email": recall_item.get("contact_email"),
        "contact_phone": recall_item.get("contact_phone"),
    }


_STATUS_FOR_OUTCOME = {
    Outcome.MATCH: "awaiting_approval",
    Outcome.NEEDS_EVIDENCE: "needs_evidence",
}


def _build_case(household: str, purchase: dict, recall_item: dict, verdict, case_store: CaseStore) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cid = case_store.case_id(household, purchase["purchase_id"], recall_item["recall_number"])
    return {
        "household": household,
        "case_id": cid,
        "status": _STATUS_FOR_OUTCOME[verdict.outcome],
        "purchase": purchase,
        "recall": _recall_summary(recall_item),
        "verdict": {
            "outcome": verdict.outcome.value,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in verdict.checks
            ],
            "missing": list(verdict.missing),
            "evidence_id": verdict.evidence_id,
        },
        "timeline": [
            {"at": now, "event": "verdict_computed", "detail": f"{verdict.outcome.value} against {recall_item.get('recall_number')}"}
        ],
        "evidence_uri": "",
        "claim_text": "",
        "created_at": now,
        "updated_at": now,
    }


def _to_verdict_purchase(purchase: dict) -> VerdictPurchase:
    purchased_on = purchase.get("purchased_on")
    if isinstance(purchased_on, str):
        purchased_on = date.fromisoformat(purchased_on)
    return VerdictPurchase(
        purchase_id=purchase["purchase_id"],
        description=purchase.get("description", ""),
        retailer=purchase.get("retailer", ""),
        purchased_on=purchased_on,
        price=float(purchase["price"]) if purchase.get("price") is not None else None,
        upc=purchase.get("upc"),
        model=purchase.get("model"),
        quantity=int(purchase.get("quantity") or 1),
    )


def run_once(household_filter: str | None = None) -> dict:
    case_store = CaseStore()
    recall_store = RecallStore()

    summary = {
        "recalls_fetched": 0,
        "recalls_stored": 0,
        "households_processed": 0,
        "purchases_checked": 0,
        "cases_created": 0,
        "cases_updated": 0,
        "errors": [],
    }

    since = date.today() - timedelta(days=FEED_LOOKBACK_DAYS)
    _log("feed_refresh_start", source="CPSC", since=since.isoformat())
    try:
        fetched = cpsc.fetch(since)
        summary["recalls_fetched"] = len(fetched)
        stored = recall_store.put_recalls(fetched)
        summary["recalls_stored"] = stored
        _log("feed_refresh_done", source="CPSC", fetched=len(fetched), stored=stored)
    except Exception as exc:
        _log("feed_refresh_error", source="CPSC", reason=str(exc), traceback=traceback.format_exc())
        summary["errors"].append(f"feed_refresh:CPSC:{exc}")

    all_recall_items = recall_store.all_recalls()
    _log("recall_pool", count=len(all_recall_items))

    households = _load_households()
    if household_filter:
        households = {k: v for k, v in households.items() if k == household_filter}
    if not households:
        _log("matching_skipped", reason="no households available from agent.pullback_agent")
        return summary

    for household, purchases in households.items():
        summary["households_processed"] += 1
        _log("household_start", household=household, purchases=len(purchases))
        for purchase in purchases:
            summary["purchases_checked"] += 1
            v_purchase = _to_verdict_purchase(purchase)
            for recall_item in all_recall_items:
                try:
                    recall = _recall_from_item(recall_item)
                    verdict = decide(v_purchase, recall)
                except Exception as exc:
                    _log(
                        "decide_error",
                        household=household,
                        purchase_id=purchase.get("purchase_id"),
                        recall_number=recall_item.get("recall_number"),
                        reason=str(exc),
                    )
                    summary["errors"].append(f"decide:{purchase.get('purchase_id')}:{exc}")
                    continue
                if verdict.outcome == Outcome.NO_MATCH:
                    continue

                cid = case_store.case_id(household, purchase["purchase_id"], recall_item["recall_number"])
                existed_before = case_store.get_case(household, cid) is not None
                case = _build_case(household, purchase, recall_item, verdict, case_store)
                stored_case = case_store.put_case(case)
                uri = write_pack(stored_case)
                stored_case["evidence_uri"] = uri
                stored_case = case_store.put_case(stored_case)
                case_store.append_timeline(household, cid, "evidence_recorded", f"pack written to {uri}")

                if existed_before:
                    summary["cases_updated"] += 1
                else:
                    summary["cases_created"] += 1
                _log(
                    "case_persisted",
                    household=household,
                    case_id=cid,
                    outcome=verdict.outcome.value,
                    status=stored_case["status"],
                    evidence_uri=uri,
                    new=not existed_before,
                )

    _log("run_done", **{k: v for k, v in summary.items() if k != "errors"}, error_count=len(summary["errors"]))
    return summary


def run_agent_pass(household_filter: str | None = None) -> dict:
    """The scheduled pass, with the model reading identity.

    The deterministic sweep in run_once() can only match on shared words, so on
    its own it misses the case this product exists for: a receipt that says
    "LED projecting finger lights party favors 50 pieces" against a notice that
    says "Finger Light Toys ... 50 pieces in a box". Reading that is the agent's
    job, and it has to happen on the schedule too, not only when someone is
    watching. Requires ANTHROPIC_API_KEY in the function environment.

    The recall pool comes from DynamoDB rather than a second fetch: run_once()
    has already refreshed it this invocation.
    """
    from agent.engine.scan import candidates
    from agent.pullback_agent import DynamoSink, build_agent

    summary = run_once(household_filter=household_filter)
    if summary.get("errors"):
        _log("agent_pass_skipped", reason="the feed refresh reported errors")
        return summary

    recalls = [_recall_from_item(item) for item in RecallStore().all_recalls()]
    households = _load_households()
    if household_filter:
        households = {k: v for k, v in households.items() if k == household_filter}

    agent_summary = {"purchases_read": 0, "verdicts": 0, "dispatched": 0, "vetoed": 0}
    for household, purchases in households.items():
        verdict_purchases = [_to_verdict_purchase(p) for p in purchases]
        agent, ledger, events = build_agent(
            household, verdict_purchases, recalls, sink=DynamoSink()
        )
        for purchase in verdict_purchases:
            if not candidates(purchase, recalls):
                continue
            agent_summary["purchases_read"] += 1
            try:
                agent(
                    f"Check purchase {purchase.purchase_id} and finish it: "
                    f"{purchase.description!r} bought from {purchase.retailer} "
                    f"on {purchase.purchased_on} for ${purchase.price}."
                )
            except Exception as exc:
                _log("agent_purchase_error", purchase=purchase.purchase_id, reason=str(exc)[:200])
        agent_summary["verdicts"] += len(ledger.verdicts)
        agent_summary["dispatched"] += len(ledger.dispatched)
        agent_summary["vetoed"] += sum(1 for e in events if e["event"] == "veto")

    summary["agent"] = agent_summary
    _log("agent_pass_done", **agent_summary)
    return summary


def _agent_enabled() -> bool:
    return os.environ.get("PULLBACK_RUN_AGENT") == "1" and bool(os.environ.get("ANTHROPIC_API_KEY"))


def _is_http_event(event: dict) -> bool:
    return isinstance(event, dict) and "requestContext" in event and "http" in event.get("requestContext", {})


def handler(event: dict, context: Any = None) -> dict:
    event = event or {}
    if _is_http_event(event):
        http = event["requestContext"]["http"]
        method = http.get("method", "GET")
        if method == "OPTIONS":
            return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

        household_filter = None
        qs = event.get("queryStringParameters") or {}
        if qs.get("household"):
            household_filter = qs["household"]
        elif event.get("body"):
            try:
                body = json.loads(event["body"])
                household_filter = body.get("household")
            except (ValueError, TypeError):
                pass

        _log("invoke", mode="http", method=method, household_filter=household_filter)
        try:
            summary = (run_agent_pass if _agent_enabled() else run_once)(
                household_filter=household_filter
            )
            return {
                "statusCode": 200,
                "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
                "body": json.dumps(summary, default=str),
            }
        except Exception as exc:
            _log("invoke_error", mode="http", reason=str(exc), traceback=traceback.format_exc())
            return {
                "statusCode": 500,
                "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
                "body": json.dumps({"error": str(exc)}),
            }

    _log("invoke", mode="scheduled", reads_identity=_agent_enabled())
    try:
        return run_agent_pass() if _agent_enabled() else run_once()
    except Exception as exc:
        _log("invoke_error", mode="scheduled", reason=str(exc), traceback=traceback.format_exc())
        raise


if __name__ == "__main__":
    print(json.dumps(handler({}), indent=2, default=str))
    sys.exit(0)
