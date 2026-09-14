import Link from "next/link";

import type { Case } from "@/lib/cases";

/**
 * The household's own things, as a shelf rather than as another queue.
 *
 * The queue answers "what needs me now". This answers a different question, and
 * the one a parent actually asks in a kitchen: of the things I own, which are
 * cleared and which are not. Every purchase the agent has ever screened appears
 * here, including the ones with nothing wrong, because a list that only shows
 * problems cannot tell you that the rest were checked.
 *
 * Keep and discard are derived from case status, never stored. A thing is
 * discard if any open case on it is a match, keep if every case on it closed.
 */

type Verdict = "discard" | "keep" | "asking";

function verdictOf(cases: Case[]): Verdict {
  if (cases.some((c) => c.status === "awaiting_approval" || c.status === "dispatched")) {
    return "discard";
  }
  if (cases.some((c) => c.status === "needs_evidence")) return "asking";
  return "keep";
}

const FACE: Record<Verdict, { word: string; tone: string }> = {
  discard: { word: "do not use", tone: "var(--alarm)" },
  asking: { word: "one question", tone: "var(--pending)" },
  keep: { word: "cleared", tone: "var(--ink-3)" },
};

export function Shelf({ cases }: { cases: Case[] }) {
  const byPurchase = new Map<string, { label: string; bought: string; cases: Case[] }>();

  for (const c of cases) {
    const id = c.purchase?.purchase_id;
    if (!id) continue;
    const found = byPurchase.get(id);
    if (found) {
      found.cases.push(c);
      continue;
    }
    byPurchase.set(id, {
      label: c.purchase.description,
      bought: [c.purchase.purchased_on, c.purchase.retailer].filter(Boolean).join(" · "),
      cases: [c],
    });
  }

  const rows = [...byPurchase.entries()]
    .map(([id, row]) => ({ id, ...row, verdict: verdictOf(row.cases) }))
    .sort((a, b) => {
      const order: Verdict[] = ["discard", "asking", "keep"];
      return order.indexOf(a.verdict) - order.indexOf(b.verdict);
    });

  if (!rows.length) return null;

  const cleared = rows.filter((r) => r.verdict === "keep").length;

  return (
    <section className="shelf">
      <div className="shelf-head">
        <h2 className="label">The shelf</h2>
        <span className="micro">
          {cleared} of {rows.length} cleared
        </span>
      </div>

      <ul className="shelf-list">
        {rows.map((row) => {
          const face = FACE[row.verdict];
          const open = row.cases.find(
            (c) => c.status === "awaiting_approval" || c.status === "needs_evidence",
          );
          return (
            <li key={row.id} className="shelf-row">
              <span className="shelf-thing">
                {open ? (
                  <Link href={`/case/${open.case_id}`}>{row.label}</Link>
                ) : (
                  row.label
                )}
                <span className="shelf-bought micro">{row.bought}</span>
              </span>
              <span className="shelf-verdict micro" style={{ color: face.tone }}>
                {face.word}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="micro shelf-note">
        Every thing the agent has screened, not only the ones with a problem. Cleared means
        every notice checked against it failed on a date, a price, a retailer or an identifier.
      </p>
    </section>
  );
}
