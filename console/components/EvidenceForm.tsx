"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { MISSING_FIELDS } from "@/lib/cases";

interface Ask {
  missing: string;
  field: string;
  label: string;
  type: "text" | "number" | "date";
  help: string;
}

function asks(missing: string[]): Ask[] {
  return missing.map((m) => {
    const mapped = MISSING_FIELDS[m];
    return mapped
      ? { missing: m, field: mapped.field as string, label: mapped.label, type: mapped.type, help: mapped.help }
      : { missing: m, field: "note", label: m, type: "text" as const, help: "Recorded on the case for the next run." };
  });
}

export function EvidenceForm({ caseId, missing }: { caseId: string; missing: string[] }) {
  const router = useRouter();
  const fields = asks(missing);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const filled = fields.filter((f) => (values[f.field] ?? "").trim().length > 0);
    if (!filled.length) {
      setError("Fill in at least one answer before sending it back to the agent.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/cases/${caseId}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action: "evidence",
          values: Object.fromEntries(filled.map((f) => [f.field, values[f.field].trim()])),
        }),
      });
      const body = (await res.json()) as { error?: string };
      if (!res.ok) {
        setError(body.error ?? `The write failed with status ${res.status}.`);
        setBusy(false);
        return;
      }
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mt-8 rounded-[4px] border border-rule-strong p-6"
      style={{ background: "var(--sheet)" }}
    >
      <p className="prose-16 max-w-[54ch]">
        The agent will not send a claim it cannot defend. Answer this and the next run recomputes
        the verdict with your answer in the checks.
      </p>

      <div className="mt-6 grid gap-5 sm:grid-cols-2">
        {fields.map((field) => (
          <div key={field.field}>
            <label className="label block" htmlFor={`f-${field.field}`}>
              {field.label}
            </label>
            <input
              id={`f-${field.field}`}
              className="field mt-2"
              type={field.type === "number" ? "number" : field.type === "date" ? "date" : "text"}
              step={field.type === "number" ? "0.01" : undefined}
              inputMode={field.type === "number" ? "decimal" : undefined}
              value={values[field.field] ?? ""}
              onChange={(e) => setValues({ ...values, [field.field]: e.target.value })}
            />
            <p className="micro mt-2">{field.help}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Sending" : "Send to the agent"}
        </button>
      </div>

      {error ? (
        <p className="data mt-4" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </form>
  );
}
