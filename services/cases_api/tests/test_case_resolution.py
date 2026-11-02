"""POST /cases/{case_id}/resolution (HU-30) against a schema of its own.

D4: FRAUD -> final_decision REJECT, LEGITIMATE -> APPROVE; the core
reads it from the case. RN-12: the evidence is archived after the
commit (shared.evidence.archive is replaced here, so S3 is never used).
"""

from uuid import uuid4

import pytest
from sqlalchemy import select

from services.cases_api.schemas import CaseDetail
from shared import evidence
from shared.cases import Case, CaseEvent, CaseStatus

ANA = {"X-User": "ana"}
NOTE = "The customer confirmed the withdrawal by phone."


@pytest.fixture
def archived(monkeypatch, sessions):
    """Replace archive(): record each call and the case's state at that
    moment, as committed in the database."""
    calls = []

    def fake_archive(session, case):
        with sessions() as other:  # what another connection sees: committed data
            calls.append((case.id, other.get(Case, case.id).status))
        # Returns None, as archive() does when it fails.

    monkeypatch.setattr(evidence, "archive", fake_archive)
    return calls


def _resolve(client, case_id, outcome="LEGITIMATE", note=NOTE, headers=ANA):
    return client.post(f"/cases/{case_id}/resolution",
                       json={"outcome": outcome, "note": note}, headers=headers)


def test_fraud_rejects_the_held_transaction(client, add_case, archived):
    case_id = add_case()

    response = _resolve(client, case_id, outcome="FRAUD", note="Linked senders.")

    assert response.status_code == 200
    case = CaseDetail.model_validate(response.json())
    assert (case.status, case.outcome, case.final_decision) == ("RESOLVED", "FRAUD", "REJECT")
    assert case.resolution_note == "Linked senders."
    assert case.resolved_by == "ana"
    assert case.resolved_at is not None
    assert case.minutes_left is None


def test_legitimate_releases_the_held_transaction(client, add_case, archived):
    case_id = add_case()

    response = _resolve(client, case_id, outcome="LEGITIMATE")

    case = CaseDetail.model_validate(response.json())
    assert (case.status, case.outcome, case.final_decision) == ("RESOLVED", "LEGITIMATE", "APPROVE")


def test_the_resolution_is_stored_with_its_event(client, add_case, archived, sessions):
    case_id = add_case(assignee="luis")

    _resolve(client, case_id, outcome="FRAUD", note="  Linked senders.  ")

    with sessions() as session:
        case = session.get(Case, case_id)
        assert (case.status, case.outcome, case.final_decision) == ("RESOLVED", "FRAUD", "REJECT")
        assert case.resolution_note == "Linked senders."
        assert case.assignee == "luis"
        events = session.scalars(
            select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.id)
        ).all()
    assert [(e.type, e.actor) for e in events] == [("CREATED", "system"), ("RESOLVED", "ana")]
    assert events[-1].data == {"outcome": "FRAUD", "final_decision": "REJECT",
                               "note": "Linked senders."}


def test_a_resolved_case_leaves_the_inbox(client, add_case, archived):
    case_id = add_case()

    _resolve(client, case_id)

    assert client.get("/cases").json()["items"] == []
    resolved = client.get("/cases", params={"status": "RESOLVED"}).json()["items"]
    assert [i["id"] for i in resolved] == [str(case_id)]


def test_the_evidence_is_archived_once_after_the_commit(client, add_case, archived):
    case_id = add_case()

    _resolve(client, case_id)

    # Called once, and the resolution was already committed when it ran.
    assert archived == [(case_id, "RESOLVED")]


def test_the_response_carries_the_evidence_key(client, add_case, monkeypatch):
    case_id = add_case()
    key = f"cases/2026/11/{case_id}.json"

    def fake_archive(session, case):
        case.evidence_key = key
        session.commit()
        return key

    monkeypatch.setattr(evidence, "archive", fake_archive)

    response = _resolve(client, case_id)

    assert response.json()["evidence_key"] == key


def test_if_archiving_fails_the_case_stays_resolved(client, add_case, archived):
    case_id = add_case()

    response = _resolve(client, case_id)

    assert response.status_code == 200
    assert response.json()["status"] == "RESOLVED"
    assert response.json()["evidence_key"] is None  # the alerts task retries it


def test_an_escalated_case_without_owner_can_be_resolved(client, add_case, archived):
    case_id = add_case(status=CaseStatus.ESCALATED)

    response = _resolve(client, case_id, outcome="FRAUD")

    assert response.status_code == 200
    assert response.json()["final_decision"] == "REJECT"
    assert response.json()["assignee"] is None


def test_resolving_twice_is_409(client, add_case, archived, sessions):
    case_id = add_case()
    _resolve(client, case_id, outcome="FRAUD")

    response = _resolve(client, case_id, outcome="LEGITIMATE")

    assert response.status_code == 409
    assert response.json() == {"detail": "The case is resolved; it can no longer change."}
    with sessions() as session:
        assert session.get(Case, case_id).final_decision == "REJECT"
    assert len(archived) == 1


def test_without_x_user_is_400(client, add_case, archived, sessions):
    case_id = add_case()

    for headers in ({}, {"X-User": "  "}, {"X-User": "x" * 101}):
        response = _resolve(client, case_id, headers=headers)
        assert response.status_code == 400, headers
        assert response.json() == {"detail": "X-User must have 1 to 100 characters."}

    with sessions() as session:
        assert session.get(Case, case_id).status == "OPEN"
    assert archived == []


def test_an_invalid_body_is_400(client, add_case, archived):
    case_id = add_case()

    for body in ({"note": NOTE}, {"outcome": "MAYBE", "note": NOTE}, {"outcome": "FRAUD"},
                 {"outcome": "FRAUD", "note": ""}, {"outcome": "FRAUD", "note": "   "},
                 {"outcome": "FRAUD", "note": "x" * 2001}):
        response = client.post(f"/cases/{case_id}/resolution", json=body, headers=ANA)
        assert response.status_code == 400, body
        assert response.json()["detail"] == "The request contains invalid data."


def test_an_unknown_case_is_404(client, archived):
    response = _resolve(client, uuid4())

    assert response.status_code == 404
    assert response.json() == {"detail": "Case not found."}


def test_a_case_id_that_is_not_a_uuid_is_400(client, archived):
    assert _resolve(client, "not-a-uuid").status_code == 400
