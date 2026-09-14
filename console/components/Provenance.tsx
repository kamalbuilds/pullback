import { HOUSEHOLD, REGION, TABLE, type Source } from "@/lib/store";
import { plural, stampUTC } from "@/lib/format";

/** Where the numbers above came from. A figure with no origin is a rumour with good posture. */
export function Provenance({ source, count }: { source: Source; count: number }) {
  const origin =
    source === "dynamodb"
      ? `DynamoDB table ${TABLE} in ${REGION}`
      : `a local capture of DynamoDB table ${TABLE}`;
  return (
    <p className="micro mt-20 border-t border-rule pt-6">
      {`${plural(count, "case")} read from ${origin}, household ${HOUSEHOLD}, at ${stampUTC(new Date().toISOString())}.`}
    </p>
  );
}
