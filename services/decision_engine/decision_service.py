import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as DecisionTimeout
from datetime import UTC, datetime

import valkey

from services.decision_engine import (
    catalog,
    currency,
    history,
    publisher,
    reference_data,
    rules,
)
from services.decision_engine import idempotency as idem
from services.decision_engine.reference_data import CacheUnavailable
from services.decision_engine.rules.base import RuleContext, TriggeredRule
from services.decision_engine.schemas import (
    Decision,
    TransactionRequest,
    TransactionType,
)
from shared import cache
from shared.cache import get_cache
from shared.events import evento_decision
from shared.refdata import digits
from shared.rule_catalog import CatalogSnapshot, DefaultTimeoutParams

# What leaves the source account goes into its outgoing history.
# A top-up has no source account.
OUTGOING_TYPES = {TransactionType.P2P, TransactionType.QR, TransactionType.RETIRO}

# When several rules fire, the most severe wins.
SEVERITY = {Decision.APPROVE: 0, Decision.HOLD: 1, Decision.REJECT: 2}

NO_RULES_REASON = "The transaction did not trigger any configured rule."

log = logging.getLogger(__name__)

# One JSON line per decision worth looking at (HU-59): every HOLD,
# REJECT or default decision, and any decision slower than
# SLOW_DECISION_MS. CloudWatch metric filters count the default ones
# (alarm 2) and Logs Insights finds the slow ones. A plain fast APPROVE
# is not logged: logging every transaction would be over 100 GB a month.
decisions_log = logging.getLogger("securepay.decisions")
SLOW_DECISION_MS = int(os.getenv("SLOW_DECISION_MS", "150"))

# RN-01: every transaction gets a decision in 200 ms. The engine stops
# waiting for the rules well before that, so the default decision and
# the network still fit in the budget.
TIMEOUT_MS = int(os.getenv("DECISION_TIMEOUT_MS", "120"))
# Threads that evaluate the rules. A decision that times out keeps its
# thread until it ends, so this matches the requests FastAPI serves at
# once (40 by default).
WORKERS = int(os.getenv("DECISION_WORKERS", "40"))

if TIMEOUT_MS <= 0 or WORKERS <= 0:
    raise ValueError("Timeout and workers must be positive.")

# Catalog entry of RN-01's default decision. It is never evaluated as a
# rule: default_decision() reads its limit.
DEFAULT_RULE = "default_timeout"

# The restricted list rule. If it is enabled and the list is not in the
# cache, the transaction is held whatever the amount (D2).
RESTRICTED_RULE = "restricted_list"

# Highest risk score a decision reports.
MAX_RISK_SCORE = 100

_workers = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="decision")


def choose_decision(triggered: list[TriggeredRule]) -> tuple[Decision, str]:
    """Turn what each rule said into one decision and its reason.

    The most severe wins (reject, then hold). With no rule fired, the
    transaction is approved. Between two of the same severity, the first
    one evaluated wins.
    """
    if not triggered:
        return Decision.APPROVE, NO_RULES_REASON

    worst = max(triggered, key=lambda r: SEVERITY[r.decision])
    return worst.decision, worst.reason


class InvalidReference(Exception):
    """The transaction cannot be decided as sent: its currency is not
    the account's."""


def normalize_document(document: str) -> str:
    """Keep only the digits, which is how the restricted list is stored."""
    return digits(document)


def evaluate_rules(ctx: RuleContext, snapshot: CatalogSnapshot) -> list[TriggeredRule]:
    """Every enabled rule of the catalog, in its order, even if one
    already rejects: the decision records all the rules that fired."""
    triggered = []
    for entry in snapshot.rules:
        if not entry.enabled or entry.type == DEFAULT_RULE:
            continue
        impl = rules.REGISTRY.get(entry.type)
        if impl is None:
            # A type the catalog knows but this engine has no code for yet.
            continue
        result = impl.evaluate(ctx, entry)
        if result:
            triggered.append(result)
    return triggered


# on_restricted_list was not read with the history: RuleContext reads it
# when a rule asks.
_NOT_READ = object()


