"""Shared fixtures of the analytics tests: one small day, 2026-10-05.

fixtures/ (described in its README.md) is a raw layer as the lake has it
(raw/decisiones, raw/labels, raw/cases, raw/reconciliation), the
reference data and security events for the replay, and the answer key
expected_views.json. make_fixtures.py built them with the engine's rules.

The Spark tests need Java (17 or later) and skip without it.
"""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2026, 10, 5)


@pytest.fixture(scope="session")
def expected() -> dict:
    return json.loads((FIXTURES / "expected_views.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def spark():
    if shutil.which("java") is None:
        pytest.skip(
            "Spark needs Java 17 or later: install it to run the analytics tests"
        )
    from services.analytics import spark as sp

    return sp.session()


@pytest.fixture(scope="session")
def lake(spark, tmp_path_factory) -> str:
    """The ETL of the fixture day, run once: the output root (curated/,
    analytics/) in a temporary folder."""
    from services.analytics import etl

    output = str(tmp_path_factory.mktemp("analytics"))
    etl.run_day(spark, DAY, str(FIXTURES), output)
    return output
