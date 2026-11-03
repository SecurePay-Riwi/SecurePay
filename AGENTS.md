# AGENTS.md — SecurePay Antifraude

Context file for AI assistants working on this project (`CLAUDE.md` points here).
Read this before touching any code.

---

## Project overview

**PagoSeguro Antifraude** is a transactional monitoring platform for a fictional
digital wallet with 2.3 M users, processing 1.8 M daily transactions in 4 currencies
(COP, USD, EUR, JPY). The platform evaluates every transaction against versioned
antifraud rules and returns APPROVE / HOLD / REJECT in ≤ 200 ms.

This is a **Riwi academic project** (Proyecto 05 de 10). The team is 4 students.
All decisions — architecture, infrastructure, costs — are the team's responsibility
and must be justified in writing.

---

## Repository layout

```
SecurePay/                  ← this repo: the product (engine, consumers, infra, docs)
├── shared/                 ← cross-cutting library, published to PyPI as securepay-shared
│   ├── models.py           ← SQLAlchemy ORM: Usuario, Cuenta, Dispositivo, Comercio,
│   │                          DispositivoCuenta, ListaRestrictiva, Transaccion
│   ├── db.py               ← PostgreSQL engine + SessionLocal (psycopg3)
│   ├── config.py           ← DATABASE_URL, FECHA_REFERENCIA, CANALES, MONEDA_DECIMALES
│   ├── aws.py              ← boto3 client factory (LocalStack-aware via AWS_ENDPOINT_URL)
│   ├── cache.py            ← Valkey client (used only by services/)
│   ├── events.py           ← transaction.decided event format (used only by services/)
│   ├── rule_catalog.py     ← rule catalog models and defaults (used only by services/)
│   ├── cases.py            ← case tables, states and create_schema() (used only by services/)
│   ├── evidence.py         ← case evidence archive, archive() (used only by services/)
│   ├── reconciliation.py   ← reconciliation records, tables and create_schema() (used only by services/)
│   ├── analytics.py        ← analytics lake layers, paths and the dimensional model TABLES (used only by services/)
│   └── refdata.py          ← cache keys of accounts, merchants and the restricted list (used only by services/)
├── services/
│   ├── decision_engine/    ← FastAPI antifraud engine (rules in rules/, catalog in catalog.py)
│   ├── rules_api/           ← FastAPI rules management and catalog versioning
│   ├── cases_api/          ← FastAPI cases API for analysts (port 8003, Sprint 4)
│   ├── alerts/             ← alerts task: escalation, compliance summary, history purge
│   ├── reconciliation/     ← nightly reconciliation: ingest, match (Spark), store (Sprint 5)
│   ├── cache_loader/       ← loads accounts, merchants and the restricted list into Valkey (HU-67)
│   ├── analytics/          ← analytics ETL (Spark), views q1..q6, labels, replay and metrics (Sprint 6)
│   └── consumers/          ← SNS/SQS consumers and analytics
├── tests/                  ← end-to-end tests that run more than one service
│                             (test_rule_catalog_e2e.py: rules API + engine)
│                             (test_reconciliation_e2e.py: ingest + match + store)
├── infra/                  ← spark/ (build of the reconciliation's Spark job), LocalStack setup (init scripts create the SNS/SQS
│                             messaging, S3 buckets and the exchange-rates DynamoDB
│                             table; add the service to SERVICES in Compose), Docker Compose
│   └── terraform/          ← AWS infrastructure: modules/ (network, security_groups,
│                             iam, storage, database, ecr, cache, ecs, messaging,
│                             lambdas) and envs/dev; local state,
│                             never committed
└── doc-website/            ← Docusaurus documentation site
```

### Satellite repositories (SecurePay-Riwi org)

| Repo | Package | Data sources | Run |
|------|---------|--------------|-----|
| `securepay-seed` | `src/securepay_seed/` (+ `kaggle_etl/`) | F4 seed DB | `uv run python -m securepay_seed.seed` |
| `securepay-generator` | `src/securepay_generator/` | F3 transaction stream | `uv run python -m securepay_generator` |
| `securepay-csv` | `src/securepay_csv/` (`kaggle_datasets/`, `partner_statements/`) | F1 PaySim, F2 Sparkov fraudTest, F5 partner statements | `uv run python -m securepay_csv.partner_statements` |
| `securepay-apis` | `src/securepay_apis/` (`restricted_list/`, `exchange_rates/`) | F6 Frankfurter exchange rates, F7 restricted list API | `uv run uvicorn securepay_apis.restricted_list.main:app --port 8001` |

Each satellite repo depends on `securepay-shared` (PyPI) and has its own
`AGENTS.md`. The repos are cloned side by side in the same folder and exchange
files, never imports: each one finds the others' output in `../securepay-<repo>/`.

---

## Shared library

`shared/` lives here and is published to PyPI as `securepay-shared`.
**Do not duplicate its code** in satellite repos — add it as a dependency:

```toml
dependencies = ["securepay-shared>=0.1.0"]
```

`cache.py`, `events.py`, `rule_catalog.py`, `cases.py`, `evidence.py`, `reconciliation.py`, `analytics.py` and `refdata.py` are **not** part of the published package — they are only
used by `services/` and stay in this repo.

---

## Structure rules (mandatory)

Follow these rules for every change. If a change seems to need breaking one,
stop and ask instead of working around it.

1. Data source code lives in its own repository (`securepay-seed`,
   `securepay-generator`, `securepay-csv`, `securepay-apis`). Never add it
   back here: changes to a data source go to its repository.
2. New product code goes under `services/<component>/` (one folder per piece
   that is deployed on its own), with its tests in `services/<component>/tests/`.
3. Code shared by the services lives in `shared/`. What the source repos also
   need is published as `securepay-shared`; do not copy it into another repo.
4. This repo never imports code from a source repository, and they never import
   from it. Data moves through files, HTTP or S3.
5. Dependencies only with uv; commit `pyproject.toml` and `uv.lock` together.
6. When a command, variable, folder or repository changes, update `README.md`,
   the Docusaurus pages in `doc-website/docs/` and this file in the same change.
7. The engine's Swagger docs live in `services/decision_engine/docs/` (one file
   per group of endpoints: summaries, descriptions, examples of every status
   code); only the field descriptions stay in `schemas.py`. When an endpoint,
   status code or response field changes, update `docs/` and the Docusaurus
   page together; `test_openapi.py` checks the documented status codes and
   that the examples are valid.

---

## Data sources (F1–F7)

