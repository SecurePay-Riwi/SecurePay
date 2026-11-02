"""Shared fixtures of the reconciliation tests: one small day, 2026-10-05.

tests/fixtures/ (described in its README.md):
    extractos/       the four partners' files, laid out like generated/extractos/
    decisiones/      raw/decisiones of 2026-10-04 to 2026-10-06 (JSON Lines)
    curated/         what ingest and match must write for that day
    extracts_report.json  the answer key
"""

import json
from datetime import date
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2026, 10, 5)
STATEMENTS = str(FIXTURES / "extractos")
DECISIONS = str(FIXTURES / "decisiones")
RECORDS = str(FIXTURES / "curated" / "extractos" / f"fecha={DAY}" / "records.jsonl")
REJECTS = str(FIXTURES / "curated" / "extractos" / f"fecha={DAY}" / "rejects.jsonl")
MATCH = str(FIXTURES / "curated" / "conciliacion" / f"fecha={DAY}")


@pytest.fixture
def report() -> dict:
    return json.loads((FIXTURES / "extracts_report.json").read_text(encoding="utf-8"))
