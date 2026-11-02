"""GET /cases and GET /cases/{case_id} (HU-26) against a schema of its own.

RN-09: the inbox puts the riskiest cases first and, with the same risk,
the closest to the 4-hour limit.
"""

from datetime import timedelta
from uuid import uuid4

from services.cases_api.schemas import CaseDetail, CasePage
from shared.cases import CaseStatus


def _ids(response):
    return [item["id"] for item in response.json()["items"]]


def test_without_filters_the_inbox_lists_the_pending_cases(client, add_case):
    open_ = add_case(status=CaseStatus.OPEN)
    escalated = add_case(status=CaseStatus.ESCALATED)
    add_case(status=CaseStatus.RESOLVED)

    response = client.get("/cases")

    assert response.status_code == 200
    page = CasePage.model_validate(response.json())
    assert {str(c.id) for c in page.items} == {str(open_), str(escalated)}
    assert page.total == 2


def test_an_empty_inbox_is_an_empty_list(client):
    response = client.get("/cases")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_highest_risk_first_then_closest_to_the_limit(client, add_case):
    low_soon = add_case(risk_score=20, due_in=timedelta(minutes=10))
    high_late = add_case(risk_score=90, due_in=timedelta(hours=3))
    high_soon = add_case(risk_score=90, due_in=timedelta(minutes=30))
    mid_overdue = add_case(risk_score=50, due_in=timedelta(minutes=-15),
                           status=CaseStatus.ESCALATED)
    mid_late = add_case(risk_score=50, due_in=timedelta(hours=2))

    response = client.get("/cases")

    assert _ids(response) == [str(c) for c in
                              (high_soon, high_late, mid_overdue, mid_late, low_soon)]


def test_minutes_left_is_negative_when_overdue_and_null_when_resolved(client, add_case):
    # 30 s of margin so the request a moment later rounds to the same minute.
    on_time = add_case(due_in=timedelta(minutes=90, seconds=30))
    overdue = add_case(due_in=timedelta(minutes=-30, seconds=30), status=CaseStatus.ESCALATED)
    resolved = add_case(status=CaseStatus.RESOLVED)

    pending = {item["id"]: item["minutes_left"] for item in client.get("/cases").json()["items"]}
    done = client.get("/cases", params={"status": "RESOLVED"}).json()["items"]

    assert pending[str(on_time)] == 90
    assert pending[str(overdue)] == -30
    assert [(d["id"], d["minutes_left"]) for d in done] == [(str(resolved), None)]


def test_filter_by_status(client, add_case):
    add_case(status=CaseStatus.OPEN)
    escalated = add_case(status=CaseStatus.ESCALATED)
    resolved = add_case(status=CaseStatus.RESOLVED)

    assert _ids(client.get("/cases", params={"status": "ESCALATED"})) == [str(escalated)]
    assert _ids(client.get("/cases", params={"status": "RESOLVED"})) == [str(resolved)]


def test_filter_by_assignee(client, add_case):
    ana = add_case(assignee="ana")
    add_case(assignee="luis")
    add_case()
    add_case(assignee="ana", status=CaseStatus.RESOLVED)

    response = client.get("/cases", params={"assignee": "ana"})

    assert _ids(response) == [str(ana)]
    assert response.json()["total"] == 1


def test_filters_combine(client, add_case):
    add_case(assignee="ana")
    resolved = add_case(assignee="ana", status=CaseStatus.RESOLVED)
    add_case(assignee="luis", status=CaseStatus.RESOLVED)

    response = client.get("/cases", params={"status": "RESOLVED", "assignee": "ana"})

    assert _ids(response) == [str(resolved)]


def test_pagination(client, add_case):
    ids = [add_case(risk_score=score) for score in (90, 80, 70, 60, 50)]

    first = client.get("/cases", params={"page": 1, "size": 2}).json()
    third = client.get("/cases", params={"page": 3, "size": 2}).json()
    beyond = client.get("/cases", params={"page": 4, "size": 2}).json()

    assert [i["id"] for i in first["items"]] == [str(ids[0]), str(ids[1])]
    assert first["total"] == 5
    assert (first["page"], first["size"]) == (1, 2)
    assert [i["id"] for i in third["items"]] == [str(ids[4])]
    assert beyond["items"] == [] and beyond["total"] == 5


def test_invalid_filters_are_400(client):
    for params in ({"status": "CLOSED"}, {"size": 101}, {"size": 0}, {"page": 0},
                   {"assignee": ""}, {"assignee": "x" * 101}):
        response = client.get("/cases", params=params)
        assert response.status_code == 400, params
        assert response.json()["detail"] == "The request contains invalid data."


def test_amounts_are_decimal_strings(client, add_case):
    add_case(amount="950000.00", currency="COP", amount_usd="230.05")
    add_case(amount_usd=None, risk_score=10)

    items = client.get("/cases").json()["items"]

    assert (items[0]["amount"], items[0]["currency"], items[0]["amount_usd"]) == (
        "950000.00", "COP", "230.05")
    assert items[1]["amount_usd"] is None


def test_a_case_with_its_events(client, add_case):
    case_id = add_case(risk_score=70, rules_triggered=("mule", "velocity"))

    response = client.get(f"/cases/{case_id}")

    assert response.status_code == 200
    case = CaseDetail.model_validate(response.json())
    assert case.id == case_id
    assert case.risk_score == 70
    assert case.rules_triggered == ["mule", "velocity"]
    assert case.rule_versions == {"mule": 1, "velocity": 1}
    assert case.transaction["type"] == "RETIRO"
    assert case.outcome is None and case.final_decision is None
    assert [(e.type, e.actor) for e in case.events] == [("CREATED", "system")]


def test_an_unknown_case_is_404(client):
    response = client.get(f"/cases/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Case not found."}


def test_a_case_id_that_is_not_a_uuid_is_400(client):
    response = client.get("/cases/not-a-uuid")

    assert response.status_code == 400
    assert response.json()["detail"] == "The request contains invalid data."
