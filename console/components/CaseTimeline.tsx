import type { TimelineEntry } from "@/lib/cases";
import { clockUTC, longDate } from "@/lib/format";

export function CaseTimeline({ entries }: { entries: TimelineEntry[] }) {
  if (!entries.length) {
    return (
      <p className="data mt-4" style={{ color: "var(--ink-2)" }}>
        Nothing has happened on this case since it was written.
      </p>
    );
  }

  return (
    <ol className="mt-5">
      {entries.map((entry, index) => (
        <li key={`${entry.at}-${entry.event}-${index}`} className="border-t border-rule py-3.5">
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-[168px_190px_1fr] sm:items-baseline sm:gap-5">
            <span className="micro">
              {longDate(entry.at)} {clockUTC(entry.at)}
            </span>
            <span className="data" style={{ color: "var(--ink)" }}>
              {entry.event}
            </span>
            <span className="data" style={{ color: "var(--ink-2)" }}>
              {entry.detail}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}
