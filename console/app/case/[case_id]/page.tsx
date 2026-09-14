import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CaseTimeline } from "@/components/CaseTimeline";
import { ChecksTable } from "@/components/ChecksTable";
import { DecisionActions } from "@/components/DecisionActions";
import { EvidenceForm } from "@/components/EvidenceForm";
import { Provenance } from "@/components/Provenance";
import { StatusMark } from "@/components/StatusMark";
import { needsHuman, sortedTimeline } from "@/lib/cases";
import { firstSentence, longDate, money, remedyPhrase } from "@/lib/format";
import { getCase } from "@/lib/store";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ case_id: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { case_id } = await params;
  const { item } = await getCase(case_id);
  if (!item) return { title: "Pullback: case not found" };
  return { title: `Pullback: ${item.purchase.description}` };
}

export default async function CasePage({ params }: Params) {
  const { case_id } = await params;
  const { item, source } = await getCase(case_id);
  if (!item) notFound();

  const timeline = sortedTimeline(item);
  const passed = item.verdict.checks.filter((c) => c.passed).length;
  const total = item.verdict.checks.length;
  const recipient =
    item.recall.contact_email ?? item.recall.contact_phone ?? item.recall.title.split(" Recalls")[0];
  const open = needsHuman(item);
  const evidenceSent = timeline.some((e) => e.event === "evidence.provided");
  // The header already carries the first hazard sentence. Only show what it did not.
  const headline = firstSentence(item.recall.hazards[0] ?? item.recall.title, 400);
  const extraHazards = item.recall.hazards.filter((h) => h.trim() !== headline.trim());

  return (
    <>
      <div className="pt-10">
        <Link href="/" className="label">
          Back to the queue
        </Link>
      </div>

      <header className="mt-8 border-b border-rule pb-10">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <StatusMark status={item.status} />
          <span className="micro">case {item.case_id}</span>
          <span className="micro">
            {item.recall.source} {item.recall.recall_number}
          </span>
        </div>

        <h1 className="statement mt-5 max-w-[24ch]">{item.purchase.description}</h1>

        <p className="data mt-4" style={{ color: "var(--ink-2)" }}>
          bought {item.purchase.purchased_on}
          {item.purchase.retailer ? ` at ${item.purchase.retailer}` : ""} for{" "}
          {money(item.purchase.price)}
          {item.purchase.quantity > 1 ? `, quantity ${item.purchase.quantity}` : ""}
        </p>

        <p className="hazard mt-6 max-w-[64ch]">
          {headline}
        </p>
      </header>

      <div className="mt-12 grid gap-14 lg:grid-cols-[1fr_330px] lg:gap-16">
        <div>
          <section>
            <h2 className="label">What the agent checked</h2>
            <p className="prose-16 mt-3 max-w-[58ch]" style={{ color: "var(--ink-2)" }}>
              {item.verdict.outcome === "MATCH"
                ? `Every checkable constraint in the notice passed against this purchase record, ${passed} of ${total}. The verdict is arithmetic on dates, money and text, not a guess by a model.`
                : item.verdict.outcome === "NEEDS_EVIDENCE"
                  ? `${passed} of ${total} available checks passed. The notice constrains more than the purchase record can answer, so the agent stopped rather than guess.`
                  : `A constraint failed, so this case was closed and nothing was sent. ${passed} of ${total} checks passed.`}
            </p>
            <ChecksTable checks={item.verdict.checks} />
            {item.verdict.missing.length ? (
              <p className="data mt-5 max-w-[62ch]" style={{ color: "var(--ink-2)" }}>
                still missing: {item.verdict.missing.join("; ")}
              </p>
            ) : null}
            <p className="micro mt-4">evidence id {item.verdict.evidence_id}</p>
          </section>

          <section className="mt-16">
            <h2 className="label">The claim, exactly as it goes out</h2>
            {item.claim_text ? (
              <>
                <p className="micro mt-3">to {recipient}</p>
                <pre
                  className="data mt-4 overflow-x-auto rounded-[2px] p-6"
                  style={{
                    background: "var(--sheet-2)",
                    color: "var(--ink)",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {item.claim_text}
                </pre>
              </>
            ) : (
              <p className="prose-16 mt-3 max-w-[58ch]" style={{ color: "var(--ink-2)" }}>
                No claim was drafted. The agent closed this case on its own and nobody was
                contacted.
              </p>
            )}
          </section>

          {open && item.status === "awaiting_approval" ? (
            <DecisionActions
              caseId={item.case_id}
              remedy={remedyPhrase(item.recall.remedy_kinds)}
              recipient={recipient}
            />
          ) : null}

          {open && item.status === "needs_evidence" ? (
            <EvidenceForm caseId={item.case_id} missing={item.verdict.missing} />
          ) : null}

          {!open && evidenceSent ? (
            <p
              className="data mt-8 rounded-[2px] border border-rule p-5"
              style={{ color: "var(--ink-2)" }}
            >
              Your answer is on the case. The next scheduled run recomputes the verdict with it.
            </p>
          ) : null}
        </div>

        <aside>
          <section>
            <h2 className="label">The notice</h2>
            <p className="prose-16 mt-3">{item.recall.title}</p>
            <p className="micro mt-3">
              {item.recall.source} {item.recall.recall_number}, published{" "}
              {longDate(item.recall.recall_date)}
            </p>
            <p className="mt-4">
              <a
                className="data"
                style={{ color: "var(--seal)", textDecoration: "underline", textUnderlineOffset: "3px" }}
                href={item.recall.url}
                target="_blank"
                rel="noreferrer"
              >
                Read the notice on cpsc.gov
              </a>
            </p>
          </section>

          <section className="mt-10">
            <h2 className="label">Remedy offered</h2>
            <p className="prose-16 mt-3" style={{ color: "var(--ink-2)" }}>
              The notice offers {remedyPhrase(item.recall.remedy_kinds)}.
            </p>
            {item.recall.contact_email ? (
              <p className="data mt-2" style={{ color: "var(--ink-2)" }}>
                {item.recall.contact_email}
              </p>
            ) : null}
            {item.recall.contact_phone ? (
              <p className="data mt-1" style={{ color: "var(--ink-2)" }}>
                {item.recall.contact_phone}
              </p>
            ) : null}
          </section>

          {extraHazards.length ? (
            <section className="mt-10">
              <h2 className="label">
                {extraHazards.length === item.recall.hazards.length
                  ? "Hazard, in full"
                  : "The rest of the hazard"}
              </h2>
              {extraHazards.map((hazard) => (
                <p key={hazard} className="prose-16 mt-3" style={{ color: "var(--ink-2)" }}>
                  {hazard}
                </p>
              ))}
            </section>
          ) : null}

          {item.evidence_uri ? (
            <section className="mt-10">
              <h2 className="label">Evidence bundle</h2>
              <p className="micro mt-3 break-all">{item.evidence_uri}</p>
            </section>
          ) : null}
        </aside>
      </div>

      <section className="mt-20">
        <h2 className="label">History</h2>
        <CaseTimeline entries={timeline} />
      </section>

      <Provenance source={source} count={1} />
    </>
  );
}
