import { NextResponse } from "next/server";

import { agentUrl, HOUSEHOLD } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function POST() {
  const url = agentUrl();
  if (!url) {
    return NextResponse.json(
      {
        error:
          "PULLBACK_AGENT_URL is not set on this deployment. There is no endpoint to call, so no run was started.",
      },
      { status: 503 },
    );
  }

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ household: HOUSEHOLD, reason: "Manual run from the console." }),
      signal: AbortSignal.timeout(60_000),
    });
    const text = (await res.text()).slice(0, 400);
    if (!res.ok) {
      return NextResponse.json(
        { error: `The agent endpoint answered ${res.status}. ${text}` },
        { status: 502 },
      );
    }
    return NextResponse.json({ ok: true, message: `Agent run finished. ${text}`.trim() });
  } catch (error) {
    return NextResponse.json(
      { error: `The agent endpoint could not be reached. ${(error as Error).message}` },
      { status: 502 },
    );
  }
}
