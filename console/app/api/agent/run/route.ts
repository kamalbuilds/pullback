import { NextResponse } from "next/server";

import { agentFunction, startAgentRun } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function POST() {
  const name = agentFunction();
  if (!name) {
    return NextResponse.json(
      {
        error:
          "PULLBACK_AGENT_FUNCTION is not set on this deployment, or it has no AWS credentials. No run was started.",
      },
      { status: 503 },
    );
  }

  try {
    await startAgentRun({ reason: "Manual run from the console." });
    return NextResponse.json({
      ok: true,
      message: `Run started on ${name}. A pass takes 30 to 90 seconds and writes straight to the table.`,
    });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 502 });
  }
}
