export type CaseStatus =
  | "needs_evidence"
  | "awaiting_approval"
  | "dispatched"
  | "resolved"
  | "dismissed";

export type Outcome = "MATCH" | "NEEDS_EVIDENCE" | "NO_MATCH";

export interface Check {
  name: string;
  passed: boolean;
  detail: string;
}

export interface TimelineEntry {
  at: string;
  event: string;
  detail: string;
}

export interface Purchase {
  purchase_id: string;
  description: string;
  retailer: string;
  purchased_on: string;
  price: number | null;
  quantity: number;
  upc: string | null;
  model: string | null;
}

export interface Recall {
  source: string;
  recall_number: string;
  title: string;
  url: string;
  recall_date: string;
  hazards: string[];
  remedy_kinds: string[];
  contact_email: string | null;
  contact_phone: string | null;
}

export interface Verdict {
  outcome: Outcome;
  checks: Check[];
  missing: string[];
  evidence_id: string;
}

export interface Case {
  household: string;
  case_id: string;
  status: CaseStatus;
  purchase: Purchase;
  recall: Recall;
  verdict: Verdict;
  timeline: TimelineEntry[];
  evidence_uri: string;
  claim_text: string;
  created_at: string;
  updated_at: string;
}

const HUMAN_EVENTS = ["approval.granted", "approval.declined", "evidence.provided"];

export function sortedTimeline(c: Case): TimelineEntry[] {
  return [...(c.timeline ?? [])].sort((a, b) => a.at.localeCompare(b.at));
}

export function lastEvent(c: Case): TimelineEntry | null {
  const t = sortedTimeline(c);
  return t.length ? t[t.length - 1] : null;
}

/** True when the agent has done everything it can and the next move belongs to a person. */
export function needsHuman(c: Case): boolean {
  if (c.status === "awaiting_approval") return true;
  if (c.status !== "needs_evidence") return false;
  const t = sortedTimeline(c);
  const asked = t.findLastIndex((e) => e.event === "evidence.requested");
  const answered = t.findLastIndex((e) => e.event === "evidence.provided");
  return answered < asked;
}

export function touchedByHuman(c: Case): boolean {
  return (c.timeline ?? []).some((e) => HUMAN_EVENTS.includes(e.event));
}

/**
 * Death is the word that decides the order. 317 of the 434 CPSC notices published in 2026
 * carry it in the title, so it is a coarse signal, but a recall that can kill outranks one
 * that can burn a hand, and an older unanswered case outranks a newer one.
 */
export function urgency(c: Case): number {
  const text = `${c.recall.title} ${c.recall.hazards.join(" ")}`.toLowerCase();
  let score = 0;
  if (text.includes("death")) score += 400;
  if (text.includes("children") || text.includes("infant") || text.includes("child")) score += 120;
  if (text.includes("serious injury")) score += 60;
  if (c.status === "awaiting_approval") score += 30;
  const openedDays = (Date.now() - Date.parse(c.created_at)) / 86_400_000;
  score += Math.min(openedDays, 60);
  return score;
}

export function queue(cases: Case[]): Case[] {
  return cases.filter(needsHuman).sort((a, b) => urgency(b) - urgency(a));
}

export interface Watch {
  purchases: number;
  corpus: number | null;
  screenings: number;
  closedAlone: number;
  handled: number;
  lastRun: string | null;
  since: string | null;
}

const CORPUS_RE = /CPSC published (\d[\d,]*) notices/;

/**
 * Everything the empty state says about the agent is counted here, from the rows themselves.
 * The corpus size is quoted back out of the screening events the agent wrote, so the number
 * on screen is the number the agent actually screened against.
 */
export function watch(cases: Case[]): Watch {
  const purchases = new Set(cases.map((c) => c.purchase?.purchase_id).filter(Boolean));
  let corpus: number | null = null;
  let screenings = 0;
  let lastRun: string | null = null;
  let since: string | null = null;

  for (const c of cases) {
    for (const e of c.timeline ?? []) {
      if (!lastRun || e.at > lastRun) lastRun = e.at;
      if (!since || e.at < since) since = e.at;
      if (e.event === "purchase.screened") screenings += 1;
      const m = CORPUS_RE.exec(e.detail ?? "");
      if (m) {
        const n = Number(m[1].replace(/,/g, ""));
        if (!corpus || n > corpus) corpus = n;
      }
    }
  }

  const closed = cases.filter((c) => c.status === "dismissed" || c.status === "resolved");
  return {
    purchases: purchases.size,
    corpus,
    screenings,
    closedAlone: closed.filter((c) => !touchedByHuman(c)).length,
    handled: cases.filter((c) => !needsHuman(c)).length,
    lastRun,
    since,
  };
}

export const STATUS_MARK: Record<CaseStatus, { word: string; tone: string }> = {
  needs_evidence: { word: "needs you", tone: "var(--pending)" },
  awaiting_approval: { word: "needs you", tone: "var(--pending)" },
  dispatched: { word: "claim sent", tone: "var(--ink-2)" },
  resolved: { word: "closed", tone: "var(--seal)" },
  dismissed: { word: "no match", tone: "var(--ink-3)" },
};

/** Maps the engine's prose in verdict.missing onto the purchase field that would settle it. */
export const MISSING_FIELDS: Record<
  string,
  { field: keyof Purchase; label: string; type: "text" | "number" | "date"; help: string }
> = {
  "where it was bought": {
    field: "retailer",
    label: "Retailer",
    type: "text",
    help: "The store or site. The notice names specific sellers.",
  },
  "what it cost": {
    field: "price",
    label: "Price paid",
    type: "number",
    help: "Unit price in dollars, before tax.",
  },
  "when it was bought": {
    field: "purchased_on",
    label: "Purchase date",
    type: "date",
    help: "The date on the receipt or the order confirmation.",
  },
  "the UPC printed on the box": {
    field: "upc",
    label: "UPC",
    type: "text",
    help: "12 digits under the barcode on the packaging.",
  },
  "the model number on the product label": {
    field: "model",
    label: "Model number",
    type: "text",
    help: "Printed on the product label or the underside.",
  },
};