| ID | Name | Type | Where |
|----|------|------|-------|
| F1 | PaySim | CSV Kaggle (`alaxi/paysim1`) | securepay-csv |
| F2 | Sparkov fraudTest | CSV Kaggle (`kartik2112/fraud-detection`) | securepay-csv |
| F3 | Simulated transaction stream | Generator | securepay-generator |
| F4 | Users / accounts / devices DB | Seed | securepay-seed |
| F5 | Partner payment statements | CSV/TXT fixed-width | securepay-csv |
| F6 | Exchange rates | Frankfurter public API | securepay-apis |
| F7 | Restricted list (PEP/sanctions) | Simulated REST API | securepay-apis |

> **F2 note:** The original enunciado specified `mlg-ulb/creditcardfraud` (`creditcard.csv`).
> The team replaced it with `kartik2112/fraud-detection` (`fraudTest.csv`) after agreement
> with the professor. Anonymous V1..V28 columns cannot support real antifraud rules.
> This change was introduced in PR #20 (Ann / Anndelgado).

---

## Business rules (RN-01 to RN-12)

| ID | Rule |
|----|------|
| RN-01 | Every transaction gets APPROVE/HOLD/REJECT in ≤ 200 ms. Default: APPROVE if < USD 50, HOLD if ≥ USD 50. |
| RN-02 | Velocity: > 5 outgoing transfers in 10 min from same account → HOLD |
| RN-03 | Mule: account receives ≥ 3 transfers from different senders and withdraws ≥ 80% in < 30 min → HOLD + case |
| RN-04 | Shared device: device linked to > 3 accounts in 30 days raises risk score for all |
| RN-05 | Splitting: ≥ 3 transactions from same account in 24 h each below daily limit, sum exceeds it → compliance case |
| RN-06 | Document on restricted list → REJECT + immediate compliance report |
| RN-07 | Device change + password change + transaction > USD 200 in < 1 hour → HOLD (account takeover) |
| RN-08 | Rules are versioned; every decision records which rule version was active |
| RN-09 | HOLD case must be resolved in ≤ 4 hours; otherwise auto-escalated to supervisor |
| RN-10 | Reconciliation: match by reference id, amount (±0.01) and date (±1 day) |
| RN-11 | Amounts reported in USD at the day's exchange rate; original currency also stored |
| RN-12 | Case evidence retained 10 years, immutable |

---

## Sprint state (as of 2026-11-03)

### Sprint 1 — Done ✅
- Seed + generator + Kaggle ETL + partner statements + exchange rates + restricted list API
- Decision engine skeleton + restricted list reject
- LocalStack + Docker Compose
- Docusaurus doc site

### Sprint 2 — Done ✅ (Jira numbering)
| HU | Description | Owner | PR |
|----|-------------|-------|----|
| HU-10 | APPROVE / HOLD / REJECT decision | Jorge | #36 |
| HU-11, HU-12 | Account history, velocity (RN-02) | Jorge | #37 |
| HU-13 | Mule account (RN-03) | Habith | #40 |
| HU-16 | Restricted list reject (RN-06) | Habith | — |
| HU-18 | Default decision on timeout (RN-01) | Habith | #39 |
| HU-33 | Restricted list checked for every party | Yulianis | #42 |
| HU-63, HU-64 | Docker images, full stack with one command | Yulianis | #43 |

