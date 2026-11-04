# Analytics fixtures: 2026-10-05

One small day of the raw layer, built by `make_fixtures.py` with the
engine's own rules (the replay, the code default catalog with splitting
as `HOLD` + case, the fixed 2026-10-01 rates). The answer key of the six
views is `expected_views.json`, computed in plain Python from the
definitions in `doc-website/docs/reference/analytics-model.mdx`.

Do not edit these files without Habith: Habith's and Yulianis's tests
depend on them. To change the day, change `make_fixtures.py` and run

```bash
PYTHONPATH=. uv run python services/analytics/tests/fixtures/make_fixtures.py
```

## Files

| File | What it has |
| :--- | :--- |
| `raw/decisiones/fecha=2026-10-05/part-0001.jsonl`, `part-0002.jsonl` | 34 `transaction.decided` events: 33 of the day, 1 of 2026-10-04 23:50 that arrived after midnight (left out of the day), and 2 repeated lines (`n_topup_app`, `mule_out`) |
| `raw/decisiones/fecha=2026-10-06/part-0001.jsonl` | 1 event of 2026-10-05 23:58 that arrived the next day (it belongs to the day) |
| `raw/labels/fecha=2026-10-05/labels.jsonl` | The generator's format: 32 labeled transactions (19 fraud), 1 `kind: "security"` line and 1 repeated line with `"duplicate": true` |
| `raw/cases/fecha=2026-10-05/cases.jsonl`, `case_events.jsonl` | 5 cases as exported at 2026-10-06 01:00 UTC, with their 16 events |
| `raw/reconciliation/fecha=2026-10-05/differences.jsonl`, `runs.jsonl`, `matched.jsonl` | 6 differences of 3 runs (2026-09-25, 2026-10-01, 2026-10-05), the 3 runs, and what matched per run and partner (4, 3, 2 and 1: the run's 10) |
| `reference.json` | 18 accounts (4 currencies), 2 merchants, 2 listed documents: `ReferenceData.from_fixtures()` |
| `security_events.jsonl` | The device and password change of the account takeover |
| `expected_views.json` | The rows of q1 to q6 |

## The day (34 transactions, every type, currency, channel and decision)

| Transactions | What happens | Label |
| :--- | :--- | :--- |
| 8 normal: top-ups (APP, CORRESPONSAL, WEB), QR (EUR, COP), withdrawals (CAJERO JPY, CORRESPONSAL COP), P2P WEB | `APPROVE` | legitimate |
| `restricted_src` 09:00, P2P from a listed owner, on the shared device | `REJECT` + case (`restricted_list`) | RESTRICTED_LIST, fraud |
| `restricted_dst` 12:00, P2P to a listed owner | `REJECT` + case | RESTRICTED_LIST, fraud |
| `velocity_0..5` 10:00 to 10:05, six P2P from one account | the 6th `HOLD` (`velocity`); 5 missed | VELOCITY, fraud |
| `mule_in_0..2` 11:00 to 11:10 from three senders, `mule_out` 11:20 withdraws 95 % | `mule_out` `HOLD` + case (`mule`); 3 missed | MULE, fraud |
| `shared_1..4` 12:10 to 12:40, QR from 4 accounts on the device of `restricted_src` | `shared_3` and `shared_4` `APPROVE` with `shared_device` (score 30): false positives | SHARED_DEVICE, legitimate |
| `split_0..2` 13:00, 16:00, 20:00 (USD); `split2_0..2` 14:00, 17:00, 23:30 (EUR) | the third of each `HOLD` + case (`splitting`, score 40); 4 missed | SPLITTING, fraud |
| `takeover` 15:30, QR EUR 400 after a device and a password change | `HOLD` (`account_takeover`) | ACCOUNT_TAKEOVER, fraud |
| `default_ghost` 18:00, P2P from an account not in the cache, USD 10 | `APPROVE` by default (`default_timeout`) | not labeled |
| `default_merchant` 18:30, QR to a merchant not in the cache, USD 75 | `HOLD` by default | not labeled |
| `late_atm` 23:58, withdrawal JPY | `APPROVE` | legitimate |

## Cases (state at the export, 2026-10-06 01:00 UTC)

| Case of | State | Story |
| :--- | :--- | :--- |
| `restricted_src` | `RESOLVED` `FRAUD` → `REJECT` | assigned at 20 min, resolved at 90 min (within the SLA) |
| `restricted_dst` | `RESOLVED` `LEGITIMATE` → `APPROVE` | escalated at 243 min, assigned at 245, resolved at 250 (outside the SLA) |
| `mule_out` | `ESCALATED` | escalated at 243 min, nobody took it |
| `split_2` | `RESOLVED` `FRAUD` | assigned at 10 min, resolved at 30 min |
| `split2_2` | `OPEN` | created at 23:30, due at 03:30 |

Resolved cases have their `EVIDENCE_ARCHIVED` event and `evidence_key`.

## Reconciliation differences (age counted to 2026-10-05)

| Run day | Partner | Type | Status | Age range |
| :--- | :--- | :--- | :--- | :--- |
| 2026-10-05 | banco_andino | MISSING_IN_PARTNER (`n_topup_app`) | PENDING | 0-1 |
| 2026-10-05 | qr_pagos | AMOUNT_MISMATCH (`n_qr_eur`, +0.22) | PENDING | 0-1 |
| 2026-10-01 | cajeros_express | MISSING_IN_PAGOSEGURO | PENDING | 2-7 |
| 2026-10-01 | red_corresponsales | MISSING_IN_PARTNER | RESOLVED | 2-7 |
| 2026-09-25 | banco_andino | AMOUNT_MISMATCH (−1000.00) | PENDING | 8+ |
| 2026-09-25 | qr_pagos | MISSING_IN_PAGOSEGURO | PENDING | 8+ |

## Devices and merchants (q6)

The shared device has 5 accounts (`restricted_src` and `shared_1..4`), a
`REJECT` and a case: `HIGH`. Six more devices are `MEDIUM` (one account
each, with a `HOLD` or a case). The merchant of `n_qr_cop` and `takeover`
is `HIGH` (a fraud label and a `HOLD`); the one not in the cache is
`MEDIUM` (a default `HOLD`); the one of the shared device is `LOW`.