def _write_history(payload, main_account, documents, check_list):
    """Write the account history and, when the restricted list rule is
    enabled, read the list, in one round trip to the cache.

    The history is written before deciding, whatever the decision and
    whichever rules are enabled, because the attempt counts too (see
    history.py). Returns the source account's outgoing history, the
    accounts of the device and the restricted list's answer (_NOT_READ
    when it was not read here).

    Each Valkey round trip took about 1.7 ms in AWS, and a decision made
    8 of them; ten tasks did not hold 300 tx/s (load test of 2026-11-05).
    """
    records = []
    if payload.type in OUTGOING_TYPES:
        records.append(
            history.outgoing_record(
                payload.source_account_id,
                payload.id,
                payload.type.value,
                payload.amount,
                payload.transaction_date,
            )
        )
    if payload.type == TransactionType.P2P:
        records.append(
            history.incoming_record(
                payload.destination_account_id,
                payload.id,
                payload.source_account_id,
                payload.amount,
                payload.transaction_date,
            )
        )
    records.append(
        history.device_record(
            payload.device_id, main_account.id, payload.transaction_date
        )
    )

    if history.uses_valkey() and reference_data.uses_cache():
        pipe = get_cache().pipeline(transaction=False)
        history.queue(pipe, records)
        if check_list:
            reference_data.queue_restricted(pipe, documents)
        try:
            replies = pipe.execute(raise_on_error=False)
            written = history.finish(records, replies[: len(records)])
        except valkey.exceptions.ValkeyError as exc:
            raise CacheUnavailable(str(exc)) from exc
        on_list = (
            reference_data.restricted_answer(replies[len(records) :])
            if check_list
            else _NOT_READ
        )
    else:
        # A replay (services/analytics/): another backend or source.
        written = history.run(records)
        on_list = _NOT_READ

    outgoing = written[0] if payload.type in OUTGOING_TYPES else []
    return outgoing, written[-1], on_list


def _mark(stages: dict | None, name: str) -> None:
    """Time of one stage of _decide(), for late_decision_line()."""
    if stages is not None:
        stages[name] = time.perf_counter()


def _decide(
    payload: TransactionRequest, snapshot: CatalogSnapshot, stages: dict | None = None
) -> dict:
    """Apply the catalog's rules and return the decision, without
    storing it.

    Accounts, merchants and the restricted list come from the cache
    (HU-67): the engine never reads PostgreSQL. What is missing there
    gets RN-01's default decision (D2); CacheUnavailable goes up to
    _decide_in_time(), which answers the same way.
    """
    _mark(stages, "started")
    # Both accounts and the merchant in one round trip to the cache.
    accounts, merchant_found = reference_data.lookup(
        (payload.source_account_id, payload.destination_account_id),
        payload.merchant_id,
    )
    for account_id, account in accounts.items():
        if account is None:
            return default_decision(
                payload, snapshot, f"account {account_id} is not in the cache"
            )

    if merchant_found is False:
        return default_decision(
            payload, snapshot, f"merchant {payload.merchant_id} is not in the cache"
        )

    # The main account is the source; in a top-up, the destination.
    main_account = accounts[payload.source_account_id or payload.destination_account_id]

    if main_account.currency != payload.currency:
        raise InvalidReference("The transaction currency is not the account currency.")

    # Documents of every account owner involved, for the restricted list
    # rule (first in the catalog, so it is checked before the others).
    # The loader already keeps only the digits.
    documents = {normalize_document(account.document) for account in accounts.values()}

    _mark(stages, "lookup")
    restricted = snapshot.get(RESTRICTED_RULE)
    check_list = bool(restricted and restricted.enabled)
    outgoing, device_accounts, on_list = _write_history(
        payload, main_account, documents, check_list
    )
    _mark(stages, "history")

    rate = currency.rate_for(
        payload.currency, currency.utc_day(payload.transaction_date)
    )
    amount_usd = currency.convert(payload.amount, rate)
    ctx = RuleContext(
        payload=payload,
        t_ms=history.to_ms(payload.transaction_date),
        amount_usd=amount_usd,
        rate=rate,
        outgoing=outgoing,
        documents=documents,
        device_accounts=device_accounts,
    )
    if on_list is not _NOT_READ:
        ctx.on_restricted_list = on_list

    if check_list and ctx.on_restricted_list is None:
        return restricted_list_not_loaded(payload, snapshot)

    triggered = evaluate_rules(ctx, snapshot)
    decision, reason = choose_decision(triggered)
    _mark(stages, "rules")

    return {
        "transaction_id": str(payload.id),
        "decision": decision.value,
        "decision_reason": reason,
        "rules_version": str(snapshot.version),
        "rules_triggered": [r.rule for r in triggered],
        # RN-08: the version of each rule that fired, so an auditor can
        # tell which thresholds decided without reading the whole catalog.
        "rule_versions": {r.rule: r.rule_version for r in triggered},
        "opens_case": any(r.opens_case for r in triggered),
        # RN-11: the cases and the account history store it (sprint 4).
        "amount_usd": str(amount_usd),
        # HU-42: the rate behind amount_usd (the transaction's day, or the
        # last earlier day with a rate).
        **_rate_fields(rate),
        "risk_score": min(MAX_RISK_SCORE, sum(r.score for r in triggered)),
        "by_default": False,
        "processed_at": datetime.now(UTC).isoformat(),
    }


