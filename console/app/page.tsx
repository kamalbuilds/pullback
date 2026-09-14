import type { Metadata } from "next";
import Link from "next/link";

import { EmptyQueue } from "@/components/EmptyQueue";
import { Provenance } from "@/components/Provenance";
import { QueueRecord } from "@/components/QueueRecord";
import { RunAgent } from "@/components/RunAgent";
import { latestRun, queue, throughputSentence, watch } from "@/lib/cases";
import { agentFunction, listCases } from "@/lib/store";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Pullback: recall decision queue",
};

const WORDS = ["no", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];

export default async function QueuePage() {
  const { cases, runs, source } = await listCases();
  const pending = queue(cases);
  const summary = watch(cases, latestRun(runs));

  if (!pending.length) {
    return (
      <>
        <EmptyQueue cases={cases} watch={summary} agentEnabled={Boolean(agentFunction())} />
        <Provenance source={source} count={cases.length} />
      </>
    );
  }

  const count = pending.length;
  const word = WORDS[count] ?? String(count);

  return (
    <>
      <section className="pt-12">
        <h1 className="statement max-w-[20ch]">
          {word} {count === 1 ? "decision is" : "decisions are"} waiting for you.
        </h1>
        <p className="prose-16 mt-6 max-w-[60ch]" style={{ color: "var(--ink-2)" }}>
          Everything else is handled. {throughputSentence(summary)}
        </p>
      </section>

      <section className="mt-10 border-t border-rule">
        {pending.map((item) => (
          <QueueRecord key={item.case_id} item={item} />
        ))}
      </section>

      <div className="mt-12 flex flex-wrap items-center gap-x-8 gap-y-5">
        <RunAgent enabled={Boolean(agentFunction())} />
        <Link href="/activity" className="data" style={{ color: "var(--seal)" }}>
          See everything the agent did unattended
        </Link>
      </div>

      <Provenance source={source} count={cases.length} />
    </>
  );
}
