"""Swagger documentation of POST /security-events."""

from services.decision_engine.docs.errors import ValidationErrorResponse, error

# A device change on the first account the seed creates (its id never
# changes).
REQUEST_EXAMPLE = {
    "id": "0b6f2c1e-4d3a-5b8c-9e7f-1a2b3c4d5e6f",
    "type": "DEVICE_CHANGE",
    "user_id": "5d2c9b0a-7e4f-5a1b-8c3d-6e9f0a1b2c3d",
    "account_id": "a8d456b7-ae6a-5481-9a4b-64deb0d295f7",
    "device_id": "f8692d53-a16a-595f-b796-dfde37f5f4b0",
    "event_date": "2026-10-01T08:00:00+00:00",
}

# Used as Body(openapi_examples=SECURITY_REQUEST_EXAMPLES) in main.py.
SECURITY_REQUEST_EXAMPLES = {
    "device_change": {
        "summary": "New device on an account",
        "value": REQUEST_EXAMPLE,
    },
    "password_change": {
        "summary": "Password changed on the same account",
        "value": {
            **REQUEST_EXAMPLE,
            "id": "7c8d9e0f-1a2b-5c3d-8e4f-5a6b7c8d9e0f",
            "type": "PASSWORD_CHANGE",
            "event_date": "2026-10-01T08:05:00+00:00",
        },
    },
}

DESCRIPTION = """
Stores a device or password change of an account. The wallet core sends
these events apart from the transactions.

The account takeover rule reads them: a device change, a password change
and a transaction above USD 200 from the same account within an hour put
the transaction on `HOLD`.

The account is not checked against the database, so the event can arrive
before or after its transactions. A resend of the same `id` is stored
once. Events are kept for 60 minutes (`HISTORY_SECURITY_MINUTES`).
""".strip()

# Passed as @app.post("/security-events", **RECORD_SECURITY_EVENT).
RECORD_SECURITY_EVENT = {
    "summary": "Record a security event",
    "description": DESCRIPTION,
    "tags": ["Security events"],
    "status_code": 202,
    "responses": {
        202: {
            "description": "Stored, or a resend of an id that was already stored.",
            "content": {"application/json": {"example": {"recorded": True}}},
        },
        400: {
            "description": "Invalid body: missing fields, an unknown type, an id "
            "that is not a UUID or a date without time zone.",
            "model": ValidationErrorResponse,
        },
        503: error(
            "Valkey (security event store) is not available.",
            {
                "valkey_down": (
                    "Valkey down",
                    "The security event store is not available.",
                )
            },
        ),
    },
}
