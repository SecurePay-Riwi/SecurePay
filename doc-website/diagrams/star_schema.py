"""Star schema of the analytics lake: doc-website/static/img/analytics-star-schema.png.

Every table, key and column count comes from TABLES in shared/analytics.py
(the script fails if a key below is not a column there). Run from the
repository root (needs Node's Playwright and its Chromium):

    python3 doc-website/diagrams/star_schema.py

Change it when a table, a key or a join of the builders changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from common import FLOW, MUTED, Svg, render  # noqa: E402

from shared.analytics import TABLES  # noqa: E402

# One color per kind of table; the arrows take the color of the key.
KIND = {
    "fact": ("#2e5fa8", "#e8eef8"),
    "dim": ("#2e8a57", "#e7f4ec"),
    "aggregate": ("#7b4fc0", "#f0ebf9"),
}
FLOW["key"] = "#3d4a5c"
FLOW["logical"] = "#9aa4b4"

W, H = 1720, 1460
CARD_W = 330
ROW = 19
s = Svg(W, H)

# The rows each card shows: (marker, column, note). The markers are
# PK (the table's key), FK (points at a dimension or the central fact),
# PART (the partition column, fecha=<value>/) and M (a measure or
# attribute). The other columns are counted in the card's last line.
CARDS: dict[str, list[tuple[str, str, str]]] = {
    "fact_decision": [
        ("PK", "transaction_id", ""),
        ("FK", "day", "→ dim_date · fecha="),
        ("FK", "merchant_id", "→ dim_merchant"),
        ("FK", "device_id", "→ dim_device"),
        ("FK", "rules_version", "→ dim_rule"),
        ("M", "amount_usd", "decimal(18,2)"),
        ("M", "decision", "APPROVE / HOLD / REJECT"),
        ("M", "risk_score", "int"),
        ("M", "label_source", "generator / paysim / sparkov"),
    ],
    "fact_rule_hit": [
        ("FK", "transaction_id", "→ fact_decision"),
        ("FK", "rule", "→ dim_rule"),
        ("FK", "rule_version", "→ dim_rule"),
        ("PART", "day", "fecha="),
        ("M", "decision", ""),
        ("M", "score", "int"),
    ],
    "fact_label": [
        ("FK", "transaction_id", "→ fact_decision"),
        ("PART", "day", "fecha="),
        ("M", "source", "LabelSource"),
        ("M", "pattern", ""),
        ("M", "is_fraud", "boolean"),
        ("M", "expected_rule", ""),
    ],
    "fact_case": [
        ("PK", "case_id", ""),
        ("FK", "transaction_id", "→ fact_decision"),
        ("FK", "day", "→ dim_date · fecha="),
        ("M", "status", "OPEN / ESCALATED / RESOLVED"),
        ("M", "outcome", "FRAUD / LEGITIMATE"),
        ("M", "within_sla", "RN-09"),
        ("M", "amount_usd", "decimal(18,2)"),
    ],
    "fact_difference": [
        ("PK", "difference_id", ""),
        ("FK", "partner", "→ dim_partner"),
        ("FK", "run_day", "→ dim_date · fecha="),
        ("FK", "reference", "→ fact_decision (logical)"),
        ("M", "type", "MISSING_IN_* / AMOUNT_MISMATCH"),
        ("M", "amount_difference", "decimal(18,2)"),
        ("M", "age_range", ""),
    ],
    "fact_reconciliation_match": [
        ("FK", "partner", "→ dim_partner"),
        ("FK", "run_day", "→ dim_date · fecha="),
        ("M", "matched", "int (RN-10)"),
    ],
    "dim_date": [
        ("PK", "day", "date"),
        ("M", "year", ""),
        ("M", "month", ""),
        ("M", "weekday", "ISO 1-7"),
        ("M", "is_weekend", "boolean"),
    ],
    "dim_rule": [
        ("PK", "rule", ""),
        ("PK", "rule_version", ""),
        ("M", "rules_version", "catalog version"),
        ("M", "action", ""),
        ("M", "score", ""),
        ("M", "opens_case", "boolean"),
    ],
    "dim_device": [
        ("PK", "device_id", ""),
        ("PK", "as_of", "window end · fecha="),
        ("M", "accounts_30d", "RN-04"),
        ("M", "shared", "accounts_30d > 3"),
        ("M", "risk_level", "LOW / MEDIUM / HIGH"),
    ],
    "dim_merchant": [
        ("PK", "merchant_id", ""),
        ("PK", "as_of", "window end · fecha="),
        ("M", "transactions_30d", ""),
        ("M", "held_or_rejected_30d", ""),
        ("M", "fraud_labeled_30d", ""),
    ],
    "dim_partner": [
        ("PK", "partner", ""),
        ("M", "tx_types", "array<string>"),
        ("M", "channels", "array<string>"),
        ("M", "utc_offset", "int"),
    ],
    "rule_metrics": [
        ("FK", "rule", "→ dim_rule"),
        ("FK", "rule_version", "→ dim_rule"),
        ("M", "rules_version", ""),
        ("M", "label_source", ""),
        ("M", "precision", "decimal(9,4)"),
        ("M", "false_positive_rate", "decimal(9,4)"),
    ],
    "pattern_coverage": [
        ("M", "pattern", ""),
        ("M", "label_source", ""),
        ("M", "rules_version", ""),
        ("M", "detection_rate", "decimal(9,4)"),
        ("M", "missed_amount_usd", "decimal(18,2)"),
        ("FK", "top_rule", "→ dim_rule.rule"),
    ],
}

# Position of each card (x, y); the kind decides its color. The rows of
# fact_decision and dim_device line up so the device arrow is straight.
LAYOUT = {
    "dim_rule": (40, 110, "dim"),
    "dim_date": (760, 110, "dim"),
    "dim_merchant": (1350, 110, "dim"),
    "fact_rule_hit": (40, 362, "fact"),
    "fact_decision": (675, 362, "fact"),
    "dim_device": (1350, 419, "dim"),
    "fact_label": (40, 680, "fact"),
    "fact_case": (1350, 700, "fact"),
    "fact_difference": (40, 960, "fact"),
    "dim_partner": (695, 980, "dim"),
    "fact_reconciliation_match": (1350, 980, "fact"),
}
AGGREGATES = {"rule_metrics": (55, 1250), "pattern_coverage": (440, 1250)}

assert set(CARDS) == set(TABLES), set(CARDS) ^ set(TABLES)
for name, rows in CARDS.items():
    missing = {c for _, c, _ in rows} - set(TABLES[name].column_names)
    assert not missing, f"{name}: {missing} not in shared/analytics.py"


def height(name: str) -> float:
    return 40 + ROW * len(CARDS[name]) + 26


BOX: dict[str, tuple[float, float, float, float]] = {}


def card(name: str, x: float, y: float, kind: str, w: float = CARD_W) -> None:
    t = TABLES[name]
    stroke, fill = KIND[kind]
    h = height(name)
    BOX[name] = (x, y, w, h)
    s.add(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#ffffff" '
        f'stroke="{stroke}" stroke-width="1.6" filter="url(#shadow)"/>'
    )
    s.add(f'<rect x="{x}" y="{y}" width="{w}" height="34" rx="8" fill="{stroke}"/>')
    s.add(f'<rect x="{x}" y="{y + 26}" width="{w}" height="8" fill="{stroke}"/>')
    s.text(x + 12, y + 22, name, size=14, weight="bold", color="#ffffff")
    part = f"fecha={t.partition}" if t.partition else "one folder"
    s.text(x + w - 10, y + 22, part, size=10.5, color="#ffffff", anchor="end")
    for i, (marker, col, note) in enumerate(CARDS[name]):
        ry = y + 34 + 6 + ROW * i
        if i % 2:
            s.add(f'<rect x="{x + 1}" y="{ry}" width="{w - 2}" height="{ROW}" fill="{fill}"/>')
        if marker != "M":
            color = {"PK": "#b7791f", "FK": "#2e5fa8", "PART": "#5b6676"}[marker]
            s.add(f'<rect x="{x + 8}" y="{ry + 3}" width="34" height="13" rx="3" fill="{color}"/>')
            s.text(x + 25, ry + 13.5, marker, size=8.5, weight="bold", color="#ffffff", anchor="middle")
        s.text(x + 50, ry + 14, col, size=12, weight="bold" if marker in ("PK", "FK") else "normal")
        if note:
            s.text(x + w - 10, ry + 14, note, size=10.5, color=MUTED, anchor="end")
    shown = len(CARDS[name])
    rest = len(t.columns) - shown
    foot = f"{len(t.columns)} columns" + (f" ({rest} more in the dictionary)" if rest > 0 else "")
    s.text(x + 12, y + h - 9, foot, size=10, color=MUTED)


def edge(points, label="", at=0, logical=False, lx=0.0, ly=0.0):
    s.arrow(points, "logical" if logical else "key", label=label, at=at, dashed=logical, lx=lx, ly=ly)


# Title.
s.text(40, 46, "SecurePay · Analytics model (star schema)", size=24, weight="bold")
s.text(
    40,
    72,
    "13 Parquet tables in s3://<datalake>/analytics/<table>/[fecha=<day>/] · Glue catalog securepay_<env>_analytics · "
    "source of truth: TABLES in shared/analytics.py",
    size=12.5,
    color=MUTED,
)

for name, (x, y, kind) in LAYOUT.items():
    card(name, x, y, kind, w=370 if name == "fact_decision" else CARD_W)

# Aggregates: a box of their own at the bottom, no arrows (they are
# rebuilt from the facts, and rule_metrics names dim_rule's key).
ax, ay = AGGREGATES["rule_metrics"]
s.box(ax - 15, ay - 30, 2 * CARD_W + 85, height("rule_metrics") + 48, fill="none", stroke=KIND["aggregate"][0], rx=10, dash=True)
s.text(ax - 3, ay - 12, "Aggregates (HU-44 to HU-46): rebuilt from the facts every run + the Kaggle replay (C5)", size=11, weight="bold", color=KIND["aggregate"][0])
for name, (x, y) in AGGREGATES.items():
    card(name, x, y, "aggregate")


def side(name, where, d=0.0):
    x, y, w, h = BOX[name]
    return {
        "left": (x, y + h / 2 + d),
        "right": (x + w, y + h / 2 + d),
        "top": (x + w / 2 + d, y),
        "bottom": (x + w / 2 + d, y + h),
    }[where]


def row(name, column):
    """y of the middle of a column's row in a card."""
    x, y, w, h = BOX[name]
    i = [c for _, c, _ in CARDS[name]].index(column)
    return y + 40 + ROW * i + ROW / 2


