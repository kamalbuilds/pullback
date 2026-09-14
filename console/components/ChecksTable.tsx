import type { Check } from "@/lib/cases";

const NAMES: Record<string, string> = {
  upc: "UPC",
  model: "model number",
  retailer: "retailer",
  sold_window: "sold window",
  price_band: "price band",
  description_overlap: "description",
};

export function ChecksTable({ checks }: { checks: Check[] }) {
  if (!checks.length) {
    return (
      <p className="data mt-4" style={{ color: "var(--ink-2)" }}>
        This case carries no checks, which means no verdict was computed for it.
      </p>
    );
  }

  return (
    <ul className="mt-5">
      {checks.map((check) => (
        <li
          key={check.name}
          className="border-b border-rule py-3.5"
          style={
            check.passed
              ? undefined
              : { borderLeft: "2px solid var(--alarm)", paddingLeft: "14px", background: "var(--alarm-wash)" }
          }
        >
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-[50px_128px_1fr] sm:items-baseline sm:gap-4">
            <span
              className="label"
              style={{ color: check.passed ? "var(--seal)" : "var(--alarm)" }}
            >
              {check.passed ? "pass" : "fail"}
            </span>
            <span className="data" style={{ color: "var(--ink)" }}>
              {NAMES[check.name] ?? check.name.replace(/_/g, " ")}
            </span>
            <span className="data" style={{ color: "var(--ink-2)" }}>
              {check.detail}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
