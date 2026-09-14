import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  DynamoDBClient,
  QueryCommand,
  UpdateItemCommand,
  type AttributeValue,
} from "@aws-sdk/client-dynamodb";
import { marshall, unmarshall } from "@aws-sdk/util-dynamodb";

import { isRun, RUN_PREFIX, type Case, type Run, type TimelineEntry } from "./cases";

export const TABLE = process.env.PULLBACK_TABLE ?? "pullback-cases";
export const HOUSEHOLD = process.env.PULLBACK_HOUSEHOLD ?? "kamal";
export const REGION = process.env.PULLBACK_AWS_REGION ?? process.env.AWS_REGION ?? "us-east-1";

export type Source = "dynamodb" | "local-capture";

/**
 * Vercel reserves every AWS_ prefixed name for its own Lambda runtime, and that runtime's
 * role has no access to this table. So the console carries its own least privilege key under
 * a PULLBACK_ prefix, and only falls back to the ambient chain when a developer has a profile
 * exported. With neither, it reads the capture taken from the same table with
 * `aws dynamodb scan`, so local work still renders real rows.
 */
export function explicitCredentials():
  | { accessKeyId: string; secretAccessKey: string }
  | undefined {
  const accessKeyId = process.env.PULLBACK_AWS_ACCESS_KEY_ID?.trim();
  const secretAccessKey = process.env.PULLBACK_AWS_SECRET_ACCESS_KEY?.trim();
  return accessKeyId && secretAccessKey ? { accessKeyId, secretAccessKey } : undefined;
}

function hasCredentials(): boolean {
  return Boolean(explicitCredentials() || process.env.AWS_PROFILE);
}

let client: DynamoDBClient | null = null;

function db(): DynamoDBClient {
  if (!client) {
    client = new DynamoDBClient({ region: REGION, credentials: explicitCredentials() });
  }
  return client;
}

function coerce(raw: Record<string, unknown>): Case {
  const c = raw as unknown as Case;
  return {
    ...c,
    timeline: (c.timeline ?? []) as TimelineEntry[],
    verdict: {
      outcome: c.verdict?.outcome ?? "NEEDS_EVIDENCE",
      checks: c.verdict?.checks ?? [],
      missing: c.verdict?.missing ?? [],
      evidence_id: c.verdict?.evidence_id ?? "",
    },
    recall: {
      ...c.recall,
      hazards: c.recall?.hazards ?? [],
      remedy_kinds: c.recall?.remedy_kinds ?? [],
    },
    purchase: {
      ...c.purchase,
      price: c.purchase?.price === undefined ? null : c.purchase.price,
      quantity: c.purchase?.quantity ?? 1,
    },
  };
}

async function fromCapture(): Promise<{ cases: Case[]; runs: Run[] }> {
  const file = path.join(process.cwd(), ".local", "scan.json");
  let raw: string;
  try {
    raw = await readFile(file, "utf8");
  } catch {
    throw new Error(
      "No AWS credentials are set and there is no local capture at .local/scan.json, so there is nothing true to render. Set PULLBACK_AWS_ACCESS_KEY_ID and PULLBACK_AWS_SECRET_ACCESS_KEY.",
    );
  }
  const parsed = JSON.parse(raw) as { Items: Record<string, AttributeValue>[] };
  const rows = parsed.Items.map((item) => unmarshall(item)).filter(
    (r) => r.household === HOUSEHOLD,
  );
  return split(rows);
}

/**
 * One Query returns cases and run records together, because they share the partition key.
 * They are split here and nowhere else, so no screen can accidentally render a run as a case.
 */
function split(rows: Record<string, unknown>[]): { cases: Case[]; runs: Run[] } {
  const cases: Case[] = [];
  const runs: Run[] = [];
  for (const row of rows) {
    if (isRun(row as { case_id?: string; record_type?: string })) {
      runs.push(row as unknown as Run);
    } else {
      cases.push(coerce(row));
    }
  }
  return { cases, runs };
}

