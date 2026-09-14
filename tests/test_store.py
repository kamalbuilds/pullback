"""Tests against the real pullback-cases / pullback-recalls tables and the
real evidence bucket in the palimpsest AWS account. No moto, no localstack:
this account is ours. Every test cleans up what it writes.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import boto3
import pytest
from boto3.dynamodb.conditions import Key

os.environ.setdefault("AWS_PROFILE", "palimpsest")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)

from agent.evidence import presigned_url, write_pack
from agent.store import CaseStore, RecallStore

HOUSEHOLD = "test-store-suite"


@pytest.fixture(scope="module")
def ddb():
    return boto3.resource("dynamodb")


@pytest.fixture(scope="module")
def s3():
    return boto3.client("s3")


@pytest.fixture()
def case_store(ddb):
    return CaseStore(resource=ddb)


@pytest.fixture()
def recall_store(ddb):
    return RecallStore(resource=ddb)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sample_case(purchase_id: str, recall_number: str) -> dict:
    now = _now()
    cid = CaseStore.case_id(HOUSEHOLD, purchase_id, recall_number)
    return {
        "household": HOUSEHOLD,
        "case_id": cid,
        "status": "needs_evidence",
        "purchase": {
            "purchase_id": purchase_id,
            "description": "Acme Toaster 2000",
            "retailer": "Target",
            "purchased_on": "2026-01-15",
            "price": 39.99,
            "quantity": 1,
            "upc": "012345678905",
            "model": "AC-2000",
        },
        "recall": {
            "source": "CPSC",
            "recall_number": recall_number,
            "title": "Acme Toaster 2000 recalled for fire hazard",
            "url": "https://www.cpsc.gov/example",
            "recall_date": "2026-02-01",
            "hazards": ["Fire"],
            "remedy_kinds": ["refund"],
            "contact_email": "recall@acme.example",
            "contact_phone": "800-555-0100",
        },
        "verdict": {
            "outcome": "NEEDS_EVIDENCE",
            "checks": [{"name": "upc", "passed": False, "detail": "no upc on file"}],
            "missing": ["the UPC printed on the box"],
            "evidence_id": f"{recall_number}:{purchase_id}:NEEDS_EVIDENCE",
        },
        "timeline": [{"at": now, "event": "verdict_computed", "detail": "NEEDS_EVIDENCE"}],
        "evidence_uri": "",
        "claim_text": "",
        "created_at": now,
        "updated_at": now,
    }


def _delete_case(ddb, case_id: str) -> None:
    ddb.Table("pullback-cases").delete_item(Key={"household": HOUSEHOLD, "case_id": case_id})


def _delete_evidence(s3, case_id: str) -> None:
    prefix = f"cases/{HOUSEHOLD}/{case_id}/"
    resp = s3.list_objects_v2(Bucket="pullback-evidence-079415246611", Prefix=prefix)
    for obj in resp.get("Contents", []):
        s3.delete_object(Bucket="pullback-evidence-079415246611", Key=obj["Key"])


class TestCaseIdIsDeterministic:
    def test_same_inputs_same_id(self):
        a = CaseStore.case_id("kamal", "purchase-1", "2026-1234")
        b = CaseStore.case_id("kamal", "purchase-1", "2026-1234")
        assert a == b
        assert len(a) == 16
        assert all(ch in "0123456789abcdef" for ch in a)

    def test_different_inputs_different_id(self):
        a = CaseStore.case_id("kamal", "purchase-1", "2026-1234")
        b = CaseStore.case_id("kamal", "purchase-2", "2026-1234")
        c = CaseStore.case_id("kamal", "purchase-1", "2026-5678")
        assert len({a, b, c}) == 3


class TestPutCaseIdempotency:
    def test_writing_same_case_twice_yields_one_item_created_at_preserved_timeline_grown(
        self, case_store, ddb
    ):
        purchase_id = f"purchase-{uuid.uuid4().hex[:8]}"
        recall_number = f"2026-{uuid.uuid4().hex[:6]}"
        case = _sample_case(purchase_id, recall_number)
        cid = case["case_id"]

        try:
            first = case_store.put_case(case)
            first_created_at = first["created_at"]
            assert first["timeline"] == case["timeline"]

            # Same case, run again as if the scheduled pass ran a second
            # time: same identifying fields, a later updated_at, one new
            # timeline entry the first write did not have.
            second_input = dict(case)
            second_input["updated_at"] = _now()
            second_input["timeline"] = case["timeline"] + [
                {"at": _now(), "event": "evidence_recorded", "detail": "pack written to s3://x"}
            ]
            second = case_store.put_case(second_input)

            assert second["created_at"] == first_created_at, "created_at must not move on re-write"
            assert len(second["timeline"]) == 2, "timeline must grow, not reset"
            assert second["timeline"][0] == case["timeline"][0]
            assert second["timeline"][1]["event"] == "evidence_recorded"

            # Exactly one item in the table for this (household, case_id).
            resp = ddb.Table("pullback-cases").query(
                KeyConditionExpression=Key("household").eq(HOUSEHOLD) & Key("case_id").eq(cid)
            )
            assert len(resp["Items"]) == 1

            # A third write with a duplicate timeline entry (at, event) must
            # not duplicate it.
            third_input = dict(second)
            third = case_store.put_case(third_input)
            assert len(third["timeline"]) == 2

            fetched = case_store.get_case(HOUSEHOLD, cid)
            assert fetched["created_at"] == first_created_at
            assert len(fetched["timeline"]) == 2
            assert fetched["purchase"]["price"] == 39.99
            assert isinstance(fetched["purchase"]["price"], float)
        finally:
            _delete_case(ddb, cid)

    def test_float_round_trips_as_plain_number(self, case_store, ddb):
        purchase_id = f"purchase-{uuid.uuid4().hex[:8]}"
        recall_number = f"2026-{uuid.uuid4().hex[:6]}"
        case = _sample_case(purchase_id, recall_number)
        cid = case["case_id"]
        try:
            case_store.put_case(case)
            fetched = case_store.get_case(HOUSEHOLD, cid)
            assert fetched["purchase"]["price"] == 39.99
            assert fetched["purchase"]["quantity"] == 1
            assert isinstance(fetched["purchase"]["quantity"], int)
        finally:
            _delete_case(ddb, cid)


class TestAppendTimelineAndSetStatus:
    def test_append_timeline_and_set_status(self, case_store, ddb):
        purchase_id = f"purchase-{uuid.uuid4().hex[:8]}"
        recall_number = f"2026-{uuid.uuid4().hex[:6]}"
        case = _sample_case(purchase_id, recall_number)
        cid = case["case_id"]
        try:
            case_store.put_case(case)
            grown = case_store.append_timeline(HOUSEHOLD, cid, "claim_sent", "emailed recall@acme.example")
            assert len(grown["timeline"]) == 2
            assert grown["timeline"][-1]["event"] == "claim_sent"

            updated = case_store.set_status(HOUSEHOLD, cid, "dispatched")
            assert updated["status"] == "dispatched"

            fetched = case_store.get_case(HOUSEHOLD, cid)
            assert fetched["status"] == "dispatched"
            assert len(fetched["timeline"]) == 2
        finally:
            _delete_case(ddb, cid)


class TestListCases:
    def test_list_cases_filters_by_status(self, case_store, ddb):
        ids = []
        try:
            for i in range(2):
                purchase_id = f"purchase-{uuid.uuid4().hex[:8]}"
                recall_number = f"2026-{uuid.uuid4().hex[:6]}"
                case = _sample_case(purchase_id, recall_number)
                case_store.put_case(case)
                ids.append(case["case_id"])
            dispatched_case = _sample_case(f"purchase-{uuid.uuid4().hex[:8]}", f"2026-{uuid.uuid4().hex[:6]}")
            dispatched_case["status"] = "dispatched"
            case_store.put_case(dispatched_case)
            ids.append(dispatched_case["case_id"])

            all_cases = case_store.list_cases(HOUSEHOLD)
            found_ids = {c["case_id"] for c in all_cases}
            assert set(ids) <= found_ids

            dispatched_only = case_store.list_cases(HOUSEHOLD, status="dispatched")
            assert dispatched_case["case_id"] in {c["case_id"] for c in dispatched_only}
            assert all(c["status"] == "dispatched" for c in dispatched_only)
        finally:
            for cid in ids:
                _delete_case(ddb, cid)


class TestRecallStore:
    def test_put_and_get_recalls_round_trip_dates_and_tuples(self, recall_store, ddb):
        source = "TEST"
        recall_number = f"TEST-{uuid.uuid4().hex[:8]}"
        recall = {
            "source": source,
            "recall_id": "999999",
            "recall_number": recall_number,
            "recall_date": date(2026, 3, 1),
            "title": "Test Widget recalled",
            "description": "unit test fixture",
            "url": "https://example.com/recall",
            "hazards": ("Laceration",),
            "remedies": ("Refund",),
            "remedy_kinds": ("refund",),
            "contact_raw": "call 800-555-0100",
            "contact_email": None,
            "contact_phone": "800-555-0100",
            "units": "1,000",
            "constraints": {
                "sold_start": date(2025, 1, 1),
                "sold_end": date(2025, 12, 31),
                "price_low": 19.99,
                "price_high": 24.99,
                "retailers": ("Target", "Walmart"),
                "upcs": (),
                "models": (),
            },
        }
        try:
            written = recall_store.put_recalls([recall])
            assert written == 1

            fetched = recall_store.all_recalls(source=source)
            match = next(r for r in fetched if r["recall_number"] == recall_number)
            assert match["recall_date"] == "2026-03-01"
            assert match["constraints"]["sold_start"] == "2025-01-01"
            assert match["constraints"]["price_low"] == 19.99
            assert isinstance(match["constraints"]["price_low"], float)
            assert list(match["hazards"]) == ["Laceration"]
        finally:
            ddb.Table("pullback-recalls").delete_item(
                Key={"source": source, "recall_number": recall_number}
            )

    def test_all_recalls_without_source_scans_everything(self, recall_store, ddb):
        source = "TEST"
        recall_number = f"TEST-{uuid.uuid4().hex[:8]}"
        recall = {
            "source": source,
            "recall_id": "999998",
            "recall_number": recall_number,
            "recall_date": date(2026, 3, 2),
            "title": "Second test widget",
            "description": "unit test fixture",
            "url": "https://example.com/recall2",
            "hazards": (),
            "remedies": (),
            "remedy_kinds": (),
            "contact_raw": "",
            "contact_email": None,
            "contact_phone": None,
            "units": None,
            "constraints": {},
        }
        try:
            recall_store.put_recalls([recall])
            everything = recall_store.all_recalls()
            assert any(r["recall_number"] == recall_number for r in everything)
        finally:
            ddb.Table("pullback-recalls").delete_item(
                Key={"source": source, "recall_number": recall_number}
            )


class TestEvidencePack:
    def test_write_pack_uploads_three_files_and_decision_txt_is_readable(
        self, case_store, s3, ddb
    ):
        purchase_id = f"purchase-{uuid.uuid4().hex[:8]}"
        recall_number = f"2026-{uuid.uuid4().hex[:6]}"
        case = _sample_case(purchase_id, recall_number)
        cid = case["case_id"]
        try:
            stored = case_store.put_case(case)
            uri = write_pack(stored)
            assert uri == f"s3://pullback-evidence-079415246611/cases/{HOUSEHOLD}/{cid}/"

            listing = s3.list_objects_v2(
                Bucket="pullback-evidence-079415246611", Prefix=f"cases/{HOUSEHOLD}/{cid}/"
            )
            keys = {obj["Key"] for obj in listing["Contents"]}
            assert keys == {
                f"cases/{HOUSEHOLD}/{cid}/case.json",
                f"cases/{HOUSEHOLD}/{cid}/decision.txt",
                f"cases/{HOUSEHOLD}/{cid}/claim.txt",
            }

            decision = s3.get_object(
                Bucket="pullback-evidence-079415246611", Key=f"cases/{HOUSEHOLD}/{cid}/decision.txt"
            )["Body"].read().decode("utf-8")
            assert "PULLBACK DECISION RECORD" in decision
            assert "NEEDS_EVIDENCE" in decision
            assert "upc" in decision
            assert purchase_id in decision or "Acme Toaster 2000" in decision

            url = presigned_url(uri)
            assert url.startswith("https://")
            assert "decision.txt" in url
        finally:
            _delete_case(ddb, cid)
            _delete_evidence(s3, cid)