### Sprint 3 — Closed ✅ (9/10; HU-15 moved to Sprint 4 for its case, with HU-25)
"Step 0" (PR #49) put the rule catalog in the code first.

| HU | Jira | Description | Owner | PR |
|----|------|-------------|-------|----|
| HU-19 → HU-22 | MAG-133..136 | Rules API, change without redeploy, enable/disable, versioning | Yulianis | #56 |
| HU-55 → HU-56 | MAG-138, MAG-139 | AWS with Terraform: network, IAM, SGs; S3, RDS, costs v1 | Jorge | #54, #55 |
| HU-17 | MAG-132 | Account takeover (RN-07) | Jorge | #51 |
| HU-14, HU-15 | MAG-129, MAG-131 | Shared device (RN-04), splitting (RN-05) | Habith | #52, #53 |
| HU-23 | MAG-137 | Rule version per decision | Habith | #57 |

### Sprint 4 — Closed ✅ (Cases + Compliance)
"Step 0" (PR #60) put the case contract in the code first (`shared/cases.py`,
`services/cases_api/`, `services/alerts/`, `shared/evidence.py`,
`amount_usd` in the decision). Every story is merged in `main`.

| HU | Jira | Description | Owner | PR |
|----|------|-------------|-------|----|
| HU-25 (closes HU-15's case) | MAG-181 | Cases consumer: a decision with `opens_case` opens a case | Habith | #60, #61 |
| HU-34 | MAG-189 | Restricted list reports (RN-06) | Habith | #62 |
| HU-28 | MAG-184 | 30-day account history | Habith | #63 |
| HU-29 | MAG-185 | Accounts related through a device | Habith | #64 |
| HU-26, HU-27, HU-30 | MAG-182, MAG-183, MAG-186 | Case inbox, assignment and resolution | Yulianis | #68 |
| HU-35 | MAG-190 | Suspicious operations report | Yulianis | #69 |
| HU-57 | MAG-191 | Engine on ECR and ECS/Fargate (with `VALKEY_CLUSTER`) | Jorge | #65, #66 |
| HU-32 | MAG-188 | Immutable case evidence (RN-12) | Jorge | #67 |
| HU-31 | MAG-187 | Escalation after 4 hours (RN-09), code and local run | Jorge | #71 |
| — | — | Windows and full-stack test fixes | Jorge | #70 |

### Sprint 5 — In progress (Reconciliation + FX + CI/CD)
"Step 0" puts the reconciliation contract in the code first
(`shared/reconciliation.py`, `services/reconciliation/` with the fixture day,
the empty `routes_reconciliation.py`, `usd_rate` and `rate_date` in the
decision, the cache keys of HU-67 in `reference_data.py`). HU-24, HU-66 and
HU-58 moved to Sprint 6. Backlog: `doc-website/docs/product-backlog/sprint-backlog-5.mdx`.

| HU | Jira | Description | Owner |
|----|------|-------------|-------|
| HU-67 | MAG-352 | Load the restricted list and the account data into the cache; when it closes, remove the temporary `engine_reads_database` rule (`sg-engine` → `sg-rds`) of HU-57 | Habith |
| HU-37 | MAG-237 | Reconcile by reference, amount and date (Spark) | Habith |
| HU-42, HU-43 | MAG-242, MAG-243 | Exchange rate of the day; keep the original amount, USD and the rate used | Habith |
| HU-38 → HU-41 | MAG-238..241 | Missing at the partner, missing at PagoSeguro, amount differences; pending differences and age | Yulianis |
| HU-68 | MAG-351 | Deploy the consumers and the alerts task as Lambdas (the AWS part of HU-31: EventBridge every 5 minutes, `business-alerts` e-mails filtered by `audience`, S3 permissions for the evidence) | Jorge |
| HU-36 | MAG-236 | Read the partners' daily files; nightly orchestration (Step Functions at 02:00 Bogotá) | Jorge |
| HU-65 | MAG-246 | Application CI/CD pipeline | Jorge |

### Sprint 6 — In progress (Analytics + Closure)
"Step 0" (PR #91) puts the analytics
contract in the code first: `shared/analytics.py` (C1, C2),
`services/analytics/` (ETL, the decisions' builder, view `q1`, the empty
builders and export of Yulianis, labels, replay and metrics), the fixture
day, `history.use_backend()` and `reference_data.use_source()`, splitting
to `HOLD` + case (D2) and `new_differences` in the reconciliation (D8).
Plan: https://claude.ai/artifact/Xz8cuN9u3epB5Nyt5QXqBY.

| HU | Jira | Description | Owner | PR |
|----|------|-------------|-------|----|
| HU-44, HU-45, HU-46 | MAG-296..298 | Precision, false positives (view q2) and fraud detected vs missed (view q3) per rule | Habith | #92 |
| HU-24 | MAG-245 | Simulate a rule version over the history | Habith | #93 |
| HU-51, HU-52, HU-47 | MAG-303, MAG-304, MAG-299 | Cases (q4), reconciliation (q5), device risk | Yulianis | — |
| HU-48 → HU-50, HU-53 | MAG-300..302, MAG-305 | Power BI pages (q1, q2, q3, q6) | Yulianis | — |
| HU-66, HU-58 | MAG-247, MAG-244 | Data CI/CD; EKS vs Fargate | Jorge | — |
| HU-59, HU-60, HU-61 | MAG-306..308 | Metrics and alarms; load test; final costs and runbook | Jorge | — |

---

## Analytics (Sprint 6)

Read this before touching `shared/analytics.py` or `services/analytics/`.
Pages: `doc-website/docs/components/analytics.mdx` and
`doc-website/docs/reference/analytics-model.mdx` (the data dictionary).

- **One shape.** `shared/analytics.py` holds the layer paths (`RAW_*`,
  `CURATED_DECISIONS`, `ANALYTICS`, `layer_path()`, `table_path()`),
  `LabelSource`, `Column`/`Table`, `TABLES` (every table of the model,
  nothing else), `CURATED_DECISION` and `spark_schema()`. Nobody else
  defines tables, columns or types; a new column is a small PR on this
  file with its row on `analytics-model.mdx`
  (`shared/tests/test_analytics_contract.py` checks both).
- **Builders:** `build(spark, day, raw, output) -> {table: rows}`, one line
  each in `etl.BUILDERS` (decisions first). They write with
  `services/analytics/spark.py` (`write()` applies the schema and replaces
  the day's `fecha=<day>/` folder; `read()`), so a day can run again.
  Spark reads and writes local folders, and `s3://` only on Glue; raw
  `s3://` (LocalStack) is read through `services/reconciliation/storage.py`.
  pyspark is imported inside the functions.
- **Curated:** the events of `raw/decisiones/fecha=<day-1..day+1>` whose
  `transaction_date` (UTC) is the day, the first of each `transaction_id`
  (earliest `processed_at`). `fact_rule_hit` takes decision and score from
  `dim_rule` by `(rule, rule_version)`.
- **Views (C3):** `sql/q<N>_<name>.sql` is an Athena `CREATE OR REPLACE
  VIEW`, `sql/control/q<N>.sql` the same numbers another way; SQL that
  runs in Trino and Spark. `test_views.py` has one case per view against
  `tests/fixtures/expected_views.json`.
- **Replay (C5):** `replay.replay(snapshot, transactions, reference,
  security_events=())` calls `decision_service._decide` inside
  `history.use_backend(InMemoryHistory())` and
  `reference_data.use_source(ReferenceData)` (context variables; the
  engine always uses Valkey). Nobody outside `services/analytics/` imports
  it (the rules API only in its simulation route, HU-24).
- **Metrics (HU-44 to HU-46):** the definitions exist twice, like the
  match: `metrics.py` in Python over a replay (`rule_metrics(decisions,
  labels, snapshot)`, `pattern_coverage()`, `false_positive_examples()`)
  and `build_metrics.py` in Spark over the lake (the last builder:
  `fact_decision` + `fact_label` + `fact_rule_hit` + `dim_rule`, every
  day, rebuilt each run), plus the Kaggle replay's rows in
  `raw/metrics/kaggle/` (`python -m services.analytics.metrics
  --kaggle`). Views `q2`/`q3` show the latest catalog version per label
  source. `metrics.py` imports the replay only inside functions: the
  ETL does not need the engine.
- **Simulation (HU-24):** `simulate.py` replays one day (plus
  `WARMUP_DAYS` before it, from `raw/decisiones` in plain Python, or the
  Kaggle rows) with the current catalog and a candidate and compares
  them (`changed`, `changes`, `released_usd`, `examples`). The rules API
  runs it in `POST /rules/simulations` through
  `services/rules_api/simulation.py` (imports inside the function, the
  only analytics import of the API); one day only (`422` for a range),
  never writes rules, versions or Valkey.
- **Labels (C4):** the generator's `generated/instance-<n>/labels.jsonl`
  is copied to `raw/labels/fecha=<day>/` (`python -m
  services.analytics.labels`). Kaggle rows: `transacciones` has no dataset
  column; `labels.kaggle_source()` uses the `kaggle_paysim_` /
  `kaggle_fraudtest_` pattern, else the seed's id
  (`uuid5(SEED_NAMESPACE, "hist:fraudtest:<row>")`).
- **Fixtures:** `services/analytics/tests/fixtures/` is one day
  (2026-10-05) built by `make_fixtures.py` with the engine's rules; do not
  edit them without Habith. Its `README.md` lists the day.

---

## Cases (Sprint 4)

Read this before touching `shared/cases.py`, `services/cases_api/`,
`services/alerts/` or the cases and history consumers. Page:
`doc-website/docs/components/cases.mdx`.

- **One shape, three writers.** `shared/cases.py` holds the tables
  (`cases`, `case_events`, `compliance_reports`, `account_transactions`),
  the enums (`CaseStatus`, `CaseOutcome`, `CaseEventType`), `PENDING`,
  `SYSTEM_ACTOR`, `CASE_DUE_MINUTES`, `ACCOUNT_HISTORY_DAYS`,
  `main_account()` and `create_schema(session)`. Nobody else defines
  columns or states; a new column is its own small PR on this file.
  The consumers create cases and history, the cases API assigns and
  resolves, the alerts task escalates and purges. No service imports
  another, and the consumers never call the API over HTTP.
- **Only `opens_case` opens a case** (D1, team decision 2026-10-13), one
  per `transaction_id` (`ON CONFLICT DO NOTHING`), with `due_at =
  created_at + CASE_DUE_MINUTES` on the consumer's clock.
- **The cases consumer** (`services/consumers/cases.py`, HU-25) checks
  each event in Python before writing (`case_values()`), so a broken one
  fails alone in `batchItemFailures`; then one session and one commit per
  batch, and `CREATED` only when the insert returned an id. If PostgreSQL
  fails, every message that opens a case goes back to the queue. Its
  tests point `cases.SessionLocal` at an isolated schema. A split that
  goes on opens one case per transaction; nothing groups them.
- **Restricted list reports (HU-34, RN-06):** when `restricted_list`
  fired, the cases consumer writes, in the case's transaction, one
  `compliance_reports` row per listed owner of the source or destination
  account (`listed_documents()`: only the digits, as the engine), `ON
  CONFLICT (transaction_id, document) DO NOTHING`. No case, no report.
  `compliance_summary.send_summary()` sends the ones with `notified_at`
  null in one SNS message to `BUSINESS_ALERTS_TOPIC` (a name or an ARN)
  with `audience = "compliance"`, and sets `notified_at`.
  `GET /compliance/restricted-list-reports` reads them.
- **States:** `OPEN` → `ESCALATED` (only the alerts task) → `RESOLVED`,
  or `OPEN` → `RESOLVED`. `RESOLVED` is final (`409`). Resolving sets
  `final_decision`: `FRAUD` → `REJECT`, `LEGITIMATE` → `APPROVE` (D4).
- **Every transition writes one `CaseEvent`** in the same transaction as
  the change; `case_events` is append-only (trigger). Actor: `X-User`,
  or `SYSTEM_ACTOR`.
- **Escalation is the alerts task every 5 minutes** (D2), not a timer per
  case. `services/alerts/handler.handler()` runs
  `escalation.escalate_overdue`, `compliance_summary.send_summary` and
  `account_history.purge` with one `now`, each in its own try. Locally,
  `python -m services.alerts` loops every `ALERTS_INTERVAL_SECONDS`.
- **Escalation (HU-31, RN-09):** `escalate_overdue()` takes up to 100
  `OPEN` cases with `due_at <= now` (most overdue first, `FOR UPDATE SKIP
  LOCKED`), sets `ESCALATED`, `escalated_at` and the `ESCALATED` event,
  and publishes ONE summary with `audience = "supervisor"` BEFORE the
  commit (contract v2, 2026-11-01): SNS down → rollback, the cases stay
  `OPEN` for the next run. Its tests: `test_escalation.py`. Locally,
  `CASE_DUE_MINUTES=2` shows it in minutes (the text says the limit with
  `limit_text()`). Times in the summary and the event go through `_utc()`:
  PostgreSQL returns `timestamptz` in the session's time zone.
- **`services/alerts/notify.py`** is the only SNS code of the alerts jobs:
  `TOPIC` (`BUSINESS_ALERTS_TOPIC`), `topic_arn()` and
  `publish(subject, body, audience)`. `escalation.py` and
  `compliance_summary.py` use it; tests replace `notify._client` and
  reset `notify._topic_arn`.
- **The 30-day account history is PostgreSQL `account_transactions`**
  (D3), not DynamoDB. The history consumer (`services/consumers/history.py`,
  HU-28) writes one row per account of every event, whatever the
  decision: `OUT` for the source, `IN` for the destination (a top-up has
  only `IN`, a QR payment or withdrawal only `OUT`), `ON CONFLICT
  (transaction_id, account_id) DO NOTHING`, checked in Python first
  (`history_rows()`) and one commit per batch, like the cases consumer.
  `device_id` only on the main account's row (HU-29 reads it).
  `GET /accounts/{account_id}/transactions?days=` reads it by
  `transaction_date`, and `account_history.purge()` deletes what is older
  than `now - ACCOUNT_HISTORY_DAYS`.
- **Related accounts (HU-29)** are a query on the same table, no new
  one: `GET /accounts/{account_id}/related-accounts?days=` takes the
  account's `device_id`s in the window and the other accounts with rows
  on them in the window; one item per (account, device) with
  `last_seen` and `open_cases` (cases in `PENDING`).
- **The suspicious operations report (HU-35)** is
  `GET /reports/suspicious?from=&to=&format=json|csv` in
  `routes_reports.py`: the cases with `created_at` in the period (both
  days inclusive, UTC, at most 31), oldest first, `pattern` =
  `rules_triggered` joined by `+`. Every case counts as a compliance case
  (D1). An empty period is an empty list with `message` (JSON) or only
  the header (CSV); amounts are written with `format(value, "f")`.
- **`shared/evidence.archive(session, case)`** never raises and is
  idempotent. The cases API calls it after resolving; the alerts task
  retries it with `archive_pending(session)`. One JSON per case at
  `cases/<yyyy>/<mm>/<case_id>.json`, written once (`IfNoneMatch="*"`)
  with COMPLIANCE Object Lock, `StorageClass=GLACIER_IR` (no lifecycle
  rule: S3 does not transition objects under 128 KB) and a SHA-256
  checksum. `EVIDENCE_RETENTION_DAYS` is a decimal: never run code that
  archives against an AWS bucket with 3650 outside prod, the lock can
  never be shortened (dev uses `0.0035`).
- **The cases API** works like the rules API: routes in
  `routes_cases.py`, `routes_reports.py`, `routes_accounts.py`,
  `routes_compliance.py` (one owner each), session and `X-User` from
  `deps.py`, models in `schemas.py`, Swagger in `docs.py`, checked by
  `tests/test_openapi.py`. Tests run in their own schema
  (`shared/tests/isolated_db.py`, `deps.bind()`).
- **The analyst's routes** (`routes_cases.py`, HU-26, HU-27, HU-30):
  `GET /cases` lists `PENDING` by default, ordered by `risk_score` desc,
  then `due_at` (RN-09), with `minutes_left` (rounded down, negative when
  overdue, null when resolved). Assigning and resolving lock the row
  (`get_case(..., for_update=True)`), refuse `RESOLVED` with `409`
  (`ensure_pending()`) and write the case and its event in one commit
  (`assign()`, `resolve()`). Resolving calls `evidence.archive()` after
  the commit; tests replace it with monkeypatch on `shared.evidence`.
- Amounts are `Numeric` (decimal strings in JSON) and the case keeps the
  engine's `amount_usd`; no service outside the engine imports
  `currency.py`.
- **Original amount, USD and the rate used (HU-43, RN-11):** `cases` and
  `account_transactions` also keep `usd_rate` and `rate_date`, copied by
  the consumers from the event with `rate_values()` (null before HU-42;
  a malformed one fails that event alone). `create_schema()` adds the two
  columns to an older database (`ADDED_COLUMNS`). The API answers each
  amount with its currency's decimals (`in_currency()`, JPY none) and
  `usd_rate` without trailing zeros (`plain_rate()`), through
  `CurrencyDecimals` in `schemas.py`. Reports use the stored
  `amount_usd`, never convert again. The suspicious CSV adds `usd_rate`
  and `rate_date` as its last columns.

---

## Reconciliation (Sprint 5)

Read this before touching `shared/reconciliation.py`,
`services/reconciliation/` or `routes_reconciliation.py`. Page:
`doc-website/docs/components/reconciliation.mdx`.

- **Four steps, one owner each, one shape.** `shared/reconciliation.py`
  holds `Partner`, `partner_for()`, `partner_day()`, `PARTNER_UTC_OFFSET`,
  the dataclasses `StatementRecord`, `RejectedRow` and `MatchRow`,
  `to_json()` / `record_from_json()` / `match_row_from_json()` (the only
  serialization: decimal strings, UTC ISO times, `YYYY-MM-DD` days), the
  enums `MatchStatus`, `DifferenceType`, `DifferenceStatus`, `RunStatus`,
  `AGE_RANGES`, `AMOUNT_TOLERANCE` (0.01), `DATE_TOLERANCE_DAYS` (1), the
  tables `reconciliation_runs` and `reconciliation_differences` and
  `create_schema(session)`. Nobody else defines columns, types or states.
- **Steps** (signatures of contract C2): `ingest.read_day()` / `run()` /
  `handler()` (HU-36) write `curated/extractos/fecha=<day>/records.jsonl`
  and `rejects.jsonl`; `match.reconcile(spark, ...)` (HU-37) writes
  `curated/conciliacion/fecha=<day>/part-*.json`; `store.load_rows()` /
  `classify()` / `save()` / `handler()` (HU-38 to HU-40) write the
  differences. Paths under `RECON_DATA_DIR` locally, `s3://<datalake>` in
  AWS; read and write them with `services/reconciliation/storage.py`.
- **Match rules (RN-10, D3):** PagoSeguro's side is `APPROVE`, not `P2P`,
  once per transaction id, `partner_day()` == the day, read from
  `raw/decisiones/fecha=<day-1..day+1>`. DATE_OFF (dates more than 1 day
  apart) is checked before AMOUNT_OFF; both limits are included.
  `match.reconcile()` is PySpark (HU-37): `match.session()` is local[*]
  in tests and Compose, the job's on AWS Glue 6.0 (`infra/spark/match_job.py`
  runs `match.main --day --records --decisions --output`). Spark reads
  and writes local folders, and `s3://` only on Glue; in local mode
  `s3://` (LocalStack) goes through `storage.py`. Output keeps nulls
  (`ignoreNullFields=false`), one `part-*.json` per day, replaced on a
  re-run. `match.match_day()` is the plain-Python reference: the Spark
  tests run every edge case on both. pyspark is imported inside the
  Spark functions only. Spark tests skip without Java (17 or later).
- **D4:** `DATE_OFF` gives one `MISSING_IN_PARTNER` and one
  `MISSING_IN_PAGOSEGURO`. A difference is unique per (`run_day`,
  `partner`, `type`, `reference`) and inserted with `ON CONFLICT DO
  NOTHING`: a repeated run neither duplicates nor reopens it. `RESOLVED`
  is final.
- **Orchestration:** `python -m services.reconciliation --day` (or
  `--from --to`) runs ingest → match → store; the run is `RUNNING` at the
  start and `FAILED` with `"<step>: <error>"` if a step fails. In AWS:
  Step Functions at 02:00 Bogotá (Jorge, HU-36).
- **Fixtures:** `services/reconciliation/tests/fixtures/` is one small
  day (2026-10-05) with every status and defect, the expected output of
  ingest and match and the answer key (`extracts_report.json`). Test
  against them; do not edit them without Habith (three people's tests
  depend on them). Its `README.md` lists the day.
- **Treasury's routes** are in the cases API (`routes_reconciliation.py`,
  Yulianis; `GET /reconciliation/runs?from=&to=` is Habith's, HU-37, at
  the end of the file), which also creates the tables at startup.
- **Differences and treasury (HU-38 to HU-41, Yulianis):**
  `store.classify()` is pure (no database); `save()` is one session and
  one commit, upserts the run of the day (creating it when nobody marked
  it `RUNNING`) and keeps the first `detected_at`; it returns
  `differences` (all of the day) and `new_differences` (rows inserted by
  this run, `RETURNING`; the treasury e-mail says "Differences of the
  day: X (new: Y)", sprint 6 D8); `handler()` creates
  the tables on its first call and reads `match_dir(RECON_DATA_DIR, day)`
  (yesterday in Bogotá without `day`). Routes: `GET
  /reconciliation/differences` (`PENDING` by default, by `run_day` then
  partner; `type`, `partner`, `status`, `from`, `to`; `size` up to 200),
  `GET /reconciliation/differences/aging` (always the three
  `AGE_RANGES`, with `by_type`) and `POST
  /reconciliation/differences/{id}/resolution` (`note` and `X-User`, row
  locked, `409` once `RESOLVED`). `age_days` counts from `run_day` to
  today in UTC (`routes_reconciliation.today()`, pinned in the tests);
  amounts keep their currency's decimals (`in_currency()`). Tests:
  `test_store.py` (against the answer key) and
  `test_reconciliation_differences.py`.
- **Reading the files (HU-36):** the readers of the four formats are in
  `services/reconciliation/parsers.py` (`READERS`, one class per partner);
  never import `securepay-csv`. A bad line raises `LineError` with its
  English reason and becomes a `RejectedRow`; the rest of the file is still
  read. The control record is checked against every detail line and the sum
  of the readable amounts (in the partner's units); a mismatch is one
  `RejectedRow` on the control line and the records still count. A missing
  file is a `RejectedRow` with `line_number = 0`. Tests:
  `tests/test_ingest.py`.
- `pyspark` is in the `spark` dependency group (default for `uv sync`),
  pinned to 4.1.x: AWS Glue 6.0 runs Spark 4.1.1 with
  Python 3.13, so never use an API newer than 4.1. The Docker image
  leaves it out (`--no-default-groups`).

## Decision engine: rules and account history

Read this before adding or changing a rule in `services/decision_engine/`.

- **The engine never reads PostgreSQL** (HU-67, contract C5). Accounts,
  merchants and the restricted list come from Valkey through
  `reference_data.py`: `get_account()` (`acct:<id>` hash: `currency`,
  `user_id`, `document` digits only, `status`), `merchant_exists()`
  (`merch:<id>`) and `on_restricted_list()` (`{restricted}:docs`, `None`
  when `{restricted}:loaded_at` is missing); a Valkey error is
  `CacheUnavailable`. Key names live in `shared/refdata.py`.
  `services/cache_loader/` (`python -m services.cache_loader`, or
  `handler()` as a daily Lambda) writes them from PostgreSQL: hashes with
  a pipeline without transaction and `REFDATA_TTL_HOURS` (48) renewed by
  every load, the list into `{restricted}:docs:next` and `RENAME` over
  `{restricted}:docs`. D2: an account or merchant missing in the cache,
  or `CacheUnavailable`, gets RN-01's default decision (`by_default`);
  the list not loaded with its rule enabled → `HOLD` whatever the
  amount; `422` only for a currency that is not the account's. The
  engine's tests load the cache from the seed once per run
  (`tests/conftest.py`); `test_reference_data.py` checks that the engine
  does not import `shared.db`. No session reaches `_decide()` or
  `RuleContext`.

- **Rules are configured by the catalog, not by code or variables**
  (RF-03, RN-08, CA-06). `shared/rule_catalog.py` holds the models
  (`RuleEntry`, `CatalogSnapshot`, one `*Params` model per rule type) and
  `DEFAULT_RULES`; the engine and the rules API share it. It is not part of
  the published `securepay-shared` package.
- **Each rule is a module in `services/decision_engine/rules/`** with
  `TYPE` (a `RuleType`) and `evaluate(ctx, rule) -> TriggeredRule | None`,
  registered with one line in `rules/__init__.py` (`REGISTRY`). It reads
  its thresholds from `rule.typed_params()` (never `os.getenv` or module
  constants) and returns `hit(rule, reason)`: decision, `opens_case` and
  `score` come from the catalog entry. If it needs a new piece of data,
  add one field or lazy property to `RuleContext` (`rules/base.py`).
  `evaluate_rules()` runs every enabled entry in catalog order;
  `choose_decision()` picks the most severe one (`REJECT`, then `HOLD`,
  else `APPROVE`). Add `tests/test_rule_<type>.py` with unit tests that
  build `RuleContext` and `RuleEntry` by hand, and a case in
  `tests/test_decision_outcomes.py` for a new decision combination.
- **`catalog.current()`** is read once per decision; the rules, the
  default decision and `rules_version` (the catalog version, `"0"` for the
  code defaults) all use that snapshot. It keeps the last valid snapshot
  in memory and, at most every `RULES_REFRESH_SECONDS` (1), reads
  `{rules}:version` from Valkey, and `{rules}:catalog` only when the
  version changed. It never raises: if Valkey fails or the new catalog is
  invalid it keeps the last valid one (the code defaults until one loads).
- **The rules API (`services/rules_api/`) owns the catalog.** PostgreSQL
  is the truth: `rules` (current state) and `rule_catalog_versions`
  (one row per change with the whole snapshot, append-only by trigger).
  Each write takes an advisory lock, so versions never repeat. After the
  commit it publishes `{rules}:catalog` and `{rules}:version` in one
  script that never replaces a newer version; at startup it publishes
  the latest again (Valkey has no persistence in Compose). The engine
  never imports the API; the API reaches the engine's rule code only
  through the simulation route (`simulation.py` → `services.analytics`,
  contract C5).
- **Account history lives in Valkey and is shared by every rule**
  (`history.py`). Do not create another per-rule key:
  - `out:{account}`: what leaves the account (`P2P`, `QR`, `RETIRO`),
    member `id|type|amount`, kept 24 h (`HISTORY_OUT_HOURS`).
    `record_outgoing()` writes it and returns the whole outgoing history.
  - `in:{account}`: `P2P` received, member `id|sender_account|amount`, kept 60 min
    (`HISTORY_IN_MINUTES`). `record_incoming()` writes it; `incoming()`
    reads it. **The mule rule (HU-13) reads incoming transfers from here.**
  - `dev:{device}`: the accounts that used a device, member `account_id`
    scored by the last time it was seen, kept 30 days
    (`HISTORY_DEVICE_DAYS`). `record_device()` writes the main account
    (source; in a top-up, destination) on every transaction and returns
    the set, which reaches the rules as `RuleContext.device_accounts`.
  - `sec:{account}`: device and password changes from
    `POST /security-events` (`security_events.py`), member
    `id|type|device_id`, scored by `event_date`, kept 60 min
    (`HISTORY_SECURITY_MINUTES`). Read by the account takeover rule.
  - Recharges are not recorded. Attempts count whatever the decision: the
    history is written before deciding (team decision, 2026-10-21).
  - One key per Lua script: ElastiCache Serverless may put two keys on
    different nodes. Write every history key through `history.record()`.
- **Amounts in the history are in the account's currency, not USD.**
  `RuleContext.amount_usd` is the transaction in USD, computed once per
  decision at the rate of the transaction's day (HU-42, below), the
  `RuleContext.rate`. Convert history amounts with
  `currency.convert(amount, ctx.rate)`, so one decision uses one rate.
- **Exchange rate of the day (HU-42, RN-11).** `currency.py` loads the
  whole `pagoseguro-exchange-rates` table (`RATES_TABLE`, about 30 items)
  into memory at startup (`currency.start()` in the lifespan) and reloads
  it every `RATES_REFRESH_SECONDS` in a background thread: a decision
  never calls DynamoDB. `rate_for(currency, day)` gives a `Rate`
  (`per_usd`, `rate_date`, `fallback`); the day is `transaction_date` in
  UTC (`utc_day()`); a day without a rate uses the last earlier one
  (`fallback`, logged once per day); no earlier day, an empty table or
  DynamoDB down at startup use the fixed 2026-10-01 `RATES_PER_USD`
  with a warning; a failed reload keeps the last table. USD is 1. The
  decision carries `usd_rate` and `rate_date`. Tests use the fixed rates
  (conftest) unless they call `currency.load()`.
- Rule names in `rules_triggered` are English snake_case (`restricted_list`,
  `velocity`); they are part of the `transaction.decided` event, so keep
  them stable. New code in this folder is in English.
- Velocity counts only `P2P` (QR payments to merchants and withdrawals do
  not count: the rule says "outgoing transfers").
- Mule account (`rules/mule.py`, HU-13) runs only on a `RETIRO`: 3 or more
  different senders in `in:{account}` in the 30 min before it, and the
  withdrawal is 80 % or more of `source_balance_before` (the core's
  balance; the engine keeps none). Thresholds: the catalog's `mule` entry.
- Shared device (`rules/shared_device.py`, HU-14) runs on every
  transaction: more than 3 different accounts in `dev:{device}` in the
  last 30 days. By default `APPROVE` with score 30: it raises
  `risk_score`, it does not hold. Thresholds: the catalog's
  `shared_device` entry.
- Splitting (`rules/splitting.py`, HU-15) reads `out:{account}`: 3 or
  more outgoing transactions (`P2P`, `QR`, `RETIRO`) in 24 h, each below
  USD 10000 (converted with `currency.to_usd()`), adding up to more than
  it, and the one being decided is one of them. By default `HOLD`
  with `opens_case` (score 40; `APPROVE` until sprint 5, changed by
  decision D2 of sprint 6). Thresholds: the catalog's `splitting`
  entry.
- Account takeover (`rules/account_takeover.py`, HU-17) runs on `P2P`, `QR`
  and `RETIRO` above USD 200: a `DEVICE_CHANGE` and a `PASSWORD_CHANGE` in
  `sec:{account}` in the 60 minutes before the transaction. Events dated
  after the transaction do not count.
- **A decision records the versions that decided it** (RN-08, HU-23):
  `rules_version` (the catalog version) and `rule_versions` (code →
  `rule_version` of each rule in `rules_triggered`; the default decision
  records `default_timeout`'s). `TriggeredRule.rule_version` comes from
  `hit()`. The stored decision and the `transaction.decided` event carry
  both, and `GET /rules/versions/{n}` of the rules API shows the catalog
  that decided. Adding a decision field: optional, with a default in
  `TransactionResponse`, without raising `EVENT_VERSION`.
- **A decision says whether it opens a case** (`opens_case`): true when a
  rule whose catalog entry has `opens_case` fired, by default
  `restricted_list`, `mule` and `splitting` (team decision 2026-10-13). The engine does not create cases: the cases consumer (HU-25)
  reads the flag from the `transaction.decided` event. `risk_score` is the
  sum of the fired rules' `score`, at most 100.
- **A decision carries `amount_usd`** (RN-11, Sprint 4 step 0): the
  transaction in USD, the same `currency.to_usd()` value the rules use,
  as a decimal string. The cases and the account history read it from
  the event.

---

## Conventions

- **Language:** code, comments, commit messages and PRs in **English** from now on.
  (Existing Spanish code/comments stay — only update when editing that file.)
- **Commits:** conventional commits (`feat:`, `fix:`, `chore:`, `docs:`)
- **PRs:** opened by Claude only when explicitly asked by Habith (Scrum Master)
- **No `Co-Authored-By` line** in commits
- **uv** for all Python dependency management (not pip directly)
- **Reference date:** `FECHA_REFERENCIA = 2026-10-01` — used by seed and generator
  to keep runs reproducible regardless of actual date

---

## Git workflow (commits, branches, pull requests)

Team conventions, based on the guides the professor shared. They apply to
every repository in the SecurePay-Riwi organization.

- **Commits:** `type(scope): description` (Conventional Commits). Types:
  `feat`, `fix`, `perf`, `build`, `ci`, `docs`, `refactor`, `style`, `test`,
  `chore`. The scope is the component or the Jira ticket (`feat(MAG-31): ...`).
  Imperative mood ("add", not "added"), no final period, title of 50
  characters or less; extra context goes in the body. Reference issues with
  `closes #12`. No `Co-Authored-By` lines.
- **Branches:** `type/TICKET-short-description`, lowercase with hyphens:
  `feature/`, `bugfix/`, `hotfix/`, `refactor/`, `test/`, `doc/`
  (for example `feature/MAG-123-mule-rule`). Branches that already exist
  keep their names.
- **Pull requests:** small (ideally under 10 files and a few hundred lines),
  opened as Draft while in progress, with at least one other team member as
  reviewer, preferably merged with "Squash and merge", and the branch deleted after the
  merge. The PR title follows the commit format.
- **PR description:** GitHub fills it from the organization template
  ([`SecurePay-Riwi/.github/pull_request_template.md`](https://github.com/SecurePay-Riwi/.github/blob/main/pull_request_template.md)).
  When you write a PR body yourself (an AI agent, or `gh pr create --body`),
  follow the same sections: Context (with the Jira ticket), Type of change,
  Before / After, How and why, Missing, How to test (the exact commands, the
  folder or service they run in and the expected result) and Checklist.
- **Before opening a PR:** `uv run ruff format .`, `uv run ruff check .` and
  `uv run pytest`. The CI
  (`.github/workflows/ci.yml`: jobs `lint`, `secret-scan`, `tests`, `image`, `terraform`)
  runs the same on the PR and must be green to merge. Do not add per-file
  ruff ignores for someone else's code; fix it or ask.
- **Source repositories:** each has its own `.github/workflows/ci.yml`
  (`lint`, `secret-scan`, `tests`, no deploy) with SecurePay's ruff rules;
  run `uv run ruff format .`, `uv run ruff check .` and `uv run pytest`
  there before a PR.

---

## Local setup

```bash
git clone https://github.com/SecurePay-Riwi/SecurePay.git
git clone https://github.com/SecurePay-Riwi/securepay-seed.git   # side by side
cd SecurePay
cp .env.example .env   # DATABASE_URL: 5432 installed PostgreSQL (default), 5433 Compose's
docker compose up -d
uv sync
(cd ../securepay-seed && cp .env.example .env && uv sync && uv run python -m securepay_seed.seed)
uv run ruff format .
uv run ruff check .
uv run pytest
```

---

## Key contacts

| Name | Role | GitHub |
|------|------|--------|
| Habith (Ing. Héctor de León) | Scrum Master | inghabith |
| Ann (Anndelgado) | Developer | Anndelgado |
| Jorge | Developer | Envy528 |
| Yulianis | Developer | — |

## Where to read more

Read these before changing the design, not to work on the code:

- Architecture overview: https://securepay-riwi.github.io/SecurePay/docs/architecture/overview
- Decisions (ADRs): https://securepay-riwi.github.io/SecurePay/docs/architecture/decisions
- Team decisions: https://securepay-riwi.github.io/SecurePay/docs/architecture/team-decisions
- Open questions: https://securepay-riwi.github.io/SecurePay/docs/architecture/open-questions
- Data flow: https://securepay-riwi.github.io/SecurePay/docs/architecture/data-flow
- Logbook: https://securepay-riwi.github.io/SecurePay/docs/logbook
- Run the data sources: https://securepay-riwi.github.io/SecurePay/docs/getting-started/run-data-sources

## AWS infrastructure (Terraform, MAG-138)

- `infra/terraform/` implements `doc-website/docs/architecture/infrastructure.mdx` and `security.mdx`; it does not redesign them. AWS names are English, `securepay-<env>-<resource>` (the design pages still show the old Spanish names; the mapping is in `terraform.mdx`); bucket names end with the account id. Tags `project`, `environment`, `owner`, `managed_by` through `default_tags`, region `us-east-2`.
- Run everything from `infra/terraform/envs/dev`: `terraform init`, `plan`, `apply`, and `destroy` after every test (the NAT Gateways and RDS cost money even idle). Dev is disposable on purpose: `force_destroy` buckets, RDS without deletion protection or final snapshot, no default Object Lock retention (test objects are uploaded with a 5-minute retain-until date), USD 5 budget that counts usage paid with credits.
- State and `terraform.tfvars` are local and ignored by git; the state holds the RDS passwords, so it is never shared, and apply/destroy always run from the same computer. Credentials come from the AWS profile, never from files; the IAM user needs `PowerUserAccess` plus `infra/terraform/terraform-user-policy.json`. Commit `.terraform.lock.hcl`.
- Step by step (IAM user, access key, create, check, push the images, deploy the engine, destroy): `doc-website/docs/getting-started/deploy-aws-terraform.mdx`.
- Engine on Fargate (MAG-191): images in ECR tagged with the short git commit (immutable tags, never only `latest`); the engine service and the admin task exist only once `engine_image_tag` / `admin_image_tag` are set. The admin task is the `securepay-seed` image and seeds RDS on demand (`terraform output -raw admin_run_task_command`). The load balancer listens on 443 with a self-signed certificate unless `domain_name` is set.
- ElastiCache Serverless only accepts cluster-protocol clients: `shared/cache.py` uses `valkey.ValkeyCluster` when `VALKEY_CLUSTER=true` (set by Terraform in AWS; false locally). New Valkey code must keep one key per command, or keys sharing a hash tag like `{rules}`.
- The engine never reaches RDS (HU-67): `sg-engine` has no 5432 rule and the engine task gets no `DATABASE_URL`. Accounts, merchants and the restricted list reach it through the cache, loaded once a day (06:00 UTC) by the `list-loader` Lambda (`services.cache_loader.loader.handler`, in `modules/lambdas`); after an `apply` that creates the Lambdas, invoke it once by hand or the engine answers with default decisions. Exchange rates: DynamoDB `securepay-<env>-exchange-rates` (`modules/storage`), name passed to the engine in `RATES_TABLE`. The temporary `engine_reads_database` variable was removed in MAG-356.
- Consumers and alerts task as Lambdas (HU-68, MAG-351): `modules/messaging` (topics `decisions`, `business-alerts`, `ops-alarms`; queues `cases`, `history`, `analytics` with DLQs after 5 attempts; DLQ alarms) and `modules/lambdas` (created once `lambda_image_tag` is set). Every Lambda runs the engine image with `entry_point = ["python", "-m", "awslambdaric"]` and the existing handler as command; there is no Lambda-only code. **A Lambda is named like its role in `modules/iam`** (`securepay-<env>-cases-consumer`, `-history-consumer`, `-analytics-consumer`, `-alerts`, later `-list-loader`, `-statement-reader`, `-difference-writer`). The cases, history and alerts handlers create the case tables on their first write (`batch.ensure_schema()`, `handler.ensure_schema()`): Lambda has no startup step. Temporary in dev: those Lambdas get the master user's `DATABASE_URL` as an environment variable; one database user per component is pending. Push images with `docker build --provenance=false` (Lambda rejects image indexes).
- Nightly reconciliation (HU-36, MAG-236): `modules/reconciliation` (AWS Glue 6.0 job `-reconciliation-match` = Spark 4.1.1 + Python 3.13, because EMR is not available on AWS's free account plan, the state machine `-reconciliation` ingest → Spark `.sync` → store → SNS `audience = treasury`, `TimeoutSeconds` 4 h 30 min, Scheduler 07:00 UTC, the 06:30 check and the failure alarm). Terraform zips `services/reconciliation` and `shared` (without tests, `archive_file`) for `--extra-py-files` and uploads `infra/spark/match_job.py` as the script; `match_job.py` keeps `--day --records --decisions --output` out of Glue's own arguments and calls `match.main`. Glue brings boto3; what else `match.py` imports goes in `python_modules` of the module (`--additional-python-modules`) at the versions of `uv.lock`, and `services/reconciliation/tests/test_glue_job.py` fails if they differ. The job runs with the `glue-jobs` role. The 06:30 check is `services/alerts/reconciliation_check.py`, run by the alerts handler with `{"job": "reconciliation_check"}`; it publishes to `OPS_ALARMS_TOPIC`.
- Exchange-rates Lambda (HU-42, MAG-359): the only Lambda that does **not** run the engine image. `securepay-<env>-exchange-rates` runs securepay-apis' image (ECR `securepay-<env>-apis`) with `securepay_apis.exchange_rates.handler.handler`, outside the VPC, in its own resources in `modules/lambdas/exchange_rates.tf` (created once `apis_image_tag` is set; daily at 16:00 UTC = 11:00 Bogotá). securepay-apis deploys it with its own `deploy.yml` and the role `securepay-<env>-deploy-apis` (`source_deployers` in `modules/iam`: one role per data-source repository, which may only push its image and update its Lambdas); SecurePay's `deploy.yml` and role do not touch it. A data-source repository that needs its own deploy (the seed, for example) adds one entry to `source_deployers`.
- Before a PR: `terraform fmt -check -recursive` in `infra/terraform/` and `terraform validate` in `envs/dev`. The page `doc-website/docs/architecture/terraform.mdx` changes with the code.

## Docker images and local ecosystem (MAG-31 / MAG-32)

- Dockerfile builds the product image with Python 3.12 and uv; the same image runs the decision engine and consumers with different commands. It installs only the main dependencies (`--no-default-groups`): no pytest, no pyspark.
- docker-compose.yml orchestrates the local stack. Satellite repositories must be cloned beside this repository because Compose builds from sibling directories.
- Use service hostnames inside containers (postgres, valkey, localstack, decision-engine); localhost inside a container is not another service.
- Which PostgreSQL: the containers always use Compose's (`postgres:5432` inside the network). What runs on your machine with `uv run` (pytest, the seed) uses `DATABASE_URL` from `.env`: port 5432 for an installed PostgreSQL (the `.env.example` default) or 5433 for Compose's. With both installed, pytest talks to the one in `DATABASE_URL`, not to the one the stack writes to.
- The cases API (`cases-api`, port 8003), the `consumers` and the `alerts` task create the case tables at startup; all three need `DATABASE_URL`.
- `cache-loader` runs once after the seed and fills Valkey with accounts, merchants and the restricted list; the `decision-engine` waits for it and has no `DATABASE_URL`. Valkey has no persistence: after restarting it, run `docker compose up cache-loader` again (or `uv run python -m services.cache_loader`).
- Tests that need "PostgreSQL down" use `shared/tests/isolated_db.down_sessions()` (it sets `connect_timeout`; on Windows port 1 waits forever without it). Tests against LocalStack create queues of their own subscribed to the topic: the Compose `consumers` container reads the real ones.
- Never commit .env, tokens, generated files or downloaded Kaggle datasets.
- The seed service uses SEED_RESET=true; do not run the stack against data that must be preserved.
- Valkey has no persistence in Compose on purpose: every run starts with empty idempotency keys and account history.
- When the engine reads a new environment variable, add it to the `decision-engine` service with `${VAR:-default}` as well as to `.env.example`.
