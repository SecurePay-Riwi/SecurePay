"""Analytics contract (sprint 6, contracts C1 and C2): the layers of the
data lake, their paths, and the tables of the dimensional model.

Nobody else defines tables, columns or types: a new column is a small PR
on this file. The data dictionary (doc-website/docs/reference/
analytics-model.mdx), the Parquet schemas (spark_schema) and, in AWS, the
Glue catalog tables all come from TABLES. Not part of the published
securepay-shared package.

    RAW        raw/decisiones/fecha=<day>/*.jsonl        analytics consumer
               raw/labels/fecha=<day>/labels.jsonl       generator labels (C4)
               raw/cases/fecha=<day>/*.jsonl             PostgreSQL export (C6)
               raw/reconciliation/fecha=<day>/*.jsonl    PostgreSQL export (C6)
               raw/metrics/kaggle/<table>.jsonl          Kaggle replay metrics (C5)
    CURATED    curated/decisiones/fecha=<day>/           Parquet, one row per transaction
    ANALYTICS  analytics/<table>/[fecha=<day>/]          Parquet, the tables below

Amounts are decimal(18,2), rates decimal(18,8), ratios decimal(9,4),
days date and moments timestamp in UTC. pyspark is imported inside
spark_schema() only.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum

RAW_DECISIONS = "raw/decisiones"  # fecha=<day>/ JSON lines (exists)
RAW_LABELS = "raw/labels"  # fecha=<day>/labels.jsonl (C4)
RAW_CASES = "raw/cases"  # fecha=<day>/cases.jsonl, case_events.jsonl (C6)
# fecha=<day>/differences.jsonl, runs.jsonl, matched.jsonl (C6)
RAW_RECONCILIATION = "raw/reconciliation"
RAW_METRICS = "raw/metrics"  # kaggle/<table>.jsonl: a replay's metrics (HU-44)
CURATED_DECISIONS = (
    "curated/decisiones"  # fecha=<day>/ Parquet, one row per transaction_id
)
ANALYTICS = "analytics"  # analytics/<table>/ Parquet

# The partition folder of every daily layer, as in raw/decisiones.
PARTITION = "fecha"


def layer_path(root: str, layer: str, day: date | None = None) -> str:
    """<root>/<layer>/ or <root>/<layer>/fecha=<day>/ (root: local folder or s3://bucket)."""
    path = f"{str(root).rstrip('/')}/{layer.strip('/')}"
    if day is not None:
        path = f"{path}/{PARTITION}={day.isoformat()}"
    return path


def table_path(root: str, table: str, day: date | None = None) -> str:
    """analytics/<table>/ (or its partition of `day`) under root."""
    return layer_path(root, f"{ANALYTICS}/{table}", day)


class LabelSource(str, Enum):
    GENERATOR = "generator"
    PAYSIM = "paysim"
    SPARKOV = "sparkov"


# The types a column may have: what Spark and Athena both understand.
TYPES = (
    "string",
    "int",
    "bigint",
    "boolean",
    "date",
    "timestamp",
    "decimal(18,2)",
    "decimal(18,8)",
    "decimal(9,4)",
    "array<string>",
)


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # one of TYPES
    description: str  # English, goes to the data dictionary (E-10)

    def __post_init__(self):
        if self.type not in TYPES:
            raise ValueError(f"{self.name}: unknown type {self.type}")


@dataclass(frozen=True)
class Table:
    name: str  # e.g. fact_decision
    grain: str  # e.g. "one row per transaction"
    # The column whose value names the daily folder fecha=<value>/
    # ("day", "run_day" or "as_of"); None: one folder, rebuilt every run.
    partition: str | None
    columns: tuple[Column, ...]
    source: str  # lineage: the raw/curated paths it is built from
    owner: str = ""

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


def _c(name: str, type_: str, description: str) -> Column:
    return Column(name, type_, description)


_DAY = _c("day", "date", "Day of the transaction in UTC (the partition).")
_TX_ID = _c("transaction_id", "string", "Transaction id sent by the core (UUID).")
_RATIO = "decimal(9,4)"

# Columns of curated/decisiones: the transaction.decided event flattened,
# one row per transaction_id. Not a table of the model (it is a layer),
# but it has a fixed schema too: the replay of HU-24 rebuilds the
# transactions from it.
CURATED_DECISION = Table(
    name="curated_decision",
    grain="one row per transaction (the first event of each transaction_id)",
    partition="day",
    source=f"{RAW_DECISIONS}/fecha=<day-1..day+1> (the events whose transaction is of <day>)",
    owner="Habith",
    columns=(
        _TX_ID,
        _DAY,
        _c("transaction_at", "timestamp", "transaction_date of the core, in UTC."),
        _c("type", "string", "P2P, QR, RETIRO or RECARGA."),
        _c("channel", "string", "Where it was made: APP, WEB, CORRESPONSAL, CAJERO."),
        _c(
            "source_account_id", "string", "Account the money leaves (null in RECARGA)."
        ),
        _c(
            "destination_account_id",
            "string",
            "Account the money reaches (P2P and RECARGA).",
        ),
        _c("merchant_id", "string", "Merchant of a QR payment, else null."),
        _c("amount", "decimal(18,2)", "Amount in the transaction's currency."),
        _c("currency", "string", "COP, USD, EUR or JPY."),
        _c("source_balance_before", "decimal(18,2)", "Core's balance before."),
        _c("source_balance_after", "decimal(18,2)", "Core's balance after."),
        _c("destination_balance_before", "decimal(18,2)", "Core's balance before."),
        _c("destination_balance_after", "decimal(18,2)", "Core's balance after."),
        _c("device_id", "string", "Device the transaction came from."),
        _c("decision", "string", "APPROVE, HOLD or REJECT."),
        _c("decision_reason", "string", "Reason of the rule that decided."),
        _c("rules_version", "string", "Catalog version that decided (RN-08)."),
        _c("rules_triggered", "array<string>", "Every rule that fired."),
        _c(
            "rule_versions",
            "string",
            "JSON object: rule_version of each rule that fired.",
        ),
        _c("opens_case", "boolean", "Whether a rule that opens a case fired."),
        _c("risk_score", "int", "Sum of the fired rules' scores, at most 100."),
        _c("by_default", "boolean", "RN-01's default decision was applied."),
        _c("amount_usd", "decimal(18,2)", "Amount in USD at the day's rate (RN-11)."),
        _c("usd_rate", "decimal(18,8)", "Units of the currency per USD used."),
        _c("rate_date", "date", "Day of the rate used."),
        _c("processed_at", "timestamp", "When the engine decided (UTC)."),
    ),
)


TABLES: dict[str, Table] = {
    t.name: t
    for t in (
        Table(
            name="fact_decision",
            grain="one row per transaction",
            partition="day",
            source=f"{CURATED_DECISIONS}/fecha=<day>, {RAW_LABELS} (label_source)",
            owner="Habith",
            columns=(
                _TX_ID,
                _DAY,
                _c(
                    "transaction_at", "timestamp", "transaction_date of the core (UTC)."
                ),
                _c("type", "string", "P2P, QR, RETIRO or RECARGA."),
                _c("currency", "string", "COP, USD, EUR or JPY."),
                _c("channel", "string", "APP, WEB, CORRESPONSAL or CAJERO."),
                _c("amount", "decimal(18,2)", "Amount in the original currency."),
                _c("amount_usd", "decimal(18,2)", "Amount in USD (RN-11)."),
                _c("usd_rate", "decimal(18,8)", "Units of the currency per USD used."),
                _c("rate_date", "date", "Day of the exchange rate used."),
                _c("decision", "string", "APPROVE, HOLD or REJECT."),
                _c("risk_score", "int", "Sum of the fired rules' scores (0-100)."),
                _c("rules_version", "string", "Catalog version that decided (RN-08)."),
                _c("by_default", "boolean", "RN-01's default decision was applied."),
                _c("opens_case", "boolean", "A rule that opens a case fired."),
                _c("device_id", "string", "Device of the transaction."),
                _c("merchant_id", "string", "Merchant of a QR payment, else null."),
                _c("source_account_id", "string", "Source account (null in RECARGA)."),
                _c(
                    "destination_account_id",
                    "string",
                    "Destination account (P2P, RECARGA).",
                ),
                _c(
                    "label_source",
                    "string",
                    "LabelSource of its label; null when it is not labeled.",
                ),
            ),
        ),
        Table(
            name="fact_rule_hit",
            grain="one row per rule fired in a transaction",
            partition="day",
            source=f"{CURATED_DECISIONS}/fecha=<day> (rules_triggered, rule_versions)",
            owner="Habith",
            columns=(
                _TX_ID,
                _DAY,
                _c("rule", "string", "Rule code (rules_triggered)."),
                _c("rule_version", "int", "rule_version of the rule that fired."),
                _c(
                    "decision",
                    "string",
                    "What the rule decides (its catalog action); the transaction's "
                    "decision for default_timeout.",
                ),
                _c("score", "int", "Score the rule adds (its catalog entry)."),
            ),
        ),
        Table(
            name="fact_label",
            grain="one row per labeled transaction",
            partition="day",
            source=f"{RAW_LABELS}/fecha=*/labels.jsonl joined with {CURATED_DECISIONS}/fecha=<day>",
            owner="Habith",
            columns=(
                _TX_ID,
                _DAY,
                _c("source", "string", "LabelSource: generator, paysim or sparkov."),
                _c("pattern", "string", "Fraud pattern; null when legitimate."),
                _c("is_fraud", "boolean", "Whether the transaction is fraud."),
                _c(
                    "expected_rule",
                    "string",
                    "Rule the source expects to fire; null when none.",
                ),
            ),
        ),
        Table(
            name="fact_case",
            grain="one row per case, its current state",
            partition="day",
            source=f"{RAW_CASES}/fecha=<day>/cases.jsonl, case_events.jsonl",
            owner="Yulianis (HU-51)",
            columns=(
                _c("case_id", "string", "Case id."),
                _TX_ID,
                _c("day", "date", "Day of created_at in UTC (the partition)."),
                _c("created_at", "timestamp", "When the case was opened."),
                _c("due_at", "timestamp", "created_at + CASE_DUE_MINUTES (RN-09)."),
                _c("assigned_to", "string", "Current assignee; null if none."),
                _c("assigned_at", "timestamp", "Last ASSIGNED event; null if none."),
                _c("resolved_at", "timestamp", "When it was resolved; null if open."),
                _c("resolved_by", "string", "Who resolved it; null if open."),
                _c("status", "string", "OPEN, ESCALATED or RESOLVED."),
                _c("outcome", "string", "FRAUD or LEGITIMATE; null if open."),
                _c("final_decision", "string", "REJECT or APPROVE; null if open."),
                _c("escalated", "boolean", "Whether it was escalated (RN-09)."),
                _c("escalated_at", "timestamp", "When it was escalated; null if not."),
                _c(
                    "minutes_to_resolve",
                    "int",
                    "Whole minutes from created_at to resolved_at; null if open.",
                ),
                _c(
                    "within_sla",
                    "boolean",
                    "Resolved in 240 minutes or less (RN-09); null if open.",
                ),
                _c("rules_triggered", "array<string>", "Rules that fired."),
                _c("risk_score", "int", "risk_score of the decision."),
                _c("amount_usd", "decimal(18,2)", "Amount in USD of the decision."),
            ),
        ),
        Table(
            name="fact_difference",
            grain="one row per reconciliation difference, its current state",
            partition="run_day",
            source=f"{RAW_RECONCILIATION}/fecha=<day>/differences.jsonl",
            owner="Yulianis (HU-52)",
            columns=(
                _c("difference_id", "string", "Difference id."),
                _c("run_day", "date", "Day reconciled (the partition)."),
                _c("partner", "string", "Partner (shared/reconciliation.py Partner)."),
                _c(
                    "type",
                    "string",
                    "MISSING_IN_PARTNER, MISSING_IN_PAGOSEGURO or AMOUNT_MISMATCH.",
                ),
                _c("status", "string", "PENDING or RESOLVED."),
                _c("reference", "string", "PagoSeguro's transaction id."),
                _c("currency", "string", "Currency of the amounts."),
                _c(
                    "pagoseguro_amount", "decimal(18,2)", "Our amount; null if missing."
                ),
                _c("partner_amount", "decimal(18,2)", "Partner's; null if missing."),
                _c(
                    "amount_difference",
                    "decimal(18,2)",
                    "partner - pagoseguro (AMOUNT_MISMATCH only).",
                ),
                _c("age_days", "int", "Days from run_day to the day of the load."),
                _c("age_range", "string", "AGE_RANGES of shared/reconciliation.py."),
                _c("detected_at", "timestamp", "First time it was detected."),
                _c("resolved_at", "timestamp", "When treasury resolved it."),
            ),
        ),
        Table(
            name="fact_reconciliation_match",
            grain="one row per reconciled day and partner",
            partition="run_day",
            source=f"{RAW_RECONCILIATION}/fecha=<day>/matched.jsonl",
            owner="Yulianis (HU-52)",
            columns=(
                _c("run_day", "date", "Day reconciled (the partition)."),
                _c("partner", "string", "Partner (shared/reconciliation.py Partner)."),
                _c(
                    "matched",
                    "int",
                    "References that matched by amount and date (RN-10).",
                ),
            ),
        ),
        Table(
            name="dim_date",
            grain="one day",
            partition=None,
            source=f"the days of {CURATED_DECISIONS}",
            owner="Habith",
            columns=(
                _c("day", "date", "The day."),
                _c("year", "int", "Year."),
                _c("month", "int", "Month (1-12)."),
                _c("day_of_month", "int", "Day of the month (1-31)."),
                _c("weekday", "int", "ISO weekday: 1 Monday ... 7 Sunday."),
                _c("is_weekend", "boolean", "Saturday or Sunday."),
            ),
        ),
        Table(
            name="dim_rule",
            grain="one rule in one catalog version",
            partition=None,
            source="the rule catalog (shared/rule_catalog.py default_catalog(); "
            "published versions from GET /rules/versions/{n})",
            owner="Habith",
            columns=(
                _c("rule", "string", "Rule code."),
                _c("rule_version", "int", "rule_version of the entry."),
                _c("type", "string", "Rule type (RuleType)."),
                _c("action", "string", "What it decides when it fires."),
                _c("opens_case", "boolean", "Whether it opens a case."),
                _c("score", "int", "Score it adds to risk_score."),
                _c("enabled", "boolean", "Whether it is evaluated."),
                _c("rules_version", "string", "Catalog version."),
            ),
        ),
        Table(
            name="dim_partner",
            grain="one partner",
            partition=None,
            source="shared/reconciliation.py (Partner, PARTNER_UTC_OFFSET)",
            owner="Yulianis (HU-52)",
            columns=(
                _c("partner", "string", "Partner code."),
                _c("tx_types", "array<string>", "Transaction types it sees."),
                _c("channels", "array<string>", "Channels it sees."),
                _c("utc_offset", "int", "Hours from UTC of its files' dates."),
            ),
        ),
        Table(
            name="dim_device",
            grain="one device, 30-day window up to the day",
            partition="as_of",
            source=f"{CURATED_DECISIONS}/fecha=<day-29..day>, {RAW_CASES}",
            owner="Yulianis (HU-47)",
            columns=(
                _c("device_id", "string", "Device id."),
                _c("accounts_30d", "int", "Different accounts in 30 days (RN-04)."),
                _c("transactions_30d", "int", "Transactions in 30 days."),
                _c("held_or_rejected_30d", "int", "HOLD or REJECT in 30 days."),
                _c("cases_30d", "int", "Cases opened in 30 days."),
                _c("shared", "boolean", "accounts_30d > 3 (RN-04)."),
                _c(
                    "risk_level",
                    "string",
                    "LOW, MEDIUM or HIGH (rules in analytics-model.mdx).",
                ),
                _c("as_of", "date", "Last day of the window (the partition)."),
            ),
        ),
        Table(
            name="dim_merchant",
            grain="one merchant, 30-day window up to the day",
            partition="as_of",
            source=f"{CURATED_DECISIONS}/fecha=<day-29..day>, {RAW_LABELS}",
            owner="Habith",
            columns=(
                _c("merchant_id", "string", "Merchant id."),
                _c("transactions_30d", "int", "QR payments in 30 days."),
                _c("held_or_rejected_30d", "int", "HOLD or REJECT in 30 days."),
                _c("fraud_labeled_30d", "int", "Labeled as fraud in 30 days."),
                _c("as_of", "date", "Last day of the window (the partition)."),
            ),
        ),
        Table(
            name="rule_metrics",
            grain="one rule, label source and catalog version",
            partition=None,
            source=f"fact_decision, fact_label, fact_rule_hit, dim_rule; {RAW_METRICS}/kaggle (the replay, C5)",
            owner="Habith (HU-44, HU-45)",
            columns=(
                _c("rule", "string", "Rule code."),
                _c("rule_version", "int", "rule_version in the catalog replayed."),
                _c("rules_version", "string", "Catalog version replayed."),
                _c("label_source", "string", "LabelSource of the labels used."),
                _c("hits", "int", "Labeled transactions where the rule fired."),
                _c("true_positives", "int", "Fired and is_fraud."),
                _c("false_positives", "int", "Fired and not is_fraud."),
                _c("precision", _RATIO, "true_positives / hits; null when hits = 0."),
                _c(
                    "false_positive_rate",
                    _RATIO,
                    "false_positives / labeled legitimate transactions.",
                ),
            ),
        ),
        Table(
            name="pattern_coverage",
            grain="one fraud pattern, label source and catalog version",
            partition=None,
            source=f"fact_decision, fact_label, fact_rule_hit; {RAW_METRICS}/kaggle (the replay, C5)",
            owner="Habith (HU-46)",
            columns=(
                _c("pattern", "string", "Fraud pattern of the label."),
                _c("label_source", "string", "LabelSource of the labels used."),
                _c("rules_version", "string", "Catalog version replayed."),
                _c("frauds", "int", "Labeled frauds of the pattern."),
                _c("detected", "int", "HOLD, REJECT or opens_case."),
                _c("missed", "int", "frauds - detected."),
                _c("detection_rate", _RATIO, "detected / frauds; null when 0."),
                _c(
                    "detected_amount_usd",
                    "decimal(18,2)",
                    "USD amount of the detected frauds (RN-11).",
                ),
                _c(
                    "missed_amount_usd",
                    "decimal(18,2)",
                    "USD amount of the frauds that got through.",
                ),
                _c("top_rule", "string", "Rule that detects most of the pattern."),
                _c(
                    "expected",
                    "int",
                    "Frauds whose label names an expected_rule: the transaction "
                    "that completes the scheme, where the rule must act.",
                ),
                _c("expected_detected", "int", "Expected frauds detected."),
                _c(
                    "expected_detection_rate",
                    _RATIO,
                    "expected_detected / expected; null when 0.",
                ),
            ),
        ),
    )
}


def _spark_type(type_: str):
    from pyspark.sql import types as T

    if type_.startswith("decimal("):
        precision, scale = type_[len("decimal(") : -1].split(",")
        return T.DecimalType(int(precision), int(scale))
    if type_ == "array<string>":
        return T.ArrayType(T.StringType())
    return {
        "string": T.StringType(),
        "int": T.IntegerType(),
        "bigint": T.LongType(),
        "boolean": T.BooleanType(),
        "date": T.DateType(),
        "timestamp": T.TimestampType(),
    }[type_]


def spark_schema(table: str):
    """StructType of a table of TABLES (or "curated_decision"), in its
    column order. Every builder writes with it: nobody infers types."""
    from pyspark.sql import types as T

    t = CURATED_DECISION if table == CURATED_DECISION.name else TABLES[table]
    return T.StructType(
        [T.StructField(c.name, _spark_type(c.type), True) for c in t.columns]
    )
