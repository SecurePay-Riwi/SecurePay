"""Case evidence (HU-32, RN-12) against a schema of its own.

Needs PostgreSQL (DATABASE_URL); S3 is replaced by a fake client that
keeps the objects in memory. That Object Lock really denies deleting or
shortening is proven against LocalStack in test_evidence_localstack.py.
"""

import io
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import select

from shared import evidence
from shared.cases import Case, CaseEvent, CaseEventType, CaseStatus, create_schema
from shared.tests.isolated_db import isolated_sessions

CREATED = datetime(2026, 12, 7, 10, 0, tzinfo=UTC)
RESOLVED = datetime(2026, 12, 7, 11, 30, tzinfo=UTC)


class FakeS3:
    """put_object honours IfNoneMatch="*" like S3; the rest is a dict."""

    def __init__(self):
        self.objects = {}
        self.puts = []
        self.fail = False

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        if self.fail:
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "PutObject")
        if kwargs.get("IfNoneMatch") == "*" and kwargs["Key"] in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[kwargs["Key"]] = kwargs
        return {"VersionId": "v1"}

    def head_object(self, Bucket, Key):
        return {"ObjectLockRetainUntilDate": self.objects[Key]["ObjectLockRetainUntilDate"]}

    def get_object(self, Bucket, Key, ChecksumMode=None, **kwargs):
        return {"Body": io.BytesIO(self.objects[Key]["Body"])}


@pytest.fixture
def sessions():
    with isolated_sessions("evidence_test") as factory:
        with factory() as session:
            create_schema(session)
        yield factory


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(evidence, "_client", lambda: fake)
    return fake


def _resolved_case(factory, status=CaseStatus.RESOLVED, evidence_key=None):
    """A mule case with its CREATED and RESOLVED events."""
    with factory() as session:
        case = Case(
            transaction_id=uuid4(), account_id=uuid4(), decision="HOLD",
            decision_reason="Mule account pattern.", rules_triggered=["mule"],
            rules_version="3", rule_versions={"mule": 2}, risk_score=80,
            amount=Decimal("1250000.00"), currency="COP", amount_usd=Decimal("312.50"),
            transaction_date=CREATED, transaction={"transaction_id": "t-1", "amount": "1250000.00"},
            status=status.value, created_at=CREATED, due_at=CREATED + timedelta(hours=4),
            evidence_key=evidence_key,
        )
        if status == CaseStatus.RESOLVED:
            case.resolved_at, case.resolved_by = RESOLVED, "analyst-1"
            case.outcome, case.final_decision = "FRAUD", "REJECT"
            case.resolution_note = "Confirmed with the customer."
        session.add(case)
        session.flush()
        session.add(CaseEvent(case_id=case.id, type="CREATED", actor="system", at=CREATED, data={}))
        if status == CaseStatus.RESOLVED:
            session.add(CaseEvent(
                case_id=case.id, type="RESOLVED", actor="analyst-1", at=RESOLVED,
                data={"outcome": "FRAUD", "final_decision": "REJECT", "note": "Confirmed."},
            ))
        session.commit()
        return case.id


def _archive(factory, case_id):
    with factory() as session:
        return evidence.archive(session, session.get(Case, case_id))


def _events(factory, case_id):
    with factory() as session:
        return session.scalars(
            select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.id)
        ).all()


def test_archive_writes_one_locked_object_in_glacier_ir(sessions, s3):
    case_id = _resolved_case(sessions)
    before = datetime.now(UTC)

    key = _archive(sessions, case_id)

    assert key == f"cases/2026/12/{case_id}.json"
    [put] = s3.puts
    assert put["Bucket"] == evidence.BUCKET
    assert put["ObjectLockMode"] == "COMPLIANCE"
    assert put["StorageClass"] == "GLACIER_IR"
    assert put["IfNoneMatch"] == "*"
    assert put["ChecksumAlgorithm"] == "SHA256"
    assert put["ChecksumSHA256"] == evidence.sha256_base64(put["Body"])
    retain = put["ObjectLockRetainUntilDate"] - before
    assert evidence.RETENTION <= retain < evidence.RETENTION + timedelta(minutes=1)


