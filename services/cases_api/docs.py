"""Swagger documentation of the cases API: summaries, descriptions and an
example of every status code. tests/test_openapi.py checks them.

Join point: each owner adds the constants of their endpoints here and
passes them as @router.<method>(..., **docs.NAME).
"""

from pydantic import BaseModel, Field

APP = {
    "title": "SecurePay cases API",
    "version": "1.0.0",
    "description": (
        "The cases an analyst works on: the inbox, assigning, resolving, "
        "the account history and the compliance reports. Cases are opened "
        "by the consumers from the engine's decisions (only the ones with "
        "`opens_case`) and escalated by the alerts task after 4 hours "
        "(RN-09).\n\n"
        "Send `X-User` with your name on every request that changes a case: "
        "it is the actor of the case event."
    ),
}


class Error(BaseModel):
    detail: str = Field(description="What went wrong.")


def _ok(description: str, example) -> dict:
    return {"description": description, "content": {"application/json": {"example": example}}}


def _error(description: str, detail: str) -> dict:
    return {"description": description, "model": Error,
            "content": {"application/json": {"example": {"detail": detail}}}}


DB_DOWN = _error("PostgreSQL is not available.", "The cases database is not available.")

HEALTH = {
    "summary": "Check that the API and its database are up",
    "tags": ["Health"],
    "responses": {200: _ok("Up.", {"status": "ok"}), 503: DB_DOWN},
}


# --- Compliance (HU-34) ------------------------------------------------------

_REPORT = {
    "id": "6f1c2b9e-3c1f-4a52-9a77-1e0f4f2d8c10",
    "case_id": "0b5e7c43-9d8a-4f6e-8f43-5a7d1c2e9b01",
    "transaction_id": "a3c1e5f7-2b4d-4c6e-8a0b-1d3f5a7c9e21",
    "account_id": "5d7f9b1c-3e5a-4c7e-9b1d-3f5a7c9e1b42",
    "document": "1000000070",
    "list_type": "PEP",
    "matched_at": "2026-10-31T14:02:11.418000Z",
    "notified_at": "2026-10-31T14:05:00.031000Z",
}

RESTRICTED_LIST_REPORTS = {
    "summary": "List the restricted list reports (RN-06)",
    "description": (
        "One report per listed document of a transaction: when the engine "
        "fires `restricted_list`, the cases consumer opens the case and "
        "writes a report for every owner of the source or destination "
        "account who is on the list. The alerts task e-mails the new ones "
        "to compliance every 5 minutes and sets `notified_at`.\n\n"
        "Newest first. `from` (inclusive) and `to` (exclusive) filter by "
        "`matched_at`; a date or time without a time zone is UTC. A period "
        "without reports is an empty list. Paginated with `page` and "
        "`size` (at most 100)."
    ),
    "responses": {
        200: _ok(
            "The reports of the period, newest first.",
            {"items": [_REPORT], "total": 1, "page": 1, "size": 50},
        ),
        400: _error("A date is not valid, `from` is after `to`, or the page is out of range.",
                    "The request contains invalid data."),
        503: DB_DOWN,
    },
}
