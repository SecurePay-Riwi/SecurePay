"""PUT /cases/{case_id}/assignee (HU-27) against a schema of its own.

Each case has one owner, and every change of owner is in its history
with the previous and the new one (ASSIGNED {"from", "to"}).
"""

from uuid import uuid4

from sqlalchemy import select

from services.cases_api.schemas import CaseDetail
from shared.cases import Case, CaseEvent, CaseStatus

SUPERVISOR = {"X-User": "supervisor.luis"}


def _assign(client, case_id, assignee, headers=SUPERVISOR):
    return client.put(f"/cases/{case_id}/assignee", json={"assignee": assignee}, headers=headers)


def _assigned(case: CaseDetail):
    return [(e.actor, e.data) for e in case.events if e.type == "ASSIGNED"]


def test_assigning_a_case_shows_its_owner(client, add_case):
    case_id = add_case()

    response = _assign(client, case_id, "ana")

    assert response.status_code == 200
    case = CaseDetail.model_validate(response.json())
    assert case.assignee == "ana"
    assert _assigned(case) == [("supervisor.luis", {"from": None, "to": "ana"})]
    # The inbox shows the owner too.
    inbox = client.get("/cases", params={"assignee": "ana"}).json()["items"]
    assert [i["id"] for i in inbox] == [str(case_id)]


def test_reassigning_records_the_previous_and_the_new_owner(client, add_case):
    case_id = add_case()
    _assign(client, case_id, "ana")

    response = _assign(client, case_id, "luis", headers={"X-User": "supervisor.marta"})

    assert response.status_code == 200
    case = CaseDetail.model_validate(response.json())
    assert case.assignee == "luis"
    assert _assigned(case) == [
        ("supervisor.luis", {"from": None, "to": "ana"}),
        ("supervisor.marta", {"from": "ana", "to": "luis"}),
    ]
    assert [e.type for e in case.events] == ["CREATED", "ASSIGNED", "ASSIGNED"]


def test_the_same_owner_again_writes_no_event(client, add_case):
    case_id = add_case(assignee="ana")

    response = _assign(client, case_id, "ana")

    assert response.status_code == 200
    case = CaseDetail.model_validate(response.json())
    assert case.assignee == "ana"
    assert _assigned(case) == []


def test_the_assignee_is_trimmed(client, add_case):
    case_id = add_case()

    response = _assign(client, case_id, "  ana  ")

    assert response.json()["assignee"] == "ana"


def test_an_escalated_case_can_be_assigned(client, add_case):
    case_id = add_case(status=CaseStatus.ESCALATED)

    response = _assign(client, case_id, "ana")

    assert response.status_code == 200
    assert response.json()["status"] == "ESCALATED"
    assert response.json()["assignee"] == "ana"


def test_a_resolved_case_is_409_and_does_not_change(client, add_case, sessions):
    case_id = add_case(status=CaseStatus.RESOLVED, assignee="ana")

    response = _assign(client, case_id, "luis")

    assert response.status_code == 409
    assert response.json() == {"detail": "The case is resolved; it can no longer change."}
    with sessions() as session:
        assert session.get(Case, case_id).assignee == "ana"
        types = session.scalars(select(CaseEvent.type).where(CaseEvent.case_id == case_id)).all()
        assert types == ["CREATED"]


def test_without_x_user_is_400(client, add_case, sessions):
    case_id = add_case()

    for headers in ({}, {"X-User": "   "}, {"X-User": "x" * 101}):
        response = _assign(client, case_id, "ana", headers=headers)
        assert response.status_code == 400, headers
        assert response.json() == {"detail": "X-User must have 1 to 100 characters."}

    with sessions() as session:
        assert session.get(Case, case_id).assignee is None


def test_an_invalid_assignee_is_400(client, add_case):
    case_id = add_case()

    for body in ({}, {"assignee": ""}, {"assignee": "   "}, {"assignee": "x" * 101}):
        response = client.put(f"/cases/{case_id}/assignee", json=body, headers=SUPERVISOR)
        assert response.status_code == 400, body
        assert response.json()["detail"] == "The request contains invalid data."


def test_an_unknown_case_is_404(client):
    response = _assign(client, uuid4(), "ana")

    assert response.status_code == 404
    assert response.json() == {"detail": "Case not found."}


def test_a_case_id_that_is_not_a_uuid_is_400(client):
    response = _assign(client, "not-a-uuid", "ana")

    assert response.status_code == 400
