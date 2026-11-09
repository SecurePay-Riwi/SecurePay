"""What each component's database user may do, read from its queries.

Only the components deployed in AWS have a user here. The rules cache
refresh is not built: the rules API publishes the catalog itself, so
rules_reader has a password in Parameter Store and no user.

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
    # services/analytics/export.py: the current state of the cases and the
    # reconciliation of the export window, read only (HU-66, C6); with
    # {"job": "kaggle_metrics"} the Kaggle replay (metrics.kaggle_metrics,
    # MAG-312): the Kaggle rows, the reference data and the latest catalog.
    "analytics_export": {
        "cases": READ,
        "case_events": READ,
        "reconciliation_differences": READ,
        "reconciliation_runs": READ,
        "transacciones": READ,
        "cuentas": READ,
        "usuarios": READ,
        "comercios": READ,
        "listas_restrictivas": READ,
        "rule_catalog_versions": READ,
    },
    # services/rules_api/store.py: the catalog (rules is the current state,
    # rule_catalog_versions is append-only by trigger). The simulation
    # (simulation.py) reads the reference data like the cache loader.
    "rules_api": {
        "rules": ("SELECT", "INSERT", "UPDATE"),
        "rule_catalog_versions": ("SELECT", "INSERT"),
        "cuentas": READ,
        "usuarios": READ,
        "comercios": READ,
        "listas_restrictivas": READ,
    },
    # services/cases_api: assign and resolve lock the case (FOR UPDATE) and
    # write its event; evidence.archive() sets evidence_key; treasury
    # resolves differences; the rest is read only.
    "cases_api": {
        "cases": ("SELECT", "UPDATE"),
        "case_events": ("SELECT", "INSERT"),
        "compliance_reports": READ,
        "account_transactions": READ,
        "reconciliation_differences": ("SELECT", "UPDATE"),
        "reconciliation_runs": READ,
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
    "cases_api": [("case_events", "id")],
}

USERS = sorted(TABLES)
