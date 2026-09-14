import type { Metadata } from "next";
import Link from "next/link";

import { EmptyQueue } from "@/components/EmptyQueue";
import { OperatorStrip } from "@/components/OperatorStrip";
import { Shelf } from "@/components/Shelf";
import { Provenance } from "@/components/Provenance";
import { QueueRecord } from "@/components/QueueRecord";
import { RunAgent } from "@/components/RunAgent";
import { latestRun, queue, watch } from "@/lib/cases";
import { agentFunction, listCases } from "@/lib/store";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Pullback: recall decision queue",
};

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

  return (
    <>
      <OperatorStrip pending={pending.length} cases={cases} watch={summary} household="Kamal" />

      <section className="tag-grid">
        {pending.map((item) => (
          <QueueRecord key={item.case_id} item={item} />
        ))}
      </section>

      <Shelf cases={cases} />

      <div className="mt-12 flex flex-wrap items-center gap-x-8 gap-y-5">
        <RunAgent enabled={Boolean(agentFunction())} />
        <Link
          href="/activity"
          className="data"
          style={{ textDecoration: "underline", textUnderlineOffset: "3px" }}
        >
          See everything the agent did unattended
        </Link>
      </div>

      <Provenance source={source} count={cases.length} />
    </>
  );
}
