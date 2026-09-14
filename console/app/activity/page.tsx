import type { Metadata } from "next";
import Link from "next/link";

import { Provenance } from "@/components/Provenance";
import type { Case, Run } from "@/lib/cases";
import { sourceList } from "@/lib/cases";
import { longDate, clockUTC, dayKey, plural } from "@/lib/format";
import { listCases } from "@/lib/store";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Pullback: what the agent did unattended",
};

const HUMAN_EVENTS = new Set(["approval.granted", "approval.declined", "evidence.provided"]);

interface Row {
  kind: "case" | "run";
  at: string;
  event: string;
  detail: string;
  caseId: string;
  subject: string;
}

/** One line of English for a whole screening pass, built from the run record's own counts. */
function runDetail(run: Run): string {
  const feeds = sourceList(run.sources ?? []);
  const parts = [
    `Screened ${plural(run.purchases_screened, "purchase")} against ${run.recalls_screened.toLocaleString("en-US")} ${feeds ? `${feeds} ` : ""}notices`,
    `${plural(run.pairs_considered, "pair")} considered`,
    `${plural(run.cases_opened, "case")} opened`,
    `${plural(run.dispatched, "claim")} dispatched`,
    `${run.vetoed} vetoed`,
  ];
  return `${parts[0]}. ${parts.slice(1).join(", ")}.`;
}

function feed(cases: Case[], runs: Run[]): Row[] {
  const rows: Row[] = [];
  for (const c of cases) {
    for (const e of c.timeline ?? []) {
      rows.push({
        kind: "case",
        at: e.at,
        event: e.event,
        detail: e.detail,
        caseId: c.case_id,
        subject: c.purchase.description,
      });
    }
  }
  for (const run of runs) {
    rows.push({
      kind: "run",
      at: run.finished_at ?? run.case_id.slice("run#".length),
      event: "run.finished",
      detail: runDetail(run),
      caseId: run.case_id,
      subject: "agent run",
    });
  }
  return rows.sort((a, b) => b.at.localeCompare(a.at));
}

export default async function ActivityPage() {
  const { cases, runs, source } = await listCases();
  const rows = feed(cases, runs);
  const human = rows.filter((r) => HUMAN_EVENTS.has(r.event)).length;
  const silent = cases.filter(
    (c) =>
      c.verdict.outcome === "NO_MATCH" &&
      !(c.timeline ?? []).some((e) => HUMAN_EVENTS.has(e.event)),
  ).length;

  const days = new Map<string, Row[]>();
  for (const row of rows) {
    const key = dayKey(row.at);
    const bucket = days.get(key);
    if (bucket) bucket.push(row);
    else days.set(key, [row]);
  }

  return (
    <>
      <section className="pt-16">
        <h1 className="statement max-w-[22ch]">
          {rows.length} {rows.length === 1 ? "entry" : "entries"}. You were needed for {human}.
        </h1>
        <p className="prose-16 mt-6 max-w-[60ch]" style={{ color: "var(--ink-2)" }}>
          Every screening pass, verdict, claim and follow up Pullback has written for this
          household, newest first.{" "}
          {silent
            ? `${plural(silent, "case")} reached NO_MATCH and closed without ever appearing in the queue.`
            : "Runs that match nothing close silently and never appear in the queue."}
        </p>
      </section>

      <section className="mt-14">
        {[...days.entries()].map(([day, entries]) => (
          <div key={day} className="mb-10">
            <div className="flex items-baseline gap-4 border-b border-rule-strong pb-2">
              <h2 className="label" style={{ color: "var(--ink)" }}>
                {longDate(`${day}T00:00:00Z`)}
              </h2>
              <span className="micro">{plural(entries.length, "entry", "entries")}</span>
            </div>
            <ol>
              {entries.map((row, index) => (
                <li
                  key={`${row.caseId}-${row.at}-${index}`}
                  className="border-b border-rule py-3"
                  style={
                    row.kind === "run"
                      ? { borderLeft: "2px solid var(--seal)", paddingLeft: "14px" }
                      : undefined
                  }
                >
                  <div className="grid grid-cols-1 gap-1.5 lg:grid-cols-[58px_182px_1fr_196px] lg:items-baseline lg:gap-5">
                    <span className="micro">{clockUTC(row.at)}</span>
                    <span
                      className="data"
                      style={{
                        color:
                          row.kind === "run"
                            ? "var(--seal)"
                            : HUMAN_EVENTS.has(row.event)
                              ? "var(--pending)"
                              : "var(--ink)",
                      }}
                    >
                      {row.event}
                    </span>
                    <span className="data" style={{ color: "var(--ink-2)" }}>
                      {row.detail}
                    </span>
                    {row.kind === "run" ? (
                      <span className="label lg:text-right">agent run</span>
                    ) : (
                      <Link
                        href={`/case/${row.caseId}`}
                        className="micro lg:overflow-hidden lg:text-ellipsis lg:whitespace-nowrap lg:text-right"
                        style={{ color: "var(--ink-3)" }}
                        title={row.subject}
                      >
                        {row.subject}
                      </Link>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </section>

      <Provenance source={source} count={cases.length} runs={runs.length} />
    </>
  );
}