def _rate_fields(rate: currency.Rate) -> dict:
    return {"usd_rate": str(rate.per_usd), "rate_date": rate.rate_date.isoformat()}


def default_decision(
    payload: TransactionRequest,
    snapshot: CatalogSnapshot,
    why: str | None = None,
) -> dict:
    """RN-01: the decision when the rules cannot decide: they do not
    answer in time, or the cache does not have (or does not return) the
    data they need (D2).

    Approve below the catalog's limit (USD 50), hold from it up. Never
    reject: being slow is not a reason to turn a customer down.
    """
    entry = snapshot.get(DEFAULT_RULE)
    params = entry.typed_params() if entry else DefaultTimeoutParams()
    rate = currency.rate_for(
        payload.currency, currency.utc_day(payload.transaction_date)
    )
    amount_usd = currency.convert(payload.amount, rate)
    why = why or f"the rules did not answer in {TIMEOUT_MS} ms"

    if amount_usd < params.limit_usd:
        decision = Decision.APPROVE
    else:
        decision = Decision.HOLD

    return {
        "transaction_id": str(payload.id),
        "decision": decision.value,
        "decision_reason": (
            f"Default decision: {why} (USD {amount_usd}, limit USD {params.limit_usd})."
        ),
        "rules_version": str(snapshot.version),
        "rules_triggered": [DEFAULT_RULE],
        "rule_versions": {DEFAULT_RULE: entry.rule_version if entry else 1},
        "opens_case": False,
        "amount_usd": str(amount_usd),
        **_rate_fields(rate),
        "risk_score": 0,
        "by_default": True,
        "processed_at": datetime.now(UTC).isoformat(),
    }


def restricted_list_not_loaded(
    payload: TransactionRequest, snapshot: CatalogSnapshot
) -> dict:
    """D2: without the restricted list nobody can tell whether an owner
    is listed, so the transaction is held whatever the amount."""
    result = default_decision(payload, snapshot)
    result["decision"] = Decision.HOLD.value
    result["decision_reason"] = (
        "Default decision: the restricted list is not loaded in the cache, "
        f"held whatever the amount (USD {result['amount_usd']})."
    )
    return result


