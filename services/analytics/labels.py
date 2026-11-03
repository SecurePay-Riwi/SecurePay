"""The labeled histories (contract C4; Habith).

Generator: securepay-generator writes, next to the events it sends,
generated/instance-<n>/labels.jsonl (one line per event: id, kind,
pattern, pattern_id, is_fraud, expected_rule; a resent duplicate repeats
the id with "duplicate": true; kind "security" lines are device and
password changes). It is copied as it is to
raw/labels/fecha=<day>/labels.jsonl:

    uv run python -m services.analytics.labels --day 2026-10-05 \
        [--file ../securepay-generator/generated/instance-0/labels.jsonl] \
        [--root generated/analytics]

Kaggle: securepay-seed's Kaggle ETL loads PaySim and Sparkov (fraudTest)
rows into the transacciones table with is_fraud and fraud_pattern. The
table keeps no type, account, currency or dataset, so
kaggle_transactions() rebuilds each row as the engine would see it:

- source: fraud rows say it in fraud_pattern (kaggle_paysim_<type>,
  kaggle_fraudtest_<category>). A legitimate row has no pattern; its id
  tells: the seed makes it uuid5(SEED_NAMESPACE, "hist:<dataset>:<row>")
  from the row of the CSV, so the ids of every fraudTest row are
  recomputed (FRAUDTEST_ROWS of them) and the rest are PaySim. A data
  contract with the seed, never an import.
- the transaction: a QR payment of the row's amount from the user's
  account to the row's merchant, with the row's channel and date. The
  amount (USD in the datasets) goes to the account's currency at the
  engine's fixed 2026-10-01 rates. The balances are not in the table:
  before = the amount, after = 0 (only the mule rule reads them, on
  withdrawals).

Files and the database only: this repo never imports securepay-generator
or securepay-seed.
"""

import argparse
import json
import logging
import uuid
from datetime import UTC, date
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path

from services.analytics import ANALYTICS_DATA_DIR, LABELS_SOURCE
from services.analytics.metrics import Label
from services.decision_engine.currency import RATES_PER_USD
from services.decision_engine.schemas import SecurityEventRequest, TransactionRequest
from services.reconciliation import storage
from shared.analytics import RAW_LABELS, LabelSource, layer_path
from shared.config import MONEDA_DECIMALES

log = logging.getLogger(__name__)

LABELS_FILE = "labels.jsonl"

# securepay-seed's kaggle_etl (data contract, see the module docstring).
SEED_NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")
FRAUDTEST_ROWS = 555_719  # rows of fraudTest.csv (its SHA-256 is fixed by the seed)
KAGGLE_PATTERN_PREFIX = {
    "kaggle_paysim_": LabelSource.PAYSIM,
    "kaggle_fraudtest_": LabelSource.SPARKOV,
}


# --- Generator ----------------------------------------------------------------


def copy_labels(file: str, day: date, root: str) -> str:
    """Copy the generator's labels.jsonl to raw/labels/fecha=<day>/ (local
    folder or s3://). Returns where it went."""
    target = f"{layer_path(root, RAW_LABELS, day)}/{LABELS_FILE}"
    storage.write_text(target, storage.read_text(file))
    return target


def generator_labels(path: str) -> list[Label]:
    """The labels of a labels.jsonl: one per transaction (the first line
    that is not a duplicate), security events left out."""
    labels: dict[str, Label] = {}
    for row in storage.read_jsonl(path):
        if row.get("kind", "transaction") != "transaction" or row.get("duplicate"):
            continue
        labels.setdefault(
            str(row["id"]),
            Label(
                transaction_id=str(row["id"]),
                source=LabelSource.GENERATOR.value,
                pattern=row.get("pattern"),
                is_fraud=bool(row.get("is_fraud")),
                expected_rule=row.get("expected_rule"),
            ),
        )
    return list(labels.values())


