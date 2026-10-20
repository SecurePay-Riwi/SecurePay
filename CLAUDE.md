# CLAUDE.md — SecurePay Antifraude

Context file for AI assistants working on this project.
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
SecurePay/                  ← this repo (monorepo, stays here)
├── shared/                 ← cross-cutting library, published to PyPI as securepay-shared
│   ├── models.py           ← SQLAlchemy ORM: Usuario, Cuenta, Dispositivo, Comercio,
│   │                          DispositivoCuenta, ListaRestrictiva, Transaccion
│   ├── db.py               ← PostgreSQL engine + SessionLocal (psycopg3)
│   ├── config.py           ← DATABASE_URL, FECHA_REFERENCIA, CANALES, MONEDA_DECIMALES
│   ├── aws.py              ← boto3 client factory (LocalStack-aware via AWS_ENDPOINT_URL)
│   ├── cache.py            ← Valkey client (used only by services/)
│   └── events.py           ← transaction.decided event format (used only by services/)
├── services/
│   ├── decision_engine/    ← FastAPI antifraud engine (HU-05, HU-06, HU-07)
│   └── consumers/          ← SNS/SQS consumers and analytics
├── db/                     ← MOVED to securepay-seed repo
├── generators/             ← MOVED to securepay-generator repo
├── sources/                ← MOVED to securepay-csv and securepay-apis repos
├── infra/                  ← LocalStack setup, Docker Compose
└── doc-website/            ← Docusaurus documentation site
```

### Satellite repositories (SecurePay-Riwi org)

| Repo | Content | Data sources |
|------|---------|--------------|
| `securepay-csv` | `sources/csv_files/` | F1 PaySim, F2 Sparkov fraudTest, F5 partner statements |
| `securepay-apis` | `sources/apis/` | F6 Frankfurter exchange rates, F7 restricted list API |
| `securepay-seed` | `db/seed/` + `db/datasets/` | F4 seed DB |
| `securepay-generator` | `generators/` | F3 transaction stream |

Each satellite repo depends on `securepay-shared` (PyPI) — no need to clone this monorepo.

---

## Shared library

`shared/` lives here and is published to PyPI as `securepay-shared`.
**Do not duplicate its code** in satellite repos — add it as a dependency:

```toml
dependencies = ["securepay-shared>=0.1.0"]
```

`cache.py` and `events.py` are **not** part of the published package — they are only
used by `services/` and stay in this repo.

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

## Sprint state (as of 2026-10-20)

### Sprint 1 — Done ✅
- Seed + generator + Kaggle ETL + partner statements + exchange rates + restricted list API
- Decision engine skeleton + HU-05 (restricted list reject)
- LocalStack + Docker Compose
- Docusaurus doc site

### Docs milestone — Done ✅ (between sprints)
- `CLAUDE.md` — AI context file committed to monorepo (PR #29)
- `README.md` — updated with `securepay-shared` PyPI section + satellite repo table (PR #30)
- READMEs for all 4 satellite repos committed (PR #2 in each repo)
- Docusaurus updated: satellite repo badges on all component pages, multi-repo table in
  run-data-sources, intro.mdx section 6 rewritten, kaggle-datasets stale refs fixed (PR #32)

### Sprint 2 — In progress
| HU | Description | Owner | Status |
|----|-------------|-------|--------|
| HU-06 | Reject by restricted list (RN-06) | Jorge | ✅ Done |
| HU-07 | Rules with history (RN-02, RN-03) | Yulianis | 🔄 In progress |
| HU-08 | Velocity / mule / list pre-check in cache | Habith | 🔄 Starting |
| HU-09 | Docker images per component | Yulianis | 🔄 In progress |
| HU-10 | Docker Compose full stack | Unassigned | ⏳ Pending |

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

## Local setup

```bash
git clone https://github.com/SecurePay-Riwi/SecurePay.git
cd SecurePay
cp .env.example .env   # fill in credentials
docker compose up -d
uv sync
uv run pytest
```

---

## Key contacts

| Name | Role | GitHub |
|------|------|--------|
| Habith (Ing. Héctor de León) | Scrum Master | inghabith |
| Ann (Anndelgado) | Developer | Anndelgado |
| Jorge | Developer | — |
| Yulianis | Developer | — |
