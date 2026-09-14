import { STATUS_MARK, type CaseStatus } from "@/lib/cases";

export function StatusMark({ status }: { status: CaseStatus }) {
  const mark = STATUS_MARK[status] ?? { word: status.replace(/_/g, " "), tone: "var(--ink-3)" };
  return (
    <span className="label" style={{ color: mark.tone }}>
      {mark.word}
    </span>
  );
}
