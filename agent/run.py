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
        cached = json.loads((DATA / "cpsc_2026.json").read_text())
        return [
            cpsc.parse_recall(item)
            for item in cached
            if item["RecallDate"][:10] >= since.isoformat()
        ]

    recalls = list(cpsc.fetch(since))
    try:
        recalls.extend(openfda.fetch_all(since))
    except Exception as exc:  # a regulator being down must not stop the pass
        print(json.dumps({"event": "feed_degraded", "source": "openFDA", "detail": str(exc)[:160]}))
    return recalls


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
                "source": "live CPSC feed" if live else "cached CPSC snapshot",
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
