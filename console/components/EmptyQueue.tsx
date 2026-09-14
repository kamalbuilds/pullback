import Link from "next/link";

import { RunAgent } from "@/components/RunAgent";
import type { Case, Watch } from "@/lib/cases";
import { throughputSentence, touchedByHuman } from "@/lib/cases";
import { ago, longDate, plural, stampUTC } from "@/lib/format";

/**
 * What the run sentence does not already say. When the run record reports the dispatch count,
 * repeating it here as "still with the manufacturer" is the same number said twice.
 */
function outcomeSentence(cases: Case[], watch: Watch): string {
  if (!cases.length) return "Nothing in this household has matched a notice yet.";

  const closedAlone = cases.filter(
    (c) => (c.status === "dismissed" || c.status === "resolved") && !touchedByHuman(c),
  ).length;
  const resolved = cases.filter((c) => c.status === "resolved").length;
  const dispatched = cases.filter((c) => c.status === "dispatched").length;

  const parts: string[] = [];
  if (closedAlone) parts.push(`${plural(closedAlone, "case")} closed without you`);
  if (resolved) parts.push(`${plural(resolved, "remedy", "remedies")} completed`);
  if (dispatched && watch.dispatched === null) {
    parts.push(`${plural(dispatched, "claim")} still with the manufacturer`);
  }
  if (!parts.length) return "";
  const sentence =
    parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
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
    <section className="report-in pt-16">
      <div className="cleared-tag">
        <span className="cleared-stamp" aria-hidden="true">
          Cleared
        </span>
        <h1 className="statement max-w-[18ch]">Nothing needs you.</h1>

        <p className="prose-16 mt-6 max-w-[58ch]" style={{ color: "var(--ink-2)" }}>
          {`${throughputSentence(watch)} ${outcomeSentence(cases, watch)}`.trim()}
        </p>

        {watch.lastRun ? (
          <p className="micro mt-6">{`last run ${ago(watch.lastRun)}, ${stampUTC(watch.lastRun)}`}</p>
        ) : null}
      </div>

      {closed.length ? (
        <div className="mt-16">
          <h2 className="label">Closed while you were away</h2>
          <ul className="mt-5">
            {closed.map((c) => (
              <li key={c.case_id} className="border-b border-rule">
                <Link
                  href={`/case/${c.case_id}`}
                  className="grid grid-cols-1 gap-1 py-4 sm:grid-cols-[136px_1fr_auto] sm:items-baseline sm:gap-6"
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
