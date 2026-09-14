"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function DecisionActions({
  caseId,
  remedy,
  recipient,
}: {
  caseId: string;
  remedy: string;
  recipient: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<"approve" | "decline" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function send(action: "approve" | "decline") {
    setBusy(action);
    setError(null);
    try {
      const res = await fetch(`/api/cases/${caseId}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const body = (await res.json()) as { error?: string };
      if (!res.ok) {
        setError(body.error ?? `The write failed with status ${res.status}.`);
        setBusy(null);
        return;
      }
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
      setBusy(null);
    }
  }

  return (
    <div className="mt-8 rounded-[2px] border border-rule-strong p-6" style={{ background: "var(--sheet)" }}>
      <p className="prose-16 max-w-[54ch]">
        Sending this asks {recipient} for {remedy}. Pullback keeps chasing it until the remedy
        lands or the manufacturer refuses in writing.
      </p>
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => send("approve")}>
          {busy === "approve" ? "Sending" : "Send the claim"}
        </button>
        <button
          type="button"
          className="btn btn-destructive"
          disabled={busy !== null}
          onClick={() => send("decline")}
          title="Closes the case and stops Pullback from raising this notice again"
        >
          {busy === "decline" ? "Closing" : "Not mine"}
        </button>
      </div>
      {error ? (
        <p className="data mt-4" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
