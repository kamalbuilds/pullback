"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

type State =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "started"; text: string }
  | { kind: "failed"; text: string };

/** The run is fire and forget, so the page re-reads the table on this schedule instead. */
const POLL_AT = [12_000, 30_000, 55_000, 90_000];

export function RunAgent({ enabled }: { enabled: boolean }) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "idle" });
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  async function run() {
    setState({ kind: "starting" });
    try {
      const res = await fetch("/api/agent/run", { method: "POST" });
      const body = (await res.json()) as { message?: string; error?: string };
      if (!res.ok) {
        setState({ kind: "failed", text: body.error ?? `The agent refused the run (${res.status}).` });
        return;
      }
      setState({ kind: "started", text: body.message ?? "Run started." });
      timers.current = POLL_AT.map((ms) => setTimeout(() => router.refresh(), ms));
    } catch (error) {
      setState({ kind: "failed", text: (error as Error).message });
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-4">
      <button
        type="button"
        className="btn btn-secondary"
        disabled={!enabled || state.kind === "starting"}
        onClick={run}
        title={
          enabled
            ? "Invokes the screening Lambda now instead of waiting for the schedule"
            : "PULLBACK_AGENT_FUNCTION is not set on this deployment, so there is no agent to invoke"
        }
      >
        {state.kind === "starting" ? "Starting" : "Screen now"}
      </button>

      {!enabled ? (
        <p className="micro max-w-[52ch]">
          Scheduled runs are the normal path. The manual trigger is off because this deployment
          has no PULLBACK_AGENT_FUNCTION.
        </p>
      ) : null}

      {state.kind === "started" ? (
        <p className="micro max-w-[56ch]" style={{ color: "var(--seal)" }}>
          {state.text} This page re-reads the table while it runs.
        </p>
      ) : null}

      {state.kind === "failed" ? (
        <p className="micro max-w-[56ch]" style={{ color: "var(--alarm)" }}>
          {state.text}
        </p>
      ) : null}
    </div>
  );
}
