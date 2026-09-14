"""One unattended pass over a household.

This is what the scheduler invokes. Nobody is watching it, so it prints one
JSON object per line and it never asks a question it could answer itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from agent.engine.scan import candidates, load_household
from agent.feeds import cpsc, nhtsa, openfda
from agent.feeds.base import Recall
from agent.pullback_agent import CaseSink, DynamoSink, FileSink, build_agent

DATA = Path(__file__).parent.parent / "data"


def load_recalls(*, since: date, live: bool) -> list[Recall]:
    """Every regulator that publishes about a household's things.

    CPSC and NHTSA describe circumstance: where a thing was sold, when, for how
    much. openFDA describes identity instead: lot codes and UPCs, with no sold
    window and no price anywhere in the schema. The verdict engine already
    handles both, because an identifier settles a case on its own and, when one
    is missing, it asks for exactly that.
    """
    if not live:
        # Every source, not just CPSC. A cached run that quietly drops the
        # vehicle and food feeds shows a household with no car and no groceries,
        # which is a demo that lies by omission.
        cached = json.loads((DATA / "cpsc_2026.json").read_text())
        recalls = [
            cpsc.parse_recall(item)
            for item in cached
            if item["RecallDate"][:10] >= since.isoformat()
        ]
        vehicles = json.loads((DATA / "nhtsa_sample.json").read_text())
        recalls.extend(nhtsa.parse_recall(item) for item in vehicles.get("results", []))
        enforcement = json.loads((DATA / "openfda_sample.json").read_text())
        for payload in enforcement.values():
            recalls.extend(openfda.parse_recall(item) for item in payload.get("results", []))
        return recalls

    recalls = list(cpsc.fetch(since))
    try:
        recalls.extend(openfda.fetch_all(since))
    except Exception as exc:  # a regulator being down must not stop the pass
        print(json.dumps({"event": "feed_degraded", "source": "openFDA", "detail": str(exc)[:160]}))
    return recalls


def widen(purchase, recalls: list[Recall], found: list) -> list:
    """Add semantically similar notices to whatever the lexical filter found.

    Optional on purpose. Semantic retrieval costs torch and a 130MB model
    download, and the README promises a clean clone runs the suite with no
    network and no credentials. So it is an extra, `pip install -e
    '.[retrieval]'`, and when it is absent the pass behaves as it did before
    rather than failing.

    It only ever widens. Nothing it adds can approve a claim: every added
    candidate still has to clear the same arithmetic, and measured across this
    household 39 of the 40 notices it adds are rejected there. The one it
    recovers is a false negative the lexical filter could never catch, because
    that receipt and that notice share almost no words.
    """
    try:
        from agent.engine.retrieval import semantic_candidates
    except ImportError:
        return found

    seen = {c.recall.recall_number for c in found}
    extra = [
        c for c in semantic_candidates(purchase, recalls) if c.recall.recall_number not in seen
    ]
    if extra:
        print(
            json.dumps(
                {
                    "event": "widened",
                    "purchase": purchase.purchase_id,
                    "added": [c.recall.recall_number for c in extra],
                }
            ),
            flush=True,
        )
    return found + extra


def load_vehicle_recalls(vehicles: list[dict]) -> list[Recall]:
    recalls: list[Recall] = []
    for vehicle in vehicles:
        try:
            recalls.extend(
                nhtsa.fetch_by_vehicle(vehicle["make"], vehicle["model"], vehicle["model_year"])
            )
        except Exception as exc:
            print(json.dumps({"event": "feed_degraded", "source": "NHTSA", "detail": str(exc)[:160]}))
    return recalls


def record_run(household: str, counts: dict, *, sink: CaseSink) -> None:
    """Write down what the pass actually covered.

    Without this the console can only count the cases it can see, which makes
    it report "screened 7 purchases" after a pass that screened fifteen. The
    number a person reads has to come from the run, not from its leftovers.

    It shares the cases table under a `run#` sort key rather than getting a
    table of its own: the console already has read access to exactly one
    table, and widening that to brag about throughput is a bad trade.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sink.write(
        {
            "household": household,
            "case_id": f"run#{now}",
            "record_type": "run",
            "status": "run_summary",
            "finished_at": now,
            "created_at": now,
            "updated_at": now,
            "timeline": [{"at": now, "event": "run_finished", "detail": json.dumps(counts)}],
            **counts,
        }
    )


def run(*, live: bool, days: int, sink: CaseSink, only: str | None = None) -> dict:
    household, purchases, raw = load_household()
    recalls = load_recalls(since=date.today() - timedelta(days=days), live=live)
    if live:
        recalls.extend(load_vehicle_recalls(raw.get("vehicles", [])))
    if only:
        purchases = [p for p in purchases if p.purchase_id == only]

    agent, ledger, events = build_agent(household, purchases, recalls, sink=sink)

    print(
        json.dumps(
            {
                "event": "run_started",
                "household": household,
                "purchases": len(purchases),
                "recalls": len(recalls),
                "window_days": days,
                "sources": sorted({r.source for r in recalls}),
                "source": "live regulator feeds" if live else "captured feed snapshots",
            }
        ),
        flush=True,
    )

    # One purchase per turn. A single prompt carrying fifteen purchases and four
    # hundred notices burns context on pairs that the candidate filter already
    # rejected, and a stall on one purchase would take the rest down with it.
    for purchase in purchases:
        if not candidates(purchase, recalls):
            print(
                json.dumps(
                    {
                        "event": "cleared",
                        "purchase": purchase.purchase_id,
                        "detail": "no notice resembles this purchase",
                    }
                ),
                flush=True,
            )
            continue
        agent(
            f"Check purchase {purchase.purchase_id} and finish it: "
            f"{purchase.description!r} bought from {purchase.retailer} "
            f"on {purchase.purchased_on} for ${purchase.price}."
        )

    record_run(
        household,
        {
            "purchases_screened": len(purchases),
            "recalls_screened": len(recalls),
            "pairs_considered": ledger.considered,
            "cases_opened": len(ledger.cases),
            "dispatched": len(ledger.dispatched),
            "vetoed": sum(1 for e in events if e["event"] == "veto"),
            "sources": sorted({r.source for r in recalls}),
        },
        sink=sink,
    )

    summary = {
        "event": "run_finished",
        "purchases": len(purchases),
        "pairs_considered": ledger.considered,
        "verdicts": len(ledger.verdicts),
        "cases_opened": len(ledger.cases),
        "claims_written": len(ledger.claims),
        "dispatched": len(ledger.dispatched),
        "vetoed": sum(1 for e in events if e["event"] == "veto"),
        "asked_household": sum(1 for e in events if e["event"] == "asked_household"),
    }
    print(json.dumps(summary), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Pullback pass over a household.")
    parser.add_argument("--live", action="store_true", help="fetch the CPSC feed instead of the snapshot")
    parser.add_argument("--days", type=int, default=365, help="how far back to consider notices")
    parser.add_argument("--only", help="restrict the pass to one purchase id")
    parser.add_argument("--dynamo", action="store_true", help="persist cases to DynamoDB")
    args = parser.parse_args()

    sink: CaseSink = DynamoSink() if args.dynamo else FileSink()
    summary = run(live=args.live, days=args.days, sink=sink, only=args.only)
    return 0 if summary["verdicts"] else 1


if __name__ == "__main__":
    sys.exit(main())
