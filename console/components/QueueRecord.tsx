import Link from "next/link";

import { StatusMark } from "@/components/StatusMark";
import type { Case } from "@/lib/cases";
import { ago, firstSentence, money, shortDate, remedyPhrase } from "@/lib/format";

function decisionLine(c: Case): string {
  const total = c.verdict.checks.length;
  const passed = c.verdict.checks.filter((k) => k.passed).length;
  if (c.verdict.outcome === "MATCH") {
    return `MATCH on ${passed} of ${total} checks against ${c.recall.source} ${c.recall.recall_number}. Claim drafted, not sent.`;
  }
  const missing = c.verdict.missing[0];
  return `NEEDS EVIDENCE. ${passed} of ${total} checks passed against ${c.recall.source} ${c.recall.recall_number}. Missing: ${missing ?? "one fact"}.`;
}

function actionLabel(c: Case): string {
  if (c.status === "awaiting_approval") {
    return `Read the claim, then send it for ${remedyPhrase(c.recall.remedy_kinds)}`;
  }
  const missing = c.verdict.missing[0];
  return missing ? `Answer one question: ${missing}` : "Add the missing evidence";
}

export function QueueRecord({ item }: { item: Case }) {
  const bought = [
    `bought ${item.purchase.purchased_on}`,
    item.purchase.retailer ? `at ${item.purchase.retailer}` : null,
    item.purchase.price !== null ? `for ${money(item.purchase.price)}` : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Link href={`/case/${item.case_id}`} className="record">
      <div className="grid grid-cols-1 gap-x-10 gap-y-3 lg:grid-cols-[1fr_178px]">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 lg:order-2 lg:flex-col lg:items-end lg:gap-y-2 lg:pt-1.5">
          <StatusMark status={item.status} />
          <span className="micro lg:text-right">{ago(item.created_at)}</span>
          <span className="micro lg:text-right">
            {item.recall.source} {item.recall.recall_number}
          </span>
          <span className="micro lg:text-right">notice {shortDate(item.recall.recall_date)}</span>
        </div>

        <div className="lg:order-1">
          <h2 className="record-title max-w-[42ch]">{item.purchase.description}</h2>
          <p className="micro mt-1.5">{bought}</p>

          <p className="hazard mt-4 max-w-[58ch]">
            {firstSentence(item.recall.hazards[0] ?? item.recall.title, 300)}
          </p>

          <p className="data mt-4 max-w-[70ch]" style={{ color: "var(--ink-2)" }}>
            {decisionLine(item)}
          </p>

          <p
            className="record-action mt-5 inline-flex items-center gap-2"
            style={{ color: "var(--seal)", fontSize: "15px" }}
          >
            {actionLabel(item)}
            <span aria-hidden="true">&rarr;</span>
          </p>
        </div>
      </div>
    </Link>
  );
}
