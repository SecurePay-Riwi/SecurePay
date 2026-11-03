"""C4: the generator's labels and the Kaggle rows of the seed. No Java
needed; the Kaggle test needs the seeded PostgreSQL (it skips without
the Kaggle ETL loaded)."""

import json
import uuid
from decimal import Decimal

import pytest

from services.analytics import labels
from services.analytics.tests.conftest import DAY, FIXTURES
from shared.analytics import LabelSource

LABELS = FIXTURES / "raw" / "labels" / "fecha=2026-10-05" / "labels.jsonl"


def test_generator_labels_are_one_per_transaction():
    lines = [json.loads(x) for x in LABELS.read_text(encoding="utf-8").splitlines()]
    found = labels.generator_labels(str(LABELS))

    assert any(x["kind"] == "security" for x in lines)
    assert any(x.get("duplicate") for x in lines)
    assert len(found) == len({x["id"] for x in lines if x["kind"] == "transaction"})
    assert {f.source for f in found} == {LabelSource.GENERATOR.value}
    velocity = [f for f in found if f.pattern == "VELOCITY"]
    assert len(velocity) == 6 and all(f.is_fraud for f in velocity)
    assert sum(1 for f in velocity if f.expected_rule == "velocity") == 1


def test_copy_labels_puts_the_file_in_raw(tmp_path):
    target = labels.copy_labels(str(LABELS), DAY, str(tmp_path))

    assert target == f"{tmp_path}/raw/labels/fecha=2026-10-05/labels.jsonl"
    assert (
        tmp_path / "raw" / "labels" / "fecha=2026-10-05" / "labels.jsonl"
    ).read_text(encoding="utf-8") == LABELS.read_text(encoding="utf-8")


def test_the_command_copies_the_labels(tmp_path, capsys):
    labels.main(["--day", "2026-10-05", "--file", str(LABELS), "--root", str(tmp_path)])

    out = json.loads(capsys.readouterr().out)
    assert out["labels"].endswith("raw/labels/fecha=2026-10-05/labels.jsonl")


def test_the_command_needs_the_file(tmp_path):
    with pytest.raises(SystemExit, match="does not exist"):
        labels.main(["--day", "2026-10-05", "--file", str(tmp_path / "none.jsonl")])


def test_generator_events_skips_what_the_engine_refuses(tmp_path):
    good = json.loads(
        (FIXTURES / "raw" / "decisiones" / "fecha=2026-10-05" / "part-0001.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[1]
    )["transaction"]
    bad = {**good, "id": str(uuid.uuid4()), "amount": "10.123"}
    security = json.loads(
        (FIXTURES / "security_events.jsonl").read_text().splitlines()[0]
    )
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(x)
            for x in (
                {"kind": "transaction", "body": good},
                {"kind": "transaction", "body": bad},
                {"kind": "security", "body": security},
            )
        )
    )

    transactions, events = labels.generator_events(str(path))

    assert [str(t.id) for t in transactions] == [good["id"]]
    assert len(events) == 1


def test_kaggle_source_from_the_pattern_or_the_id():
    sparkov_id = str(uuid.uuid5(labels.SEED_NAMESPACE, "hist:fraudtest:12"))
    paysim_id = str(uuid.uuid5(labels.SEED_NAMESPACE, "hist:paysim:12"))

    assert (
        labels.kaggle_source(paysim_id, "kaggle_paysim_transfer") is LabelSource.PAYSIM
    )
    assert (
        labels.kaggle_source(paysim_id, "kaggle_fraudtest_travel")
        is LabelSource.SPARKOV
    )
    assert labels.kaggle_source(sparkov_id, None) is LabelSource.SPARKOV
    assert labels.kaggle_source(paysim_id, None) is LabelSource.PAYSIM


def test_kaggle_amounts_go_to_the_accounts_currency():
    assert labels._in_currency(Decimal("10"), "USD") == Decimal("10.00")
    assert labels._in_currency(Decimal("10"), "COP") == Decimal("33176.50")
    assert labels._in_currency(Decimal("0.001"), "JPY") == Decimal("1")


def test_kaggle_transactions_from_the_seed():
    """Two rows as the seed's Kaggle ETL writes them, inserted on the seed's
    first user and rolled back."""
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError

    from shared.db import SessionLocal
    from shared.models import Comercio, Cuenta, Dispositivo, Transaccion

    try:
        session = SessionLocal()
        account = session.execute(
            select(Cuenta.id, Cuenta.user_id, Cuenta.moneda).order_by(Cuenta.id)
        ).first()
    except OperationalError:
        pytest.skip("PostgreSQL is not available")
    try:
        if account is None:
            pytest.skip("the seed is not loaded")
        device = session.scalars(select(Dispositivo.id)).first()
        merchant = session.scalars(select(Comercio.id)).first()
        fraud_id = uuid.uuid5(labels.SEED_NAMESPACE, "hist:paysim:7")
        legit_id = uuid.uuid5(labels.SEED_NAMESPACE, "hist:fraudtest:7")
        when = datetime(2026, 9, 20, 10, tzinfo=UTC)
        for tx_id, fraud, pattern in (
            (fraud_id, True, "kaggle_paysim_transfer"),
            (legit_id, False, None),
        ):
            session.add(
                Transaccion(
                    id=tx_id,
                    user_id=account.user_id,
                    device_id=device,
                    merchant_id=merchant,
                    amount=Decimal("12.50"),
                    transaction_date=when,
                    channel="APP",
                    is_fraud=fraud,
                    fraud_pattern=pattern,
                )
            )
        session.flush()

        transactions, found = labels.kaggle_transactions(session)
    finally:
        session.rollback()
        session.close()

    by_id = {str(t.id): t for t in transactions}
    label_of = {f.transaction_id: f for f in found}
    tx = by_id[str(fraud_id)]
    assert (tx.type.value, tx.currency, str(tx.source_account_id)) == (
        "QR",
        account.moneda,
        str(account.id),
    )
    assert tx.amount == labels._in_currency(Decimal("12.50"), account.moneda)
    assert label_of[str(fraud_id)].source == "paysim"
    assert label_of[str(fraud_id)].is_fraud is True
    assert label_of[str(legit_id)].source == "sparkov"
    assert label_of[str(legit_id)].pattern is None
