
from datetime import datetime, timedelta, timezone

from api.services.decision_service import (
    IDEMPOTENCY_WINDOW_SECONDS,
    _is_within_idempotency_window,
)
from seeds.models import Transaccion


def test_decision_is_reusable_at_exact_window_boundary():
    now = datetime.now(timezone.utc)

    transaction = Transaccion(
        decision="APPROVE",
        processed_at=now - timedelta(
            seconds=IDEMPOTENCY_WINDOW_SECONDS
        ),
    )

    assert _is_within_idempotency_window(transaction, now) is True


def test_decision_is_not_reusable_after_window_boundary():
    now = datetime.now(timezone.utc)

    transaction = Transaccion(
        decision="APPROVE",
        processed_at=now - timedelta(
            seconds=IDEMPOTENCY_WINDOW_SECONDS,
            microseconds=1,
        ),
    )

    assert _is_within_idempotency_window(transaction, now) is False


def test_decision_without_processing_date_is_not_reusable():
    transaction = Transaccion(
        decision="APPROVE",
        processed_at=None,
    )

    assert (
        _is_within_idempotency_window(
            transaction,
            datetime.now(timezone.utc),
        )
        is False
    )