export async function listCases(): Promise<{ cases: Case[]; runs: Run[]; source: Source }> {
  if (!hasCredentials()) {
    return { ...(await fromCapture()), source: "local-capture" };
  }
  const out = await db().send(
    new QueryCommand({
      TableName: TABLE,
      KeyConditionExpression: "household = :h",
      ExpressionAttributeValues: marshall({ ":h": HOUSEHOLD }),
    }),
  );
  return { ...split((out.Items ?? []).map((item) => unmarshall(item))), source: "dynamodb" };
}

export async function getCase(caseId: string): Promise<{ item: Case | null; source: Source }> {
  if (caseId.startsWith(RUN_PREFIX)) return { item: null, source: "dynamodb" };
  const { cases, source } = await listCases();
  return { item: cases.find((c) => c.case_id === caseId) ?? null, source };
}

export interface Mutation {
  status?: Case["status"];
  events: TimelineEntry[];
  purchasePatch?: Record<string, string | number | null>;
}

/**
 * One conditional update per action. The condition keeps a second tab, or a retried POST,
 * from writing a decision onto a case that has already moved on.
 */
export async function applyMutation(
  caseId: string,
  expectedStatus: Case["status"],
  mutation: Mutation,
): Promise<void> {
  if (!hasCredentials()) {
    throw new Error(
      "No AWS credentials are present, so this console is reading a local capture and cannot write.",
    );
  }

  const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  const names: Record<string, string> = { "#status": "status" };
  const values: Record<string, unknown> = {
    ":expected": expectedStatus,
    ":events": mutation.events,
    ":empty": [] as TimelineEntry[],
    ":now": now,
  };
  const sets = [
    "timeline = list_append(if_not_exists(timeline, :empty), :events)",
    "updated_at = :now",
  ];

  if (mutation.status) {
    sets.push("#status = :status");
    values[":status"] = mutation.status;
  }

  for (const [field, value] of Object.entries(mutation.purchasePatch ?? {})) {
    const key = field.replace(/[^a-z_]/gi, "");
    names[`#p_${key}`] = key;
    sets.push(`purchase.#p_${key} = :p_${key}`);
    values[`:p_${key}`] = value;
  }

  await db().send(
    new UpdateItemCommand({
      TableName: TABLE,
      Key: marshall({ household: HOUSEHOLD, case_id: caseId }),
      UpdateExpression: `SET ${sets.join(", ")}`,
      ConditionExpression: "#status = :expected",
      ExpressionAttributeNames: names,
      ExpressionAttributeValues: marshall(values, { removeUndefinedValues: true }),
    }),
  );
}

/**
 * The agent runs as a Lambda. Its Function URL is dead on this account (403 even with a
 * correct resource policy and a SigV4-signed request, because the account sits in a
 * restricted concurrency tier), so the console invokes the function by name with the same
 * server-side credentials it reads DynamoDB with. Nothing about the agent is reachable from
 * the browser.
 */
export function agentFunction(): string | null {
  const name = process.env.PULLBACK_AGENT_FUNCTION?.trim();
  if (!name || !hasCredentials()) return null;
  return name;
}

/**
 * A full screening pass takes 30 to 90 seconds, which outlives a serverless request, so the
 * invoke is asynchronous. A 202 means the run started. It never means the run finished, and
 * the console must not say otherwise.
 */
export async function startAgentRun(payload: Record<string, unknown>): Promise<number> {
  const name = agentFunction();
  if (!name) throw new Error("No agent function is configured on this deployment.");
  const { InvokeCommand, LambdaClient } = await import("@aws-sdk/client-lambda");
  const lambda = new LambdaClient({ region: REGION, credentials: explicitCredentials() });
  const out = await lambda.send(
    new InvokeCommand({
      FunctionName: name,
      InvocationType: "Event",
      Payload: Buffer.from(JSON.stringify({ household: HOUSEHOLD, ...payload })),
    }),
  );
  if (out.StatusCode !== 202) {
    throw new Error(`Lambda ${name} answered ${out.StatusCode} instead of accepting the run.`);
  }
  return out.StatusCode;
}