fx, fy, fw, fh = BOX["fact_decision"]

# Central fact to its dimensions (arrow from the foreign key to the key).
dd = BOX["dim_date"]
edge([(dd[0] + dd[2] / 2, fy), (dd[0] + dd[2] / 2, dd[1] + dd[3])], "day")
rx_ = BOX["dim_rule"][0] + BOX["dim_rule"][2]
edge([(fx + 25, fy), (fx + 25, row("dim_rule", "rules_version")), (rx_, row("dim_rule", "rules_version"))], "rules_version", at=1)
my = row("fact_decision", "merchant_id")
edge([(fx + fw, my), (1260, my), (1260, row("dim_merchant", "merchant_id")), (1350, row("dim_merchant", "merchant_id"))], "merchant_id + day = as_of", at=1)
dy_ = row("fact_decision", "device_id")
edge([(fx + fw, dy_), (1350, dy_)], "device_id + day = as_of", ly=16, lx=10)

# Facts around the central one, all toward transaction_id.
ty = row("fact_decision", "transaction_id")
edge([(BOX["fact_rule_hit"][0] + CARD_W, ty), (fx, ty)], "transaction_id", ly=-14)
rh = BOX["fact_rule_hit"]
edge([(rh[0] + CARD_W / 2, rh[1]), (rh[0] + CARD_W / 2, BOX["dim_rule"][1] + BOX["dim_rule"][3])], "rule, rule_version")
ly_ = row("fact_label", "transaction_id")
edge([(BOX["fact_label"][0] + CARD_W, ly_), (fx + 60, ly_), (fx + 60, fy + fh)], "transaction_id", at=0)
cy_ = row("fact_case", "transaction_id")
edge([(1350, cy_), (fx + fw - 50, cy_), (fx + fw - 50, fy + fh)], "transaction_id", at=0)

