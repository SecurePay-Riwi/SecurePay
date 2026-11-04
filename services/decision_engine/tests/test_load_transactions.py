"""The load test's transactions (HU-60, infra/load/transactions.py) are
requests the engine accepts: every type, the accounts each type needs and
the currency of the account that pays, so the load measures decisions and
not 422s."""

import importlib.util
import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from services.decision_engine.schemas import TransactionRequest

LOAD = Path(__file__).resolve().parents[3] / "infra" / "load"


def _module():
    spec = importlib.util.spec_from_file_location(
        "load_transactions", LOAD / "transactions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_transaction_is_a_valid_request_in_the_payer_s_currency():
    load = _module()
    currency = {a["id"]: a["currency"] for a in load.DATA["accounts"]}
    rng, now = random.Random(7), datetime(2026, 10, 5, 12, tzinfo=UTC)
    kinds = Counter()

    for _ in range(2000):
        body = load.transaction(rng, now)
        request = TransactionRequest.model_validate(body)
        payer = body[
            "destination_account_id"
            if body["type"] == "RECARGA"
            else "source_account_id"
        ]
        kinds[request.type.value] += 1

        assert request.currency == currency[payer]
        assert request.amount > 0
        assert body["source_account_id"] != body["destination_account_id"]

    assert set(kinds) == set(load.MIX)
    assert kinds["P2P"] > kinds["QR"] > kinds["RECARGA"] > kinds["RETIRO"]


def test_the_accounts_are_the_seed_s_active_ones():
    load = _module()

    assert len(load.DATA["accounts"]) >= 2
    assert load.DATA["merchants"]
    assert {a["currency"] for a in load.DATA["accounts"]} <= set(load.AMOUNT)
