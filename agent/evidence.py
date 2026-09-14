"""The durable artifact: an evidence pack a human can audit without running code.

Every case gets three files at s3://pullback-evidence-<account>/cases/<household>/<case_id>/:

    case.json      the full case, byte for byte what is in DynamoDB
    decision.txt    a plain-English rendering of every check that ran, what it
                    found, and why the outcome is what it is
    claim.txt       the claim message that was (or would be) sent

The point of decision.txt specifically: six months from now, with the code
long since changed, someone should be able to open this one file and verify
the decision was sound without re-running anything.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import boto3

BUCKET = "pullback-evidence-079415246611"


def _key_prefix(household: str, case_id: str) -> str:
    return f"cases/{household}/{case_id}"


def _render_decision(case: dict) -> str:
    verdict = case.get("verdict") or {}
    purchase = case.get("purchase") or {}
    recall = case.get("recall") or {}
    lines: list[str] = []

    lines.append("PULLBACK DECISION RECORD")
    lines.append("=" * 40)
    lines.append(f"case_id      {case.get('case_id', '')}")
    lines.append(f"household    {case.get('household', '')}")
    lines.append(f"status       {case.get('status', '')}")
    lines.append(f"created_at   {case.get('created_at', '')}")
    lines.append(f"updated_at   {case.get('updated_at', '')}")
    lines.append("")

    lines.append("PURCHASE")
    lines.append("-" * 40)
    for field in ("purchase_id", "description", "retailer", "purchased_on", "price", "quantity", "upc", "model"):
        if purchase.get(field) not in (None, ""):
            lines.append(f"  {field:<14} {purchase.get(field)}")
    lines.append("")

    lines.append("RECALL")
    lines.append("-" * 40)
    for field in ("source", "recall_number", "title", "url", "recall_date"):
        if recall.get(field) not in (None, ""):
            lines.append(f"  {field:<14} {recall.get(field)}")
    if recall.get("hazards"):
        lines.append(f"  hazards        {', '.join(recall['hazards'])}")
    if recall.get("remedy_kinds"):
        lines.append(f"  remedy_kinds   {', '.join(recall['remedy_kinds'])}")
    if recall.get("contact_email"):
        lines.append(f"  contact_email  {recall.get('contact_email')}")
    if recall.get("contact_phone"):
        lines.append(f"  contact_phone  {recall.get('contact_phone')}")
    lines.append("")

    lines.append(f"VERDICT: {verdict.get('outcome', 'UNKNOWN')}")
    lines.append("-" * 40)
    for check in verdict.get("checks", []):
        mark = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"  [{mark}] {check.get('name', '')}: {check.get('detail', '')}")
    if verdict.get("missing"):
        lines.append("")
        lines.append("  Missing to reach a firm verdict:")
        for item in verdict["missing"]:
            lines.append(f"    - {item}")
    if verdict.get("evidence_id"):
        lines.append("")
        lines.append(f"  evidence_id: {verdict['evidence_id']}")
    lines.append("")

    lines.append("TIMELINE")
    lines.append("-" * 40)
    for entry in case.get("timeline", []):
        lines.append(f"  {entry.get('at', '')}  {entry.get('event', ''):<20} {entry.get('detail', '')}")
    lines.append("")

    lines.append(f"generated_at   {datetime.now(timezone.utc).isoformat()}")
    return "\n".join(lines) + "\n"


def write_pack(case: dict, client: Any = None) -> str:
    """Build the evidence pack for `case` and upload it. Returns the
    s3:// URI of the pack's directory (no trailing object key)."""
    household = case["household"]
    case_id = case["case_id"]
    prefix = _key_prefix(household, case_id)
    s3 = client or boto3.client("s3")

    case_json = json.dumps(case, indent=2, sort_keys=True)
    decision_txt = _render_decision(case)
    claim_txt = case.get("claim_text") or (
        "No claim has been drafted for this case yet. "
        f"Verdict is {(case.get('verdict') or {}).get('outcome', 'UNKNOWN')}."
    )

    s3.put_object(Bucket=BUCKET, Key=f"{prefix}/case.json", Body=case_json.encode("utf-8"), ContentType="application/json")
    s3.put_object(Bucket=BUCKET, Key=f"{prefix}/decision.txt", Body=decision_txt.encode("utf-8"), ContentType="text/plain")
    s3.put_object(Bucket=BUCKET, Key=f"{prefix}/claim.txt", Body=claim_txt.encode("utf-8"), ContentType="text/plain")

    return f"s3://{BUCKET}/{prefix}/"


def presigned_url(uri: str, expires: int = 3600, key_suffix: str = "decision.txt", client: Any = None) -> str:
    """Presigned GET for a file inside the pack at `uri` (an s3://.../
    directory URI as returned by write_pack). Defaults to decision.txt
    since that is the file a human actually wants to open."""
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri}")
    without_scheme = uri[len("s3://"):]
    bucket, _, prefix = without_scheme.partition("/")
    key = f"{prefix.rstrip('/')}/{key_suffix}" if not prefix.endswith(key_suffix) else prefix
    s3 = client or boto3.client("s3")
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
    )
