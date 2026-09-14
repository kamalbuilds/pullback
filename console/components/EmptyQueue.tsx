import Link from "next/link";

import { RunAgent } from "@/components/RunAgent";
import type { Case, Watch } from "@/lib/cases";
import { touchedByHuman } from "@/lib/cases";
import { ago, longDate, plural } from "@/lib/format";

function screenedSentence(w: Watch): string {
  const head = `Pullback screened ${plural(w.purchases, "purchase")} in this household`;
  return w.corpus
    ? `${head} against ${w.corpus.toLocaleString("en-US")} recall notices published by the CPSC in 2026.`
    : `${head} against every recall notice it has ingested.`;
}

function outcomeSentence(cases: Case[]): string {
  const closedAlone = cases.filter(
    (c) => (c.status === "dismissed" || c.status === "resolved") && !touchedByHuman(c),
  ).length;
  const resolved = cases.filter((c) => c.status === "resolved").length;
  const dispatched = cases.filter((c) => c.status === "dispatched").length;

  const parts: string[] = [];
  if (closedAlone) parts.push(`${plural(closedAlone, "case")} closed without you`);
  if (resolved) parts.push(`${plural(resolved, "remedy", "remedies")} completed`);
  if (dispatched) parts.push(`${plural(dispatched, "claim")} still with the manufacturer`);
  if (!parts.length) return "No purchase in this household has matched a notice yet.";
  const sentence = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}.`;
}

export function EmptyQueue({
  cases,
  watch,
  agentEnabled,
}: {
  cases: Case[];
  watch: Watch;
  agentEnabled: boolean;
}) {
  const closed = [...cases]
    .filter((c) => c.status !== "awaiting_approval" && c.status !== "needs_evidence")
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, 4);

  return (
    <section className="report-in pt-20">
      <h1 className="statement max-w-[18ch]">Nothing needs you.</h1>

      <p className="prose-16 mt-7 max-w-[58ch]" style={{ color: "var(--ink-2)" }}>
        {screenedSentence(watch)} {outcomeSentence(cases)}
      </p>

      {watch.lastRun ? (
        <p className="micro mt-6">
          last run {ago(watch.lastRun)} at {watch.lastRun.replace("T", " ").replace("Z", "")} UTC
        </p>
      ) : null}

      {closed.length ? (
        <div className="mt-16">
          <h2 className="label">Closed while you were away</h2>
          <ul className="mt-5">
            {closed.map((c) => (
              <li key={c.case_id} className="border-b border-rule">
                <Link
                  href={`/case/${c.case_id}`}
                  className="grid grid-cols-1 gap-1 py-4 sm:grid-cols-[110px_1fr_auto] sm:items-baseline sm:gap-6"
                >
                  <span className="micro">{longDate(c.updated_at)}</span>
                  <span className="prose-16">{c.purchase.description}</span>
                  <span className="micro" style={{ color: "var(--ink-2)" }}>
                    {c.verdict.outcome === "NO_MATCH"
                      ? "no match, closed silently"
                      : c.status === "resolved"
                        ? "remedy complete"
                        : "claim with the manufacturer"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-14">
        <RunAgent enabled={agentEnabled} />
      </div>
    </section>
  );
}
