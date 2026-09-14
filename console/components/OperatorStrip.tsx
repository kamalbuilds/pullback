import type { Case, Watch } from "@/lib/cases";

/**
 * The block above the tag board. Whose house, how much is on them, what it
 * costs to close the tab, and one footnote about the pass that did the reading.
 */
export function OperatorStrip({
  pending,
  cases,
  watch,
  household,
}: {
  pending: number;
  cases: Case[];
  watch: Watch;
  household: string;
}) {
  const hazardous = cases.filter(
    (c) =>
      c.status === "awaiting_approval" &&
      /death|fatal|kill/i.test(`${c.recall.title} ${c.recall.hazards[0] ?? ""}`),
  ).length;

  const cost =
    hazardous > 0
      ? `${hazardous} of them ${hazardous === 1 ? "names" : "name"} a death or fatal hazard.`
      : pending > 0
        ? `${pending} recalled ${pending === 1 ? "item is" : "items are"} still in the house.`
        : "Nothing outstanding.";

  const synced = watch.lastRun ? watch.lastRun.slice(0, 16).replace("T", " ") : "just now";

  return (
    <section className="count-block">
      <div className="count-meta">
        <span className="label" style={{ color: "var(--ink)" }}>
          Household {household}
        </span>
        <span className="micro">screened {synced} UTC</span>
      </div>

      <h1 className="statement mt-5 max-w-[20ch]">
        {pending} {pending === 1 ? "tag needs" : "tags need"} a decision.
      </h1>

      <p className="count-cost">{cost}</p>

      <p className="count-machine micro">
        The overnight pass did the reading. {watch.purchases} purchases screened
        {watch.corpus ? ` against ${watch.corpus} notices` : ""}
        {watch.closedAlone ? `, ${watch.closedAlone} closed without asking` : ""}.
      </p>
    </section>
  );
}
