"""The scaled day of the match benchmark (E-13): every copy is the fixture
day with new ids, so the answer is the fixture's times the copies."""

import json

from services.reconciliation import benchmark, match


def _lines(path):
    return [json.loads(line) for line in path.open()]


def _match(records, decisions):
    return match.match_day(
        benchmark.DAY,
        match.read_records(str(records)),
        match.read_decisions(str(decisions), benchmark.DAY),
    )


def test_each_copy_has_new_ids_in_both_sides(tmp_path):
    records, decisions = benchmark.scale(tmp_path, 3)

    fixture = _lines(
        benchmark.FIXTURES
        / "curated"
        / "extractos"
        / "fecha=2026-10-05"
        / "records.jsonl"
    )
    scaled = _lines(records)
    assert len(scaled) == 3 * len(fixture)
    assert (
        len({r["pagoseguro_reference"] for r in scaled})
        == len({r["pagoseguro_reference"] for r in fixture}) * 3
    )

    ids = {
        e["transaction"]["id"]
        for folder in decisions.iterdir()
        for e in _lines(folder / "part-0000.jsonl")
    }
    # A record of a copy points at the decision of the same copy.
    references = {r["pagoseguro_reference"] for r in scaled}
    fixture_ids = {
        e["transaction"]["id"]
        for folder in (benchmark.FIXTURES / "decisiones").iterdir()
        for e in _lines(folder / "part-0000.jsonl")
    }
    fixture_refs = {r["pagoseguro_reference"] for r in fixture}
    assert len(references & ids) == 3 * len(fixture_refs & fixture_ids)


def test_the_scaled_day_matches_like_the_fixture_times_the_copies(tmp_path):
    records, decisions = benchmark.scale(tmp_path, 2)
    fixture_records = (
        benchmark.FIXTURES
        / "curated"
        / "extractos"
        / "fecha=2026-10-05"
        / "records.jsonl"
    )
    one = _match(fixture_records, benchmark.FIXTURES / "decisiones")
    two = _match(records, decisions)
    assert len(two) == 2 * len(one)
    assert sorted(r.status for r in two) == sorted([r.status for r in one] * 2)


def test_the_tuned_variant_is_the_match_session():
    assert benchmark.VARIANTS["tuned"][1] is None
    assert match.SESSION_SETTINGS["spark.sql.session.timeZone"] == "UTC"