def _decide_in_time(payload: TransactionRequest) -> dict:
    """Run the rules, or answer with the default decision if they take
    longer than TIMEOUT_MS or the cache does not answer.

    The catalog is read once, before starting: the rules and the default
    decision use the same version.

    A Python thread cannot be stopped, so a late evaluation that already
    started finishes in the background and its result is dropped: the
    stored and published decision is the default one. One that is still
    waiting for a worker is cancelled: under overload the queue would
    otherwise keep every worker busy with decisions nobody waits for, and
    every new one would time out too (load test of 2026-11-05).
    """
    snapshot = catalog.current()
    stages = {"submitted": time.perf_counter()}
    future = _workers.submit(_decide, payload, snapshot, stages)

    try:
        return future.result(timeout=TIMEOUT_MS / 1000)
    except DecisionTimeout:
        if not future.cancel():
            # Started: say where its time went once it ends (HU-60).
            future.add_done_callback(
                lambda _f: _log_late(str(payload.id), stages, time.perf_counter())
            )
        else:
            _log_late(str(payload.id), stages, time.perf_counter())
        log.warning("Transaction %s: rules timed out, default decision", payload.id)
        return default_decision(payload, snapshot)
    except CacheUnavailable as exc:
        log.warning(
            "Transaction %s: cache unavailable (%s), default decision", payload.id, exc
        )
        return default_decision(payload, snapshot, "the cache did not answer")


def process_transaction(payload: TransactionRequest) -> tuple[dict, bool]:
    """
    Evaluate a transaction only once per id.

    Returns (result, replay).
    replay=True means an existing decision was reused.

    Only the first decision is published to SNS: a resend returns the
    stored decision without publishing it again.
    """
    transaction = payload.model_dump(mode="json")
    fingerprint = idem.huella(transaction)

    previous = idem.reservar(payload.id, fingerprint)

    if previous:
        return previous, True

    started = time.perf_counter()
    try:
        result = _decide_in_time(payload)
    except Exception:
        # No decision means nothing to replay: the retry must decide.
        idem.liberar(payload.id)
        raise
    log_decision(result, (time.perf_counter() - started) * 1000)

    idem.guardar(payload.id, fingerprint, result)

    # Does not wait for SNS: hands the event to the background thread.
    publisher.publicar(evento_decision(transaction, result))

    return result, False


def decision_line(result: dict, elapsed_ms: float) -> dict | None:
    """The JSON line of a decision, or None when it is not worth a line
    (a fast APPROVE that no default decided)."""
    plain = result["decision"] == Decision.APPROVE.value and not result.get(
        "by_default"
    )
    if plain and elapsed_ms < SLOW_DECISION_MS:
        return None
    return {
        "event": "decision",
        "transaction_id": result["transaction_id"],
        "decision": result["decision"],
        "rules_triggered": result.get("rules_triggered", []),
        "risk_score": result.get("risk_score", 0),
        "by_default": bool(result.get("by_default")),
        "rules_version": result.get("rules_version"),
        "elapsed_ms": round(elapsed_ms, 1),
    }


# Stages of _decide() in order, and the field of each in the late line;
# each one's time runs from the previous.
STAGES = {
    "started": "queue_ms",
    "lookup": "lookup_ms",
    "history": "history_ms",
    "rules": "rules_ms",
}


def late_decision_line(transaction_id: str, stages: dict, ended: float) -> dict:
    """Where the time of a decision that timed out went, in ms: waiting
    for a worker (queue_ms), the accounts' round trip (lookup_ms), the
    history's (history_ms) and the rules (rules_ms). A stage it never
    reached is missing; total_ms is until it ended or was cancelled.
    One line per default decision by timeout, so the load test can tell
    a queue from a slow cache (HU-60, load test of 2026-11-05)."""
    line = {"event": "late_decision", "transaction_id": transaction_id}
    previous = stages["submitted"]
    for stage, field in STAGES.items():
        if stage not in stages:
            break
        line[field] = round((stages[stage] - previous) * 1000, 1)
        previous = stages[stage]
    line["total_ms"] = round((ended - stages["submitted"]) * 1000, 1)
    line["cache_connections"] = cache.stats["connections"]
    line["cache_refreshes"] = cache.stats["topology_refreshes"]
    return line


def _log_late(transaction_id: str, stages: dict, ended: float) -> None:
    try:
        line = late_decision_line(transaction_id, dict(stages), ended)
        decisions_log.info(json.dumps(line))
    except Exception:  # a log line never breaks a decision
        log.exception("Transaction %s: late decision line failed", transaction_id)


def log_decision(result: dict, elapsed_ms: float) -> None:
    line = decision_line(result, elapsed_ms)
    if line is not None:
        decisions_log.info(json.dumps(line, ensure_ascii=False))
