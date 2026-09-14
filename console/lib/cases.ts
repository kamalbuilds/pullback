import { plural } from "./format";

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

/**
 * A run record shares the partition key with the cases but is not one. The agent writes one
 * per screening pass under a `run#<iso>` sort key, and it is the only honest source for how
 * much work a pass did. Counting cases in the table measures what is left over, not what ran.
 */
export interface Run {
  case_id: string;
  record_type: "run";
  status: "run_summary";
  purchases_screened: number;
  recalls_screened: number;
  pairs_considered: number;
  cases_opened: number;
  dispatched: number;
  vetoed: number;
  sources: string[];
  finished_at: string;
  timeline: TimelineEntry[];
}

export const RUN_PREFIX = "run#";

export function isRun(raw: { case_id?: string; record_type?: string }): boolean {
  return raw.record_type === "run" || (raw.case_id ?? "").startsWith(RUN_PREFIX);
}

/** ISO timestamps sort lexicographically, so the last run# key is the newest run. */
export function latestRun(runs: Run[]): Run | null {
  if (!runs.length) return null;
  return [...runs].sort((a, b) => a.case_id.localeCompare(b.case_id))[runs.length - 1];
}

export interface Watch {
  purchases: number;
  corpus: number | null;
  sources: string[];
  opened: number | null;
  dispatched: number | null;
  vetoed: number | null;
  closedAlone: number;
  handled: number;
  lastRun: string | null;
  since: string | null;
  /** True when the figures above came from a run record rather than from leftover rows. */
  fromRun: boolean;
}

const CORPUS_RE = /CPSC published (\d[\d,]*) notices/;

/**
 * The run record is the source of truth for throughput. Everything falls back to counting
 * rows only when no run has been written yet, because a fallback that prints zero would be a
 * lie in the other direction.
 */
export function watch(cases: Case[], run: Run | null = null): Watch {
  const purchases = new Set(cases.map((c) => c.purchase?.purchase_id).filter(Boolean));
  let corpus: number | null = null;
  let lastRun: string | null = null;
  let since: string | null = null;

  for (const c of cases) {
    for (const e of c.timeline ?? []) {
      if (!lastRun || e.at > lastRun) lastRun = e.at;
      if (!since || e.at < since) since = e.at;
      const m = CORPUS_RE.exec(e.detail ?? "");
      if (m) {
        const n = Number(m[1].replace(/,/g, ""));
        if (!corpus || n > corpus) corpus = n;
      }
    }
  }

  const closed = cases.filter((c) => c.status === "dismissed" || c.status === "resolved");
  return {
    purchases: run ? run.purchases_screened : purchases.size,
    corpus: run ? run.recalls_screened : corpus,
    sources: run?.sources?.length ? run.sources : [],
    opened: run ? run.cases_opened : null,
    dispatched: run ? run.dispatched : null,
    vetoed: run ? run.vetoed : null,
    closedAlone: closed.filter((c) => !touchedByHuman(c)).length,
    handled: cases.filter((c) => !needsHuman(c)).length,
    lastRun: run?.finished_at ?? lastRun,
    since,
    fromRun: Boolean(run),
  };
}

/** "CPSC", "CPSC and NHTSA", "CPSC, NHTSA and openFDA". */
export function sourceList(sources: string[]): string {
  if (!sources.length) return "";
  if (sources.length === 1) return sources[0];
  return `${sources.slice(0, -1).join(", ")} and ${sources[sources.length - 1]}`;
}

/**
 * The one sentence that says how much work the agent did. It is quoted from the run record so
 * the throughput is what ran, not what happens to be left in the table. Counting leftover rows
 * understates every pass that closed cases, and a number on screen has to be true.
 */
export function throughputSentence(w: Watch): string {
  if (!w.fromRun || w.corpus === null) {
    return `Pullback is watching ${plural(w.purchases, "purchase")} in this household and has closed ${plural(w.handled, "case")} without asking. No run summary has been written yet, so these are counted from the cases themselves.`;
  }
  const feeds = sourceList(w.sources);
  const against = `against ${w.corpus.toLocaleString("en-US")} ${feeds ? `${feeds} ` : ""}recall ${w.corpus === 1 ? "notice" : "notices"}`;
  const did: string[] = [];
  if (w.opened !== null) did.push(`opened ${plural(w.opened, "case")}`);
  if (w.vetoed) did.push(`vetoed ${w.vetoed}`);
  if (w.dispatched !== null) did.push(`dispatched ${plural(w.dispatched, "claim")}`);
  const tail = did.length
    ? `, ${did.length === 1 ? did[0] : `${did.slice(0, -1).join(", ")} and ${did[did.length - 1]}`}`
    : "";
  return `The last run screened ${plural(w.purchases, "purchase")} in this household ${against}${tail}.`;
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
