"""The engine re-run over a history, in memory (contract C5; Habith).

replay() calls the engine's own decision (decision_service._decide: the
rule modules of rules.REGISTRY, evaluate_rules and choose_decision) on
each transaction in transaction_date order, with the account history in
an InMemoryHistory (history.use_backend) and the accounts, merchants and
restricted list in a ReferenceData (reference_data.use_source). No
Valkey, no network, no PostgreSQL: the rule code exists once, in
services/decision_engine/rules/.

Exchange rates: whatever services.decision_engine.currency has loaded;
without a table, the engine's fixed 2026-10-01 rates (as in its tests).

Nobody outside services/analytics/ imports this module; the rules API
only inside its simulation route (HU-24).
"""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from services.decision_engine import decision_service, history, reference_data
from services.decision_engine import security_events as security
from services.decision_engine.reference_data import Account
from services.decision_engine.schemas import SecurityEventRequest, TransactionRequest
from shared.refdata import digits
from shared.rule_catalog import CatalogSnapshot

log = logging.getLogger(__name__)

# The file ReferenceData.from_fixtures() reads in a fixtures folder.
REFERENCE_FILE = "reference.json"


@dataclass(frozen=True)
class ReplayDecision:
    transaction_id: str
    decision: str  # APPROVE / HOLD / REJECT
    rules_triggered: tuple[str, ...]
    risk_score: int
    opens_case: bool
    rules_version: str


@dataclass(frozen=True)
class ReferenceData:
    """What the engine reads from the cache, in memory."""

    accounts: dict[str, dict]  # account_id -> {currency, user_id, document, status}
    merchants: set[str] = field(default_factory=set)
    restricted_documents: set[str] = field(default_factory=set)  # digits only

    # The three reads of services/decision_engine/reference_data.py.

    def get_account(self, account_id) -> Account | None:
        data = self.accounts.get(str(account_id))
        if data is None:
            return None
        return Account(
            id=str(account_id),
            currency=data["currency"],
            user_id=str(data["user_id"]),
            document=digits(data["document"]),
            status=data["status"],
        )

    def merchant_exists(self, merchant_id) -> bool:
        return str(merchant_id) in self.merchants

    def on_restricted_list(self, documents: set[str]) -> bool:
        return bool(set(documents) & self.restricted_documents)

    @classmethod
    def from_database(cls, session) -> "ReferenceData":
        """The same rows the cache loader writes to Valkey (HU-67)."""
        from sqlalchemy import select

        from shared.models import Comercio, Cuenta, ListaRestrictiva, Usuario

        accounts = {
            str(account_id): {
                "currency": currency,
                "user_id": str(user_id),
                "document": digits(document),
                "status": status,
            }
            for account_id, currency, user_id, document, status in session.execute(
                select(
                    Cuenta.id,
                    Cuenta.moneda,
                    Cuenta.user_id,
                    Usuario.documento,
                    Cuenta.estado,
                ).join(Usuario, Usuario.id == Cuenta.user_id)
            )
        }
        merchants = {str(m) for (m,) in session.execute(select(Comercio.id))}
        restricted = {
            digits(d)
            for (d,) in session.execute(select(ListaRestrictiva.documento))
            if digits(d)
        }
        return cls(accounts, merchants, restricted)

    @classmethod
    def from_fixtures(cls, folder: str) -> "ReferenceData":
        """reference.json of a fixtures folder: {"accounts": {...},
        "merchants": [...], "restricted_documents": [...]}."""
        data = json.loads((Path(folder) / REFERENCE_FILE).read_text(encoding="utf-8"))
        return cls(
            accounts=data["accounts"],
            merchants=set(data.get("merchants", [])),
            restricted_documents=set(data.get("restricted_documents", [])),
        )


def decide_all(
    snapshot: CatalogSnapshot,
    transactions: Iterable[TransactionRequest],
    reference: ReferenceData,
    security_events: Iterable[SecurityEventRequest] = (),
) -> list[tuple[TransactionRequest, dict]]:
    """Each transaction with the engine's whole decision (the dict of
    _decide), in transaction_date order (then id). A repeated id is
    decided once, like the engine's idempotency. Security events are
    recorded before the transactions at or after their event_date. A
    transaction whose currency is not its account's (the engine answers
    422) is left out. A new in-memory history for each call."""
    ordered = sorted(transactions, key=lambda t: (t.transaction_date, str(t.id)))
    pending = sorted(security_events, key=lambda e: (e.event_date, str(e.id)))
    seen: set[str] = set()
    decided = []
    with (
        history.use_backend(history.InMemoryHistory()),
        reference_data.use_source(reference),
    ):
        i = 0
        for tx in ordered:
            while i < len(pending) and pending[i].event_date <= tx.transaction_date:
                security.record(pending[i])
                i += 1
            if str(tx.id) in seen:
                continue
            seen.add(str(tx.id))
            try:
                decided.append((tx, decision_service._decide(tx, snapshot)))
            except decision_service.InvalidReference:
                log.warning(
                    "Replay: %s left out (currency is not the account's)", tx.id
                )
    return decided


def replay(
    snapshot: CatalogSnapshot,
    transactions: Iterable[TransactionRequest],
    reference: ReferenceData,
    security_events: Iterable[SecurityEventRequest] = (),
) -> list[ReplayDecision]:
    """Runs the engine's own rule modules (rules.REGISTRY, evaluate_rules,
    choose_decision) over `transactions` in transaction_date order, with an
    in-memory history (history.use_backend(InMemoryHistory())) and in-memory
    reference data. No Valkey, no network, no PostgreSQL: the rule code
    exists once, in services/decision_engine/rules/."""
    return [
        ReplayDecision(
            transaction_id=str(tx.id),
            decision=result["decision"],
            rules_triggered=tuple(result["rules_triggered"]),
            risk_score=result["risk_score"],
            opens_case=result["opens_case"],
            rules_version=result["rules_version"],
        )
        for tx, result in decide_all(snapshot, transactions, reference, security_events)
    ]
