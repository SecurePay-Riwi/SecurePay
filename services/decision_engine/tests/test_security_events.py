"""POST /security-events and the sec:{account} set it writes
(security_events.py). Needs Valkey; no database."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import valkey
from fastapi.testclient import TestClient

from services.decision_engine import security_events
from services.decision_engine.main import app
from services.decision_engine.security_events import (
    SECURITY_MINUTES,
    recent,
    security_key,
)
from shared.cache import get_cache

client = TestClient(app)

BASE = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


@pytest.fixture
def account():
    """A fresh account per test; skipped when Valkey is not running."""
    try:
        get_cache().ping()
    except valkey.exceptions.ConnectionError:
        pytest.skip("Valkey is not available at VALKEY_URL")

    account_id = str(uuid4())
    yield account_id

    get_cache().delete(security_key(account_id))


def event(account_id, type_="DEVICE_CHANGE", minutes=0, **changes):
    body = {
        "id": str(uuid4()),
        "type": type_,
        "user_id": str(uuid4()),
        "account_id": account_id,
        "device_id": str(uuid4()),
        "event_date": (BASE + timedelta(minutes=minutes)).isoformat(),
    }
    body.update(changes)
    return body


def test_event_is_recorded(account):
    body = event(account)

    response = client.post("/security-events", json=body)

    assert response.status_code == 202
    assert response.json() == {"recorded": True}
    [stored] = recent(account)
    assert stored.id == body["id"]
    assert stored.type == "DEVICE_CHANGE"
    assert stored.device_id == body["device_id"]
    assert stored.t == int(BASE.timestamp() * 1000)


def test_resend_of_the_same_event_is_stored_once(account):
    body = event(account)

    client.post("/security-events", json=body)
    response = client.post("/security-events", json=body)

    assert response.status_code == 202
    assert len(recent(account)) == 1


def test_events_come_back_in_chronological_order(account):
    # The password change arrives first but happened later.
    client.post("/security-events", json=event(account, "PASSWORD_CHANGE", minutes=10))
    client.post("/security-events", json=event(account, "DEVICE_CHANGE", minutes=2))

    assert [e.type for e in recent(account)] == ["DEVICE_CHANGE", "PASSWORD_CHANGE"]


def test_events_older_than_the_retention_are_trimmed(account):
    client.post("/security-events", json=event(account, minutes=0))
    client.post(
        "/security-events",
        json=event(account, "PASSWORD_CHANGE", minutes=SECURITY_MINUTES + 1),
    )

    assert [e.type for e in recent(account)] == ["PASSWORD_CHANGE"]


def test_events_of_other_accounts_are_not_mixed(account):
    other = str(uuid4())
    try:
        client.post("/security-events", json=event(other))
        assert recent(account) == []
    finally:
        get_cache().delete(security_key(other))


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "EMAIL_CHANGE"},
        {"id": "not-a-uuid"},
        {"event_date": "2026-10-01T08:00:00"},  # no time zone
        {"account_id": None},
    ],
)
def test_invalid_body_returns_400(changes):
    body = {**event(str(uuid4())), **changes}

    response = client.post("/security-events", json=body)

    assert response.status_code == 400
    assert response.json()["errors"]


def test_valkey_down_returns_503(monkeypatch):
    def down(event):
        raise valkey.exceptions.ConnectionError("down")

    monkeypatch.setattr(security_events, "record", down)

    response = client.post("/security-events", json=event(str(uuid4())))

    assert response.status_code == 503
    assert response.json() == {"detail": "The security event store is not available."}
