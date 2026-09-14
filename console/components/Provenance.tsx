import { HOUSEHOLD, REGION, TABLE, type Source } from "@/lib/store";
import { plural } from "@/lib/format";

/** Where the numbers above came from. A figure with no origin is a rumour with good posture. */
export function Provenance({ source, count }: { source: Source; count: number }) {
  return (
    <p className="micro mt-20 border-t border-rule pt-6">
      {plural(count, "case")} read from{" "}
      {source === "dynamodb"
        ? `DynamoDB table ${TABLE} in ${REGION}`
        : `a local capture of DynamoDB table ${TABLE}`}
      , household {HOUSEHOLD}, at {new Date().toISOString().replace("T", " ").slice(0, 19)} UTC.
    </p>
  );
}
