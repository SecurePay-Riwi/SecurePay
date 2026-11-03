"""What each component's database user may do, read from its queries.

Only the components deployed in AWS have a user here. The cases API, the
rules API and the rules cache refresh get theirs in the pull request that
deploys them (their passwords already exist in Parameter Store).

INSERT ... RETURNING and an ORM insert (which returns the new id) also
need SELECT; SELECT ... FOR UPDATE needs UPDATE; DELETE with a WHERE needs
SELECT. Nobody gets DROP, TRUNCATE or ALTER: the tables belong to the
master user.
"""

READ = ("SELECT",)

# user -> {table: privileges}
TABLES: dict[str, dict[str, tuple[str, ...]]] = {
    # services/consumers/cases.py: opens the case and its CREATED event;
    # restricted-list reports read the owners of the accounts.
    "cases_consumer": {
        "cases": ("SELECT", "INSERT"),
        "case_events": ("SELECT", "INSERT"),
        "compliance_reports": ("SELECT", "INSERT"),
        "cuentas": READ,
        "usuarios": READ,
        "listas_restrictivas": READ,
    },
    # services/consumers/history.py: one row per account of the transaction.
    "history_consumer": {
        "account_transactions": ("SELECT", "INSERT"),
    },
    # services/alerts: escalation and evidence (cases, case_events), the
    # compliance summary (compliance_reports), the 30-day purge
    # (account_transactions) and the reconciliation check.
    "alerts": {
        "cases": ("SELECT", "UPDATE"),
        "case_events": ("SELECT", "INSERT"),
        "compliance_reports": ("SELECT", "UPDATE"),
        "account_transactions": ("SELECT", "DELETE"),
        "reconciliation_runs": READ,
    },
    # services/reconciliation/store.py: upserts the run, inserts differences.
    "reconciliation": {
        "reconciliation_runs": ("SELECT", "INSERT", "UPDATE"),
        "reconciliation_differences": ("SELECT", "INSERT"),
    },
    # services/cache_loader/loader.py: copies the reference data to the cache.
    "list_loader": {
        "cuentas": READ,
        "usuarios": READ,
        "comercios": READ,
        "listas_restrictivas": READ,
    },
}

# user -> [(table, column)] of the identity sequences it inserts into.
SEQUENCES: dict[str, list[tuple[str, str]]] = {
    "cases_consumer": [("case_events", "id")],
    "alerts": [("case_events", "id")],
}

USERS = sorted(TABLES)
