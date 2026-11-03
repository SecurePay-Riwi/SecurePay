"""Read and write the reconciliation's files in a local folder or in S3.

A path is a local folder ("generated/reconciliation/curated/...") or an
S3 URL ("s3://bucket/prefix/..."); the three steps use these functions so
the same code runs locally (tests, Compose) and in AWS.
"""

import fnmatch
import json
from pathlib import Path

from shared.aws import cliente

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = cliente("s3", read_timeout=30)
    return _s3


def _split(url: str) -> tuple[str, str]:
    bucket, _, key = url.removeprefix("s3://").partition("/")
    return bucket, key


def is_s3(path: str) -> bool:
    return str(path).startswith("s3://")


def join(path: str, *parts: str) -> str:
    return "/".join([str(path).rstrip("/"), *parts])


def list_files(folder: str, pattern: str = "*") -> list[str]:
    """The files under `folder` (at any depth) whose name matches
    `pattern`, sorted. A folder that does not exist is empty."""
    if is_s3(folder):
        bucket, prefix = _split(folder.rstrip("/") + "/")
        found = []
        pages = (
            _client()
            .get_paginator("list_objects_v2")
            .paginate(Bucket=bucket, Prefix=prefix)
        )
        for page in pages:
            for item in page.get("Contents", []):
                if fnmatch.fnmatch(item["Key"].rsplit("/", 1)[-1], pattern):
                    found.append(f"s3://{bucket}/{item['Key']}")
        return sorted(found)
    root = Path(folder)
    if not root.is_dir():
        return []
    return sorted(str(p) for p in root.rglob(pattern) if p.is_file())


def read_text(path: str) -> str:
    if is_s3(path):
        bucket, key = _split(path)
        return (
            _client().get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        )
    return Path(path).read_text(encoding="utf-8")


def write_text(path: str, body: str) -> None:
    """Write (or replace) one file; local folders are created."""
    if is_s3(path):
        bucket, key = _split(path)
        _client().put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def read_jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in read_text(path).splitlines() if line.strip()]


def write_jsonl(path: str, rows: list[dict]) -> None:
    write_text(
        path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    )
