"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type State = { kind: "idle" } | { kind: "running" } | { kind: "done"; text: string } | { kind: "failed"; text: string };

export function RunAgent({ enabled }: { enabled: boolean }) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "idle" });

  async function run() {
    setState({ kind: "running" });
    try {
      const res = await fetch("/api/agent/run", { method: "POST" });
      const body = (await res.json()) as { message?: string; error?: string };
      if (!res.ok) {
        setState({ kind: "failed", text: body.error ?? `The agent returned ${res.status}.` });
        return;
      }
      setState({ kind: "done", text: body.message ?? "The agent run finished." });
      router.refresh();
    } catch (error) {
      setState({ kind: "failed", text: (error as Error).message });
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-4">
      <button
        type="button"
        className="btn btn-secondary"
        disabled={!enabled || state.kind === "running"}
        onClick={run}
        title={
          enabled
            ? "Runs the screening pass now instead of waiting for the schedule"
            : "PULLBACK_AGENT_URL is not set on this deployment, so there is no agent endpoint to call"
        }
      >
        {state.kind === "running" ? "Screening" : "Screen now"}
      </button>
      {!enabled ? (
        <p className="micro max-w-[52ch]">
          Scheduled runs are the normal path. The manual trigger is off because this deployment has
          no PULLBACK_AGENT_URL.
        </p>
      ) : null}
      {state.kind === "done" ? (
        <p className="micro" style={{ color: "var(--seal)" }}>
          {state.text}
        </p>
      ) : null}
      {state.kind === "failed" ? (
        <p className="micro" style={{ color: "var(--alarm)" }}>
          {state.text}
        </p>
      ) : null}
    </div>
  );
}