def test_archive_sets_the_key_and_writes_the_event(sessions, s3):
    case_id = _resolved_case(sessions)

    key = _archive(sessions, case_id)

    with sessions() as session:
        assert session.get(Case, case_id).evidence_key == key
    event = _events(sessions, case_id)[-1]
    assert event.type == CaseEventType.EVIDENCE_ARCHIVED.value
    assert event.actor == "system"
    assert event.data["bucket"] == evidence.BUCKET
    assert event.data["key"] == key
    assert datetime.fromisoformat(event.data["retain_until"]) == (
        s3.puts[0]["ObjectLockRetainUntilDate"]
    )


def test_the_json_has_the_case_its_events_the_transaction_and_the_decision(sessions, s3):
    case_id = _resolved_case(sessions)

    key = _archive(sessions, case_id)
    document = json.loads(s3.objects[key]["Body"])

    assert document["schema_version"] == 1
    assert document["case"]["id"] == str(case_id)
    assert document["case"]["outcome"] == "FRAUD"
    assert document["case"]["amount"] == "1250000.00"
    assert document["transaction"] == {"transaction_id": "t-1", "amount": "1250000.00"}
    assert document["decision"]["decision"] == "HOLD"
    assert document["decision"]["rules_triggered"] == ["mule"]
    assert document["decision"]["rule_versions"] == {"mule": 2}
    # The events up to the resolution, in order (EVIDENCE_ARCHIVED comes after).
    assert [e["type"] for e in document["events"]] == ["CREATED", "RESOLVED"]


def test_reading_it_back_returns_the_original_content(sessions, s3):
    case_id = _resolved_case(sessions)

    key = _archive(sessions, case_id)

    assert evidence.read(key) == json.loads(s3.objects[key]["Body"])


def test_a_second_call_does_not_write(sessions, s3):
    case_id = _resolved_case(sessions)

    first = _archive(sessions, case_id)
    second = _archive(sessions, case_id)

    assert first == second
    assert len(s3.puts) == 1
    assert [e.type for e in _events(sessions, case_id)].count("EVIDENCE_ARCHIVED") == 1


def test_an_object_left_by_a_failed_commit_counts_as_archived(sessions, s3):
    case_id = _resolved_case(sessions)
    with sessions() as session:
        case = session.get(Case, case_id)
        key = evidence.evidence_key(case)
    earlier = datetime(2036, 12, 7, tzinfo=UTC)
    s3.objects[key] = {"Body": b"{}", "ObjectLockRetainUntilDate": earlier}

    assert _archive(sessions, case_id) == key

    assert s3.objects[key]["Body"] == b"{}"  # the first object stays
    assert _events(sessions, case_id)[-1].data["retain_until"] == earlier.isoformat()


def test_an_s3_error_returns_none_without_raising(sessions, s3):
    case_id = _resolved_case(sessions)
    s3.fail = True

    assert _archive(sessions, case_id) is None

    with sessions() as session:
        assert session.get(Case, case_id).evidence_key is None
    assert [e.type for e in _events(sessions, case_id)] == ["CREATED", "RESOLVED"]


def test_archive_pending_only_takes_resolved_cases_without_evidence(sessions, s3):
    pending = _resolved_case(sessions)
    _resolved_case(sessions, evidence_key="cases/2026/12/done.json")
    _resolved_case(sessions, status=CaseStatus.OPEN)

    with sessions() as session:
        assert evidence.archive_pending(session) == 1

    assert [put["Key"] for put in s3.puts] == [f"cases/2026/12/{pending}.json"]


def test_archive_pending_retries_after_a_failure(sessions, s3):
    case_id = _resolved_case(sessions)
    s3.fail = True
    with sessions() as session:
        assert evidence.archive_pending(session) == 0

    s3.fail = False
    with sessions() as session:
        assert evidence.archive_pending(session) == 1
    with sessions() as session:
        assert session.get(Case, case_id).evidence_key is not None
