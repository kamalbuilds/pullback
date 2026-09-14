import Link from "next/link";

import { RecordVerb } from "@/components/RecordVerb";
import { StatusMark } from "@/components/StatusMark";
import type { Case } from "@/lib/cases";
import { ago, firstSentence, money, shortDate, remedyPhrase } from "@/lib/format";

const CHECK_WORD: Record<string, string> = {
  upc: "upc",
  model: "model",
  retailer: "retailer",
  sold_window: "sold window",
  price_band: "price",
  description_overlap: "description",
};

function verdictWord(c: Case): string {
  if (c.verdict.outcome === "MATCH") return "match";
  if (c.verdict.outcome === "NEEDS_EVIDENCE") return "needs evidence";
  return "no match";
}

function actionLabel(c: Case): string {
  const missing = c.verdict.missing[0];
  return missing ? `Answer one question: ${missing}` : "Add the missing evidence";
}

/**
 * One case, rendered as the swing tag that should have been on the object.
 *
 * Order is the order a person needs it in: which notice, what the thing is, what
 * it does to you, what it cost, what the engine checked, then the one decision.
 */
export function QueueRecord({ item }: { item: Case }) {
  const checks = item.verdict.checks;
  const passed = checks.filter((k) => k.passed).length;
  const recipient = item.recall.contact_email ?? item.recall.contact_phone ?? "the manufacturer";

  return (
    <article className="tag">
      <div className="tag-head">
        <span className="label" style={{ color: "var(--ink)" }}>
          {item.recall.source} {item.recall.recall_number}
        </span>
        <StatusMark status={item.status} />
      </div>

      <div className="tag-body">
        <Link href={`/case/${item.case_id}`}>
          <h2 className="tag-title">{item.purchase.description}</h2>
        </Link>

        <p className="band">{firstSentence(item.recall.hazards[0] ?? item.recall.title, 260)}</p>

        <dl className="spec">
          <div className="spec-row">
            <dt className="spec-key">Bought</dt>
            <span className="spec-lead" aria-hidden="true" />
            <dd className="spec-val">{item.purchase.purchased_on}</dd>
          </div>
          {item.purchase.retailer ? (
            <div className="spec-row">
              <dt className="spec-key">From</dt>
              <span className="spec-lead" aria-hidden="true" />
              <dd className="spec-val">{item.purchase.retailer}</dd>
            </div>
          ) : null}
          {item.purchase.price !== null ? (
            <div className="spec-row">
              <dt className="spec-key">Paid</dt>
              <span className="spec-lead" aria-hidden="true" />
              <dd className="spec-val">{money(item.purchase.price)}</dd>
            </div>
          ) : null}
          <div className="spec-row">
            <dt className="spec-key">Notice</dt>
            <span className="spec-lead" aria-hidden="true" />
            <dd className="spec-val">{shortDate(item.recall.recall_date)}</dd>
          </div>
          <div className="spec-row">
            <dt className="spec-key">Verdict</dt>
            <span className="spec-lead" aria-hidden="true" />
            <dd className="spec-val">
              {verdictWord(item)}, {passed} of {checks.length}
            </dd>
          </div>
        </dl>

        <div className="checks">
          {checks.map((check) => (
            <span
              key={check.name}
              className={check.passed ? "chip" : "chip chip-fail"}
              title={check.detail}
            >
              {CHECK_WORD[check.name] ?? check.name.replace(/_/g, " ")}
              <span aria-hidden="true">{check.passed ? "✓" : "✗"}</span>
            </span>
          ))}
        </div>

        {item.verdict.missing.length ? (
          <p className="data mt-3" style={{ color: "var(--pending)" }}>
            missing: {item.verdict.missing.join("; ")}
          </p>
        ) : null}
      </div>

      <div className="tag-foot">
        {item.status === "awaiting_approval" ? (
          <RecordVerb
            caseId={item.case_id}
            remedy={remedyPhrase(item.recall.remedy_kinds)}
            recipient={recipient}
          />
        ) : (
          <Link href={`/case/${item.case_id}`} className="btn btn-secondary btn-block">
            {actionLabel(item)}
          </Link>
        )}

        <div className="mt-3 flex items-baseline justify-between gap-3">
          <Link href={`/case/${item.case_id}`} className="micro">
            Read the checks first
          </Link>
          <span className="micro">{ago(item.created_at)}</span>
        </div>
      </div>
    </article>
  );
}
