import { NextResponse } from "next/server";

import type { Case, TimelineEntry } from "@/lib/cases";
import { money } from "@/lib/format";
import { agentUrl, applyMutation, getCase, HOUSEHOLD } from "@/lib/store";

export const dynamic = "force-dynamic";

const PATCHABLE = new Set(["retailer", "price", "purchased_on", "upc", "model"]);

function now(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function entry(event: string, detail: string): TimelineEntry {
  return { at: now(), event, detail };
}

/**
 * Tells the agent a case has moved. The console never sends a claim itself, so the timeline
 * says exactly which of the two happened: the agent took it, or it is waiting for the run.
 */
async function notifyAgent(item: Case, reason: string): Promise<TimelineEntry> {
  const url = agentUrl();
  if (!url) {
    return entry(
      "dispatch.queued",
      `${reason} No agent endpoint is configured on this deployment, so the next scheduled run picks it up. Nothing has been sent yet.`,
    );
  }
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ household: HOUSEHOLD, case_id: item.case_id, reason }),
      signal: AbortSignal.timeout(20_000),
    });
    const text = (await res.text()).slice(0, 400);
    if (!res.ok) {
      return entry(
        "dispatch.queued",
        `${reason} The agent endpoint answered ${res.status}, so the claim is still unsent. ${text}`,
      );
    }
    return entry("agent.notified", `${reason} The agent accepted the case. ${text}`);
  } catch (error) {
    return entry(
      "dispatch.queued",
      `${reason} The agent endpoint could not be reached (${(error as Error).message}), so the claim is still unsent.`,
    );
  }
}

export async function POST(request: Request, context: { params: Promise<{ case_id: string }> }) {
  const { case_id } = await context.params;
  const { item } = await getCase(case_id);
  if (!item) {
    return NextResponse.json({ error: "No case with that id in this household." }, { status: 404 });
  }

  let body: { action?: string; values?: Record<string, string> };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "The request body was not JSON." }, { status: 400 });
  }

  try {
    if (body.action === "approve") {
      if (item.status !== "awaiting_approval") {
        return NextResponse.json(
          { error: `This case is ${item.status.replace(/_/g, " ")}, so there is nothing to approve.` },
          { status: 409 },
        );
      }
      const recipient = item.recall.contact_email ?? item.recall.contact_phone ?? "the manufacturer";
      const events = [
        entry("approval.granted", `Approved from the console. The claim goes to ${recipient}.`),
        await notifyAgent(item, "Claim released for dispatch."),
      ];
      await applyMutation(case_id, "awaiting_approval", { status: "dispatched", events });
      return NextResponse.json({ ok: true, status: "dispatched" });
    }

    if (body.action === "decline") {
      if (item.status !== "awaiting_approval") {
        return NextResponse.json(
          { error: `This case is ${item.status.replace(/_/g, " ")}, so there is nothing to decline.` },
          { status: 409 },
        );
      }
      await applyMutation(case_id, "awaiting_approval", {
        status: "dismissed",
        events: [
          entry(
            "approval.declined",
            `Declined from the console. ${item.recall.source} ${item.recall.recall_number} will not be raised for this purchase again.`,
          ),
          entry("case.closed", "Closed by the household. No claim was sent."),
        ],
      });
      return NextResponse.json({ ok: true, status: "dismissed" });
    }

    if (body.action === "evidence") {
      if (item.status !== "needs_evidence") {
        return NextResponse.json(
          { error: `This case is ${item.status.replace(/_/g, " ")}, so it is not waiting on evidence.` },
          { status: 409 },
        );
      }
      const patch: Record<string, string | number> = {};
      const said: string[] = [];
      for (const [field, raw] of Object.entries(body.values ?? {})) {
        const value = String(raw ?? "").trim();
        if (!value || !PATCHABLE.has(field)) continue;
        if (field === "price") {
          const n = Number(value);
          if (!Number.isFinite(n) || n < 0) {
            return NextResponse.json({ error: "Price has to be a number." }, { status: 400 });
          }
          patch.price = n;
          said.push(`price ${money(n)}`);
        } else if (field === "purchased_on") {
          if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
            return NextResponse.json({ error: "Purchase date has to be YYYY-MM-DD." }, { status: 400 });
          }
          patch.purchased_on = value;
          said.push(`purchase date ${value}`);
        } else {
          patch[field] = value;
          said.push(`${field.replace(/_/g, " ")} ${value}`);
        }
      }

      if (!said.length) {
        return NextResponse.json({ error: "No usable answer was sent." }, { status: 400 });
      }

      const events = [
        entry("evidence.provided", `Household answered: ${said.join("; ")}.`),
        await notifyAgent(item, "Purchase record updated, verdict needs recomputing."),
      ];
      await applyMutation(case_id, "needs_evidence", { events, purchasePatch: patch });
      return NextResponse.json({ ok: true, status: "needs_evidence" });
    }

    return NextResponse.json({ error: "Unknown action." }, { status: 400 });
  } catch (error) {
    const message = (error as Error).message ?? "The write failed.";
    const conflict = (error as { name?: string }).name === "ConditionalCheckFailedException";
    return NextResponse.json(
      {
        error: conflict
          ? "This case changed while the page was open. Reload it and look again before deciding."
          : message,
      },
      { status: conflict ? 409 : 500 },
    );
  }
}
