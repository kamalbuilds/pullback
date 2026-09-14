"""Durable case and recall state, over DynamoDB.

Two tables, both already provisioned, both PAY_PER_REQUEST:

    pullback-cases    PK household (S)  SK case_id (S)
    pullback-recalls  PK source (S)     SK recall_number (S)

This module is the only thing in the codebase that talks to DynamoDB. It moves
plain JSON-shaped dicts in and out; nothing here should leak boto3 types
(Decimal, sets) past its own boundary.

Idempotency: `put_case` uses read-modify-write, not a ConditionExpression. A
conditional put (`attribute_not_exists(case_id)`) only protects the *first*
write; every write after that needs to merge with what is already there
(keep created_at, append to timeline, let everything else including status
and verdict be replaced by the caller's newer view). Merging a list and
picking a min() over created_at is not expressible as a single
ConditionExpression, so it has to happen in Python. The tradeoff this
accepts: two concurrent writers for the exact same case_id can race between
the read and the write and one can clobber the other's timeline entry. That
race is acceptable here because a case_id is only ever written by the
scheduled matching pass for one household, run one at a time, never two
Lambda invocations racing on the same purchase+recall pair. If that stops
being true, swap the write for a DynamoDB transaction that reads the item
inside the transaction.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any

import boto3

CASES_TABLE = "pullback-cases"
RECALLS_TABLE = "pullback-recalls"


def _to_dynamo(value: Any) -> Any:
    """Recursively convert plain Python values into what boto3's DynamoDB
    resource will accept: floats become Decimal, dataclasses become dicts,
    tuples become lists."""
    if is_dataclass(value) and not isinstance(value, type):
        return _to_dynamo(asdict(value))
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value: Any) -> Any:
    """Recursively convert DynamoDB's Decimal back into plain int/float so
    the console can json.dumps() the result with no custom encoder."""
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if as_int == value else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


class CaseStore:
    def __init__(self, resource: Any = None) -> None:
        self._ddb = resource or boto3.resource("dynamodb")
        self._table = self._ddb.Table(CASES_TABLE)

    @staticmethod
    def case_id(household: str, purchase_id: str, recall_number: str) -> str:
        """Deterministic idempotency key. Same household+purchase+recall,
        run through this a thousand times, must always name the same case."""
        raw = f"{household}|{purchase_id}|{recall_number}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def get_case(self, household: str, case_id: str) -> dict | None:
        resp = self._table.get_item(
            Key={"household": household, "case_id": case_id}, ConsistentRead=True
        )
        item = resp.get("Item")
        return _from_dynamo(item) if item else None

    def list_cases(self, household: str, status: str | None = None) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        items: list[dict] = []
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("household").eq(household)}
        while True:
            resp = self._table.query(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        cases = [_from_dynamo(i) for i in items]
        if status is not None:
            cases = [c for c in cases if c.get("status") == status]
        cases.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
        return cases

    def put_case(self, case: dict) -> dict:
        """Idempotent upsert. If a case already exists at this
        (household, case_id), keep its created_at and grow its timeline
        instead of overwriting them; every other field takes the caller's
        new value. See module docstring for why this is read-modify-write
        rather than a ConditionExpression."""
        household, case_id = case["household"], case["case_id"]
        existing = self.get_case(household, case_id)

        merged = dict(case)
        if existing is not None:
            merged["created_at"] = existing.get("created_at", case.get("created_at"))
            existing_timeline = existing.get("timeline", [])
            new_timeline = case.get("timeline", [])
            # Append only entries the existing item doesn't already have,
            # keyed on (at, event) so replaying the same run twice doesn't
            # duplicate timeline lines.
            seen = {(e.get("at"), e.get("event")) for e in existing_timeline}
            grown = list(existing_timeline)
            for e in new_timeline:
                key = (e.get("at"), e.get("event"))
                if key not in seen:
                    grown.append(e)
                    seen.add(key)
            merged["timeline"] = grown

        self._table.put_item(Item=_to_dynamo(merged))
        return merged

    def append_timeline(self, household: str, case_id: str, event: str, detail: str) -> dict:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        entry = {"at": now, "event": event, "detail": detail}
        resp = self._table.update_item(
            Key={"household": household, "case_id": case_id},
            UpdateExpression=(
                "SET timeline = list_append(if_not_exists(timeline, :empty), :entry), "
                "updated_at = :now"
            ),
            ExpressionAttributeValues={
                ":entry": _to_dynamo([entry]),
                ":empty": [],
                ":now": now,
            },
            ReturnValues="ALL_NEW",
        )
        return _from_dynamo(resp["Attributes"])

    def set_status(self, household: str, case_id: str, status: str) -> dict:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        resp = self._table.update_item(
            Key={"household": household, "case_id": case_id},
            UpdateExpression="SET #s = :status, updated_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": status, ":now": now},
            ReturnValues="ALL_NEW",
        )
        return _from_dynamo(resp["Attributes"])


class RecallStore:
    def __init__(self, resource: Any = None) -> None:
        self._ddb = resource or boto3.resource("dynamodb")
        self._table = self._ddb.Table(RECALLS_TABLE)

    def put_recalls(self, recalls: list[Any]) -> int:
        """Bulk upsert. Accepts either plain dicts or the Recall dataclass
        from agent.feeds.base/cpsc; either way each item must carry
        `source` and `recall_number`. Returns the count written."""
        count = 0
        with self._table.batch_writer(overwrite_by_pkeys=["source", "recall_number"]) as batch:
            for recall in recalls:
                item = asdict(recall) if is_dataclass(recall) else dict(recall)
                item = _to_dynamo(_stringify_dates(item))
                batch.put_item(Item=item)
                count += 1
        return count

    def all_recalls(self, source: str | None = None) -> list[dict]:
        items: list[dict] = []
        if source is not None:
            from boto3.dynamodb.conditions import Key

            kwargs: dict[str, Any] = {"KeyConditionExpression": Key("source").eq(source)}
            while True:
                resp = self._table.query(**kwargs)
                items.extend(resp.get("Items", []))
                last = resp.get("LastEvaluatedKey")
                if not last:
                    break
                kwargs["ExclusiveStartKey"] = last
        else:
            kwargs = {}
            while True:
                resp = self._table.scan(**kwargs)
                items.extend(resp.get("Items", []))
                last = resp.get("LastEvaluatedKey")
                if not last:
                    break
                kwargs["ExclusiveStartKey"] = last
        return [_from_dynamo(i) for i in items]


def _stringify_dates(value: Any) -> Any:
    """Recall dataclasses carry datetime.date fields (recall_date, and
    sold_start/sold_end inside constraints). DynamoDB has no date type, so
    these become ISO strings on the way in; agent.feeds/agent.engine
    re-parse them with date.fromisoformat on the way back out."""
    import datetime as _dt

    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _stringify_dates(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify_dates(v) for v in value]
    return value
