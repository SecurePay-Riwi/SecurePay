"""Case evidence (RN-12): kept 10 years in a bucket with Object Lock.

The cases API calls archive() after resolving a case, and the alerts task
calls archive_pending() for resolved cases whose evidence_key is still
null (the API's call failed or never ran).

One JSON object per case, written once:

- ``ObjectLockMode=COMPLIANCE`` with its own retain-until date (now +
  EVIDENCE_RETENTION_DAYS). Nobody can delete the version or shorten
  the date before then, not even the root account. The dev bucket in
  AWS has no default retention, so this date is the one that counts.
- ``StorageClass=GLACIER_IR``: written there directly. A lifecycle rule
  would never move it, because S3 does not transition objects under
  128 KB without a size filter (team decision of 2026-10-31).
- ``ChecksumSHA256``: S3 rejects the upload if the bytes change on the
  way, keeps the checksum with the object and checks it again on read.
- ``IfNoneMatch="*"``: if the object is already there (an earlier call
  wrote it but its commit failed), S3 answers 412 instead of adding a
  second version, and that counts as archived.

Not part of the published securepay-shared package.
"""

import base64
import hashlib
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from botocore.exceptions import ClientError
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from shared.aws import cliente
from shared.cases import SYSTEM_ACTOR, Case, CaseEvent, CaseEventType, CaseStatus

log = logging.getLogger(__name__)

# A bucket name: LocalStack's (infra/localstack/init/01_messaging.py) or
# the Terraform one, securepay-<env>-evidence-<account>.
BUCKET = os.getenv("EVIDENCE_BUCKET", "pagoseguro-evidence")
# RN-12: 10 years. A decimal, so dev and the tests can lock for minutes
# (0.0035 days, about 5 minutes): COMPLIANCE can never be shortened.
RETENTION = timedelta(days=float(os.getenv("EVIDENCE_RETENTION_DAYS", "3650")))

LOCK_MODE = "COMPLIANCE"
STORAGE_CLASS = "GLACIER_IR"
SCHEMA_VERSION = 1
# How many cases one run of the alerts task retries at most.
PENDING_BATCH = 50

# The case columns that go to the decision block instead of the case block.
DECISION_FIELDS = (
    "decision", "decision_reason", "rules_triggered", "rules_version",
    "rule_versions", "risk_score",
)


def _client():
    return cliente("s3", read_timeout=10)


def evidence_key(case: Case) -> str:
    """cases/<yyyy>/<mm>/<case_id>.json, by the month the case was closed.

    Always the same key for the same case, so a retry finds the object
    the first try wrote.
    """
    closed = case.resolved_at or case.created_at
    return f"cases/{closed:%Y}/{closed:%m}/{case.id}.json"


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def build_document(case: Case, events: list[CaseEvent], archived_at: datetime) -> dict:
    """The case, its events in order, and the transaction and decision as
    they came from the engine."""
    columns = {attr.key: getattr(case, attr.key) for attr in inspect(Case).column_attrs}
    transaction = columns.pop("transaction")
    decision = {field: columns.pop(field) for field in DECISION_FIELDS}
    columns.pop("evidence_key")  # set only after the upload
    return {
        "schema_version": SCHEMA_VERSION,
        "archived_at": archived_at,
        "case": columns,
        "transaction": transaction,
        "decision": decision,
        "events": [
            {"type": e.type, "actor": e.actor, "at": e.at, "data": e.data} for e in events
        ],
    }


def encode(document: dict) -> bytes:
    return json.dumps(
        document, default=_json_value, ensure_ascii=False, indent=2, sort_keys=True,
    ).encode("utf-8")


def sha256_base64(body: bytes) -> str:
    """The checksum in the form S3 expects (base64, not hex)."""
    return base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")


def _upload(s3, key: str, body: bytes, retain_until: datetime) -> datetime:
    """Write the object once and return its retain-until date. If it is
    already there, keep it and return the date it already has."""
    try:
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=body,
            ContentType="application/json",
            StorageClass=STORAGE_CLASS,
            ObjectLockMode=LOCK_MODE,
            ObjectLockRetainUntilDate=retain_until,
            # Object Lock uploads need the algorithm header; the value lets
            # S3 reject bytes that changed on the way.
            ChecksumAlgorithm="SHA256",
            ChecksumSHA256=sha256_base64(body),
            IfNoneMatch="*",
        )
        return retain_until
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "PreconditionFailed":
            raise
    log.info("Evidence %s was already in S3; keeping it", key)
    return s3.head_object(Bucket=BUCKET, Key=key)["ObjectLockRetainUntilDate"]


def archive(session: Session, case: Case) -> str | None:
    """Write the case evidence to the Object Lock bucket and return its key.

    Idempotent: if case.evidence_key is set, return it without writing.
    Writes the EVIDENCE_ARCHIVED event and sets case.evidence_key (own
    commit). Never raises: on error it logs and returns None (the alerts
    task retries).
    """
    if case.evidence_key:
        return case.evidence_key
    try:
        # Lock the row and read it again: the cases API and the alerts
        # task may archive the same case at the same time.
        session.refresh(case, with_for_update=True)
        if case.evidence_key:
            session.rollback()
            return case.evidence_key

        now = datetime.now(UTC)
        events = session.scalars(
            select(CaseEvent)
            .where(CaseEvent.case_id == case.id)
            .order_by(CaseEvent.at, CaseEvent.id)
        ).all()
        key = evidence_key(case)
        body = encode(build_document(case, list(events), now))
        retain_until = _upload(_client(), key, body, now + RETENTION)

        case.evidence_key = key
        session.add(CaseEvent(
            case_id=case.id,
            type=CaseEventType.EVIDENCE_ARCHIVED.value,
            actor=SYSTEM_ACTOR,
            at=now,
            data={"bucket": BUCKET, "key": key, "retain_until": retain_until.isoformat()},
        ))
        session.commit()
        log.info("Case %s: evidence archived in %s/%s until %s", case.id, BUCKET, key,
                 retain_until.isoformat())
        return key
    except Exception:
        log.exception("Case %s: evidence not archived; the alerts task retries", case.id)
        session.rollback()
        return None


def archive_pending(session: Session) -> int:
    """Archive the RESOLVED cases whose evidence_key is still null, oldest
    first, at most PENDING_BATCH per run. Returns how many were archived."""
    cases = session.scalars(
        select(Case)
        .where(Case.status == CaseStatus.RESOLVED.value, Case.evidence_key.is_(None))
        .order_by(Case.resolved_at)
        .limit(PENDING_BATCH)
    ).all()
    session.rollback()  # archive() locks each row in its own transaction
    return sum(1 for case in cases if archive(session, case))


def read(key: str, version_id: str | None = None) -> dict:
    """The archived evidence, for an audit (criterion 3). boto3 checks the
    SHA-256 S3 stored with the object and fails if the bytes differ."""
    extra = {"VersionId": version_id} if version_id else {}
    response = _client().get_object(Bucket=BUCKET, Key=key, ChecksumMode="ENABLED", **extra)
    return json.loads(response["Body"].read())
