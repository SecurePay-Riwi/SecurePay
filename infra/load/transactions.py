"""The transactions of the load test (HU-60), without Locust, so the
tests can check that every one is a valid request.

Made from accounts.json (the seed's active accounts and merchants): P2P,
QR, RECARGA and RETIRO in the proportions of MIX, each in the currency of
the account that pays (or receives, in a top-up), with a new id each.
"""

import json
import random
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

DATA = json.loads(
    (Path(__file__).resolve().parent / "accounts.json").read_text(encoding="utf-8")
)
# Share of each type, roughly the generator's (P2P is most of the traffic).
MIX = {"P2P": 60, "QR": 25, "RECARGA": 10, "RETIRO": 5}
CHANNEL = {"P2P": "APP", "QR": "APP", "RECARGA": "APP", "RETIRO": "CAJERO"}
# A typical amount in each currency (about USD 5 to 80), and its decimals.
AMOUNT = {"USD": (5, 80, 2), "EUR": (5, 70, 2), "COP": (20000, 300000, 0)}
AMOUNT["JPY"] = (700, 12000, 0)


def money(value: Decimal, decimals: int) -> str:
    return str(value.quantize(Decimal(1).scaleb(-decimals)))


def transaction(rng: random.Random, now: datetime) -> dict:
    """One valid request: the accounts the type needs, the amount in the
    currency of the account that pays (or receives, in a top-up)."""
    kind = rng.choices(list(MIX), weights=list(MIX.values()))[0]
    source, destination = rng.sample(DATA["accounts"], 2)
    payer = destination if kind == "RECARGA" else source
    low, high, decimals = AMOUNT[payer["currency"]]
    amount = Decimal(rng.uniform(low, high))
    balance = amount * 20

    body = {
        "id": str(uuid.uuid4()),
        "type": kind,
        "channel": CHANNEL[kind],
        "source_account_id": None,
        "destination_account_id": None,
        "merchant_id": None,
        "amount": money(amount, decimals),
        "currency": payer["currency"],
        "device_id": str(uuid.uuid5(uuid.NAMESPACE_URL, payer["id"])),
        "transaction_date": now.isoformat(),
    }
    if kind != "RECARGA":
        body["source_account_id"] = source["id"]
        body["source_balance_before"] = money(balance, decimals)
        body["source_balance_after"] = money(balance - amount, decimals)
    if kind in ("P2P", "RECARGA"):
        body["destination_account_id"] = destination["id"]
        body["destination_balance_before"] = money(balance, decimals)
        body["destination_balance_after"] = money(balance + amount, decimals)
    if kind == "QR":
        body["merchant_id"] = rng.choice(DATA["merchants"])
    return body
