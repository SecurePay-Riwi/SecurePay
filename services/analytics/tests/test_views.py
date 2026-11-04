"""Each view and its control query over the fixture day (contract C3):
both give the numbers of expected_views.json. One case per view: a view
that is not in sql/ is skipped. Spark tests: they skip without Java."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from services.analytics import views

# Meeting point: one line per view.
VIEWS = ("q1", "q2", "q3", "q4", "q5", "q6")


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _sorted(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: [str(v) for v in r.values()])


def _rows(df) -> list[dict]:
    return _sorted(
        [{k: _plain(v) for k, v in r.asDict().items()} for r in df.collect()]
    )


@pytest.fixture(scope="module")
def tables(spark, lake):
    views.register_tables(spark, lake)


@pytest.mark.parametrize("view", VIEWS)
def test_the_view_gives_the_answer_key(spark, tables, expected, view):
    if view not in views.view_files():
        pytest.skip(f"{view} is not in services/analytics/sql/ yet")

    assert _rows(views.run_view(spark, view)) == _sorted(expected[view])


@pytest.mark.parametrize("view", VIEWS)
def test_the_control_query_gives_the_same_numbers(spark, tables, expected, view):
    if view not in views.view_files():
        pytest.skip(f"{view} is not in services/analytics/sql/ yet")

    assert _rows(views.run_control(spark, view)) == _sorted(expected[view])


def test_every_view_has_its_control_query():
    for view in views.view_files():
        assert (views.CONTROL_DIR / f"{view}.sql").is_file(), view


def test_views_are_athena_views_without_order_less_limits():
    for view, path in views.view_files().items():
        name, select = views.view_sql(view)
        assert path.name == f"{name}.sql"
        assert " LIMIT " not in f" {select.upper()} " or "ORDER BY" in select.upper()


def test_write_views_leaves_parquet_for_power_bi(spark, lake, expected):
    written = views.write_views(spark, lake)

    assert written["q1"] == len(expected["q1"])
    assert list((Path(lake) / "views" / "q1").glob("*.parquet"))