def generator_events(
    path: str,
) -> tuple[list[TransactionRequest], list[SecurityEventRequest]]:
    """The transactions and security events of the generator's
    events.jsonl (GEN_OUTPUT=file), for the replay. A line the engine
    would refuse (422, e.g. the decimal defects) is left out."""
    transactions, security = [], []
    for row in storage.read_jsonl(path):
        try:
            if row.get("kind") == "security":
                security.append(SecurityEventRequest(**row["body"]))
            else:
                transactions.append(TransactionRequest(**row["body"]))
        except ValueError:
            continue
    return transactions, security


# --- Kaggle -------------------------------------------------------------------


@cache
def _fraudtest_ids() -> frozenset[str]:
    return frozenset(
        str(uuid.uuid5(SEED_NAMESPACE, f"hist:fraudtest:{i}"))
        for i in range(FRAUDTEST_ROWS)
    )


def kaggle_source(transaction_id: str, pattern: str | None) -> LabelSource:
    """PaySim or Sparkov, from the pattern or else from the id."""
    for prefix, source in KAGGLE_PATTERN_PREFIX.items():
        if pattern and pattern.startswith(prefix):
            return source
    if str(transaction_id) in _fraudtest_ids():
        return LabelSource.SPARKOV
    return LabelSource.PAYSIM


def _in_currency(amount_usd: Decimal, currency: str) -> Decimal:
    unit = Decimal(1).scaleb(-MONEDA_DECIMALES[currency])
    amount = (Decimal(amount_usd) * RATES_PER_USD[currency]).quantize(
        unit, rounding=ROUND_HALF_UP
    )
    return max(amount, unit)


def kaggle_transactions(
    session, limit: int | None = None
) -> tuple[list[TransactionRequest], list[Label]]:
    """The Kaggle rows of transacciones as transactions for the replay,
    with their labels (oldest first; `limit` rows at most). Rows whose
    user has no account are left out."""
    from sqlalchemy import select

    from shared.models import Cuenta, Transaccion

    query = (
        select(
            Transaccion.id,
            Transaccion.device_id,
            Transaccion.merchant_id,
            Transaccion.amount,
            Transaccion.transaction_date,
            Transaccion.channel,
            Transaccion.is_fraud,
            Transaccion.fraud_pattern,
            Cuenta.id,
            Cuenta.moneda,
        )
        .join(Cuenta, Cuenta.user_id == Transaccion.user_id)
        .order_by(Transaccion.transaction_date, Transaccion.id)
    )
    if limit is not None:
        query = query.limit(limit)

    transactions, labels = [], []
    for (
        tx_id,
        device_id,
        merchant_id,
        amount,
        at,
        channel,
        is_fraud,
        pattern,
        account_id,
        currency,
    ) in session.execute(query):
        value = _in_currency(amount, currency)
        transactions.append(
            TransactionRequest(
                id=tx_id,
                type="QR",
                channel=channel,
                source_account_id=account_id,
                merchant_id=merchant_id,
                amount=value,
                currency=currency,
                source_balance_before=value,
                source_balance_after=Decimal(0),
                device_id=device_id,
                transaction_date=at if at.tzinfo else at.replace(tzinfo=UTC),
            )
        )
        labels.append(
            Label(
                transaction_id=str(tx_id),
                source=kaggle_source(str(tx_id), pattern).value,
                pattern=pattern,
                is_fraud=bool(is_fraud),
                expected_rule=None,
            )
        )
    return transactions, labels


def main(argv=None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="python -m services.analytics.labels")
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--file", default=LABELS_SOURCE)
    parser.add_argument("--root", default=ANALYTICS_DATA_DIR)
    args = parser.parse_args(argv)
    if not storage.is_s3(args.file) and not Path(args.file).is_file():
        raise SystemExit(f"{args.file} does not exist: run the generator first.")
    target = copy_labels(args.file, args.day, args.root)
    print(json.dumps({"day": args.day.isoformat(), "labels": target}))


if __name__ == "__main__":
    main()
