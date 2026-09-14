"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * The action on a queue row used to be a link that navigated somewhere else. A
 * reader could not tell the world ever changed, because nothing on the page ever
 * did. This is the same decision, taken where it is read.
 *
 * It posts to the route the case page already uses, so there is one write path and
 * one set of guards. On success the row stamps itself and the headline count drops,
 * because a queue that never shortens is a list.
 */
export function RecordVerb({
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
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function send(action: "approve" | "decline") {
    setBusy(action);
    setError(null);
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}`, {
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
      const at = new Date().toISOString().slice(0, 16).replace("T", " ");
      setDone(
        action === "approve"
          ? `Sent to ${recipient} · ${at} UTC`
          : `Closed as not yours · ${at} UTC`,
      );
      setBusy(null);
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
      setBusy(null);
    }
  }

  if (done) {
    return (
      <p className="micro" style={{ color: "var(--seal)" }}>
        {done}
      </p>
    );
  }

  return (
    <div>
      <div className="flex flex-col gap-2">
        <button
          type="button"
          className="btn btn-primary btn-block"
          disabled={busy !== null}
          onClick={() => send("approve")}
        >
          {busy === "approve" ? "Sending" : `Send it for ${remedy}`}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-block"
          disabled={busy !== null}
          onClick={() => send("decline")}
          title="Closes the case and stops Pullback raising this notice again"
        >
          {busy === "decline" ? "Closing" : "Not mine"}
        </button>
      </div>
      {error ? (
        <p className="data mt-3" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
