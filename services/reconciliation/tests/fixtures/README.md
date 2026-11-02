# Reconciliation fixtures: one small day (2026-10-05)

Hand-made so every step can test against the same day without running the
generator, the engine or the step before it. Do not edit them by hand: a
change here changes what three people's tests expect. Ask Habith.

| Folder / file | What it is | Used by |
| :--- | :--- | :--- |
| `extractos/<partner>/fecha=2026-10-05/` | The four partners' files, in their formats (see `doc-website/docs/components/partner-statements.mdx`) | ingest (HU-36) |
| `decisiones/fecha=2026-10-0{4,5,6}/` | `transaction.decided` events as the analytics consumer writes them in `raw/decisiones/` (JSON Lines) | match (HU-37) |
| `curated/extractos/fecha=2026-10-05/records.jsonl`, `rejects.jsonl` | What `ingest.run()` must write for the day (`to_json`) | ingest's expected output, match's input |
| `curated/conciliacion/fecha=2026-10-05/part-00000.json` | What `match.reconcile()` must write (one `MatchRow` per reference) | match's expected output, store's input (HU-38 to HU-40) |
| `extracts_report.json` | The answer key: files, defects, `expected_differences` and `expected_run` (counts) | store, the end-to-end test |

The rejection `reason` texts in `rejects.jsonl` are an example; compare
partner, file and line, not the wording.

## The day, transaction by transaction

| Tx | Partner | What | Match status | Difference |
| :--- | :--- | :--- | :--- | :--- |
| B1 | banco_andino | Top-up, in v1 and v2 | MATCHED | — |
| B2 | banco_andino | Missing in v1, restored by v2 | MATCHED | — |
| B3 | banco_andino | Rounded in v1 (89.00), v2 writes `88.910` (read as 88.91) | MATCHED | — |
| B4 | banco_andino | HOLD: not in the file and not counted | — | — |
| — | banco_andino | v1's control does not add up; v1 is not read (v2 is the latest) | — | — |
| R1 | red_corresponsales | Top-up | MATCHED | — |
| R2 | red_corresponsales | Withdrawal at 23:30 Bogota on the 5th = 04:30 UTC on the 6th (raw `fecha=2026-10-06`) | MATCHED | — |
| R3 | red_corresponsales | Ours, not in the file | ONLY_PAGOSEGURO | MISSING_IN_PARTNER |
| C1 | cajeros_express | COP 123456.78, the partner writes 123457,00 | AMOUNT_OFF | AMOUNT_MISMATCH |
| C2 | cajeros_express | Withdrawal; its event is twice in raw (counted once) | MATCHED | — |
| C3 | cajeros_express | Ours on 2026-10-04 03:10 UTC, the partner dates it 2026-10-06 01:00 UTC | DATE_OFF | MISSING_IN_PARTNER + MISSING_IN_PAGOSEGURO (D4) |
| C4 | cajeros_express | REJECT: not counted | — | — |
| C5 | cajeros_express | Its line has amount `N/A`: rejected row, so it is ours only | ONLY_PAGOSEGURO | MISSING_IN_PARTNER |
| — | cajeros_express | Control declares total 124627,00 (the detail adds up to 123627,00): rejected row, the file is still read | — | — |
| Q1 | qr_pagos | JPY 1500, no decimals | MATCHED | — |
| Q2 | qr_pagos | USD 10.00, the partner writes 1001 minor units (10.01): exactly the tolerance | MATCHED | — |
| Q3 | qr_pagos | The partner reports it, we do not have it | ONLY_PARTNER | MISSING_IN_PAGOSEGURO |
| Q4 | qr_pagos | APPROVE of the 6th (raw `fecha=2026-10-06`): another day, not counted | — | — |
| P1 | — | P2P: no partner sees it | — | — |

Expected run: 4 files read, 11 records, 2 rejected rows, 13 match rows, 8
matched, 6 differences.
