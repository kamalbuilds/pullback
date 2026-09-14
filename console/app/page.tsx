import type { Metadata } from "next";
import Link from "next/link";

import { EmptyQueue } from "@/components/EmptyQueue";
import { Provenance } from "@/components/Provenance";
import { QueueRecord } from "@/components/QueueRecord";
import { queue, watch } from "@/lib/cases";
import { plural } from "@/lib/format";
import { agentUrl, listCases } from "@/lib/store";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Pullback: recall decision queue",
};

const WORDS = ["no", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];

export default async function QueuePage() {
  const { cases, source } = await listCases();
  const pending = queue(cases);
  const summary = watch(cases);

  if (!pending.length) {
    return (
      <>
        <EmptyQueue cases={cases} watch={summary} agentEnabled={Boolean(agentUrl())} />
        <Provenance source={source} count={cases.length} />
      </>
    );
  }

  const count = pending.length;
  const word = WORDS[count] ?? String(count);

  return (
    <>
      <section className="pt-16">
        <h1 className="statement max-w-[20ch]">
          {word} {count === 1 ? "decision is" : "decisions are"} waiting for you.
        </h1>
        <p className="prose-16 mt-6 max-w-[58ch]" style={{ color: "var(--ink-2)" }}>
          Everything else is handled. Pullback has screened{" "}
          {plural(summary.purchases, "purchase")} in this household
          {summary.corpus ? ` against ${summary.corpus.toLocaleString("en-US")} recall notices` : ""} and
          closed {plural(summary.handled, "case")} without asking.
        </p>
      </section>

      <section className="mt-14 border-t border-rule">
        {pending.map((item) => (
          <QueueRecord key={item.case_id} item={item} />
        ))}
      </section>

      <p className="mt-10">
        <Link href="/activity" className="data" style={{ color: "var(--seal)" }}>
          See everything the agent did unattended
        </Link>
      </p>

      <Provenance source={source} count={cases.length} />
    </>
  );
}
