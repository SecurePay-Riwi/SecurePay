"""The JSON line of a decision (HU-59): what CloudWatch counts (default
decisions, alarm 2) and what Logs Insights finds (slow decisions)."""

import json
import logging

import pytest

from services.decision_engine import decision_service as ds


def _result(**changes):
    result = {
        "transaction_id": "11111111-1111-1111-1111-111111111111",
        "decision": "APPROVE",
        "rules_triggered": [],
        "risk_score": 0,
        "by_default": False,
        "rules_version": "3",
    }
    result.update(changes)
    return result


def test_a_fast_approve_is_not_logged():
    assert ds.decision_line(_result(), elapsed_ms=12) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"decision": "HOLD", "rules_triggered": ["velocity"], "risk_score": 40},
        {"decision": "REJECT", "rules_triggered": ["restricted_list"]},
        {"by_default": True, "rules_triggered": ["default_timeout"]},
    ],
)
def test_holds_rejects_and_default_decisions_are_logged(changes):
    line = ds.decision_line(_result(**changes), elapsed_ms=12.34)

    assert line == {
        "event": "decision",
        "transaction_id": "11111111-1111-1111-1111-111111111111",
        "decision": changes.get("decision", "APPROVE"),
        "rules_triggered": changes["rules_triggered"],
        "risk_score": changes.get("risk_score", 0),
        "by_default": changes.get("by_default", False),
        "rules_version": "3",
        "elapsed_ms": 12.3,
    }


def test_a_slow_approve_is_logged(monkeypatch):
    monkeypatch.setattr(ds, "SLOW_DECISION_MS", 150)

    assert ds.decision_line(_result(), elapsed_ms=149.9) is None
    assert ds.decision_line(_result(), elapsed_ms=150)["elapsed_ms"] == 150


class Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def test_the_line_is_bare_json_on_its_own_logger():
    lines = Lines()
    logger = logging.getLogger("securepay.decisions")
    logger.addHandler(lines)
    logger.setLevel(logging.INFO)
    try:
        ds.log_decision(_result(decision="HOLD"), elapsed_ms=8)
        ds.log_decision(_result(), elapsed_ms=8)
    finally:
        logger.removeHandler(lines)

    assert len(lines.lines) == 1
    assert json.loads(lines.lines[0])["decision"] == "HOLD"


def test_the_engine_does_not_repeat_the_line_with_a_prefix():
    from services.decision_engine import main  # noqa: F401 (configures logging)

    logger = logging.getLogger("securepay.decisions")
    assert logger.propagate is False
    assert any(h.formatter._fmt == "%(message)s" for h in logger.handlers)
