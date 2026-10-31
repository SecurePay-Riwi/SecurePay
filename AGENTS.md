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
│   └── evidence.py         ← case evidence archive, archive() (used only by services/)
├── services/
│   ├── decision_engine/    ← FastAPI antifraud engine (rules in rules/, catalog in catalog.py)
│   ├── rules_api/           ← FastAPI rules management and catalog versioning
│   ├── cases_api/          ← FastAPI cases API for analysts (port 8003, Sprint 4)
│   ├── alerts/             ← alerts task: escalation, compliance summary, history purge
│   └── consumers/          ← SNS/SQS consumers and analytics
├── tests/                  ← end-to-end tests that run more than one service
│                             (test_rule_catalog_e2e.py: rules API + engine)
├── infra/                  ← LocalStack setup (init scripts create the SNS/SQS
│                             messaging, S3 buckets and the exchange-rates DynamoDB
│                             table; add the service to SERVICES in Compose), Docker Compose
│   └── terraform/          ← AWS infrastructure: modules/ (network, security_groups,
│                             iam, storage, database) and envs/dev; local state,
│                             never committed
├── doc-website/            ← Docusaurus documentation site
├── db/                     ← BACKUP only: now in securepay-seed
├── generators/             ← BACKUP only: now in securepay-generator
└── sources/                ← BACKUP only: now in securepay-csv and securepay-apis
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

`cache.py`, `events.py`, `rule_catalog.py`, `cases.py` and `evidence.py` are **not** part of the published package — they are only
used by `services/` and stay in this repo.

---

## Structure rules (mandatory)

Follow these rules for every change. If a change seems to need breaking one,
stop and ask instead of working around it.

1. `db/`, `generators/` and `sources/` are a **backup** from before the split.
   Never edit them: changes to a data source go to its own repository.
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

## Sprint state (as of 2026-10-31)

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

### Sprint 4 — In progress (Cases + Compliance)
"Step 0" put the case contract in the code first (`shared/cases.py`,
`services/cases_api/`, `services/alerts/`, `shared/evidence.py`,
`amount_usd` in the decision). HU-25 (cases consumer, closes HU-15's
case), HU-34 (restricted list reports) and HU-28 (30-day account
history) are merged; HU-29 (related accounts) is in review. Habith: HU-25 → HU-34 → HU-28 → HU-29;
Yulianis: HU-26 → HU-27 → HU-30, HU-35; Jorge: HU-57 → HU-31 → HU-32.

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
- Amounts are `Numeric` (decimal strings in JSON) and the case keeps the
  engine's `amount_usd`; no service outside the engine imports
  `currency.py`.

---

## Decision engine: rules and account history

Read this before adding or changing a rule in `services/decision_engine/`.

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
  never imports the API and the API never imports the engine.
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
  decision with `currency.to_usd()` (fixed 2026-10-01 rates until HU-42
  reads the `pagoseguro-exchange-rates` table). Convert history amounts
  with `currency.to_usd()` too.
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
  it, and the one being decided is one of them. By default `APPROVE`
  with `opens_case` (score 40). Thresholds: the catalog's `splitting`
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

---

## Local setup

```bash
git clone https://github.com/SecurePay-Riwi/SecurePay.git
git clone https://github.com/SecurePay-Riwi/securepay-seed.git   # side by side
cd SecurePay
cp .env.example .env   # fill in credentials; Compose PostgreSQL is port 5433
docker compose up -d
uv sync
(cd ../securepay-seed && cp .env.example .env && uv sync && uv run python -m securepay_seed.seed)
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
- Step by step (IAM user, access key, create, check, destroy): `doc-website/docs/getting-started/deploy-aws-terraform.mdx`.
- Before a PR: `terraform fmt -check -recursive` in `infra/terraform/` and `terraform validate` in `envs/dev`. The page `doc-website/docs/architecture/terraform.mdx` changes with the code.

## Docker images and local ecosystem (MAG-31 / MAG-32)

- Dockerfile builds the product image with Python 3.12 and uv; the same image runs the decision engine and consumers with different commands.
- docker-compose.yml orchestrates the local stack. Satellite repositories must be cloned beside this repository because Compose builds from sibling directories.
- Use service hostnames inside containers (postgres, valkey, localstack, decision-engine); localhost inside a container is not another service.
- The cases API (`cases-api`, port 8003), the `consumers` and the `alerts` task create the case tables at startup; all three need `DATABASE_URL`.
- Never commit .env, tokens, generated files or downloaded Kaggle datasets.
- The seed service uses SEED_RESET=true; do not run the stack against data that must be preserved.
- Valkey has no persistence in Compose on purpose: every run starts with empty idempotency keys and account history.
- When the engine reads a new environment variable, add it to the `decision-engine` service with `${VAR:-default}` as well as to `.env.example`.