# Reconciliation.
edge([(BOX["fact_difference"][0] + CARD_W, row("fact_difference", "partner")), (695, row("dim_partner", "partner"))], "partner")
edge([(1350, row("fact_reconciliation_match", "partner")), (695 + CARD_W, row("dim_partner", "partner"))], "partner")
fd = BOX["fact_difference"]
edge([(fd[0] + 260, fd[1]), (fd[0] + 260, 920), (fx + fw / 2, 920), (fx + fw / 2, fy + fh)], "reference = transaction_id (logical)", at=1, logical=True)

# Legend.
lx0, ly0 = 830, 1222
s.box(lx0, ly0, 850, 210, fill="#e9eef6", stroke="#cdd6e3", rx=8)
s.text(lx0 + 16, ly0 + 26, "How to read it", size=13, weight="bold")
for i, (color, text) in enumerate([(KIND["fact"][0], "Fact"), (KIND["dim"][0], "Dimension"), (KIND["aggregate"][0], "Aggregate")]):
    xx = lx0 + 16 + i * 130
    s.add(f'<rect x="{xx}" y="{ly0 + 42}" width="16" height="16" rx="3" fill="{color}"/>')
    s.text(xx + 22, ly0 + 55, text, size=12)
for i, (color, m, text) in enumerate(
    [
        ("#b7791f", "PK", "key of the table"),
        ("#2e5fa8", "FK", "points at another table"),
        ("#5b6676", "PART", "partition column (fecha=)"),
    ]
):
    xx = lx0 + 16 + i * 270
    s.add(f'<rect x="{xx}" y="{ly0 + 75}" width="34" height="14" rx="3" fill="{color}"/>')
    s.text(xx + 17, ly0 + 86, m, size=8.5, weight="bold", color="#ffffff", anchor="middle")
    s.text(xx + 42, ly0 + 87, text, size=12)
s.add(f'<line x1="{lx0 + 16}" y1="{ly0 + 113}" x2="{lx0 + 46}" y2="{ly0 + 113}" stroke="{FLOW["key"]}" stroke-width="2.4"/>')
s.text(lx0 + 54, ly0 + 117, "join of the builders and views; the arrow points at the key", size=12)
s.add(f'<line x1="{lx0 + 16}" y1="{ly0 + 138}" x2="{lx0 + 46}" y2="{ly0 + 138}" stroke="{FLOW["logical"]}" stroke-width="2.4" stroke-dasharray="7 5"/>')
s.text(lx0 + 54, ly0 + 142, "logical link, no join (a MISSING_IN_PAGOSEGURO has no decision)", size=12)
s.text(lx0 + 16, ly0 + 170, "Every day and run_day joins dim_date.day (the cards say → dim_date).", size=12, weight="bold")
s.text(lx0 + 16, ly0 + 192, "Power BI reads only the views q1..q6 (D6), which Athena builds over these tables.", size=12, color=MUTED)

if __name__ == "__main__":
    out_path = ROOT / "doc-website" / "static" / "img" / "analytics-star-schema.png"
    render(s.svg(), out_path)
    print(out_path)
