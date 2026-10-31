"""Object Lock really protects the evidence (HU-32, criterion 2), against
LocalStack's S3, which enforces COMPLIANCE like AWS.

Writes straight to the evidence bucket that infra/localstack/init/
01_messaging.py creates, with a 2-minute lock, so no case table is
needed. Skipped if LocalStack is not running (docker compose up -d).
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from shared import evidence

pytestmark = pytest.mark.integracion

LOCK = timedelta(minutes=2)


@pytest.fixture(scope="module")
def s3():
    client = evidence._client()
    try:
        client.head_bucket(Bucket=evidence.BUCKET)
    except Exception:
        pytest.skip("LocalStack is not available (docker compose up -d)")
    return client


@pytest.fixture
def archived(s3):
    """One evidence object, uploaded the way archive() does it."""
    key = f"tests/{uuid4()}.json"
    body = evidence.encode({"case": {"id": key}, "events": []})
    until = (datetime.now(UTC) + LOCK).replace(microsecond=0)
    version = s3.put_object(
        Bucket=evidence.BUCKET, Key=key, Body=body, ContentType="application/json",
        StorageClass=evidence.STORAGE_CLASS, ObjectLockMode=evidence.LOCK_MODE,
        ObjectLockRetainUntilDate=until, ChecksumAlgorithm="SHA256",
        ChecksumSHA256=evidence.sha256_base64(body),
        IfNoneMatch="*",
    )["VersionId"]
    return key, version, body, until


def _error(call) -> str:
    with pytest.raises(ClientError) as exc:
        call()
    return exc.value.response["Error"]["Code"]


def test_the_object_is_locked_in_glacier_ir(s3, archived):
    key, version, body, until = archived

    head = s3.head_object(Bucket=evidence.BUCKET, Key=key, ChecksumMode="ENABLED")

    assert head["ObjectLockMode"] == "COMPLIANCE"
    assert head["ObjectLockRetainUntilDate"] == until
    assert head["StorageClass"] == "GLACIER_IR"
    assert head["ChecksumSHA256"] == evidence.sha256_base64(body)


def test_deleting_the_version_is_denied(s3, archived):
    key, version, _, _ = archived

    assert _error(lambda: s3.delete_object(
        Bucket=evidence.BUCKET, Key=key, VersionId=version,
    )) == "AccessDenied"


def test_shortening_the_lock_is_denied(s3, archived):
    key, version, _, until = archived

    assert _error(lambda: s3.put_object_retention(
        Bucket=evidence.BUCKET, Key=key, VersionId=version,
        Retention={"Mode": "COMPLIANCE", "RetainUntilDate": until - timedelta(minutes=1)},
    )) == "AccessDenied"


def test_switching_to_governance_is_denied_even_with_bypass(s3, archived):
    key, version, _, until = archived

    assert _error(lambda: s3.put_object_retention(
        Bucket=evidence.BUCKET, Key=key, VersionId=version,
        Retention={"Mode": "GOVERNANCE", "RetainUntilDate": until},
        BypassGovernanceRetention=True,
    )) == "AccessDenied"


def test_overwriting_is_refused_and_leaves_one_version(s3, archived):
    key, _, _, _ = archived

    assert _error(lambda: s3.put_object(
        Bucket=evidence.BUCKET, Key=key, Body=b"{}", IfNoneMatch="*",
    )) == "PreconditionFailed"

    versions = s3.list_object_versions(Bucket=evidence.BUCKET, Prefix=key)["Versions"]
    assert len(versions) == 1


def test_a_plain_delete_only_hides_it_and_the_original_is_still_there(s3, archived):
    key, version, body, _ = archived

    # Without VersionId S3 only adds a delete marker on top: allowed, and
    # nothing is lost.
    s3.delete_object(Bucket=evidence.BUCKET, Key=key)

    original = evidence.read(key, version_id=version)
    assert original == json.loads(body)
