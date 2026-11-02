"""Amounts in USD at the rate of the transaction's day (RN-11, HU-42).

The rates come from the `pagoseguro-exchange-rates` DynamoDB table,
which securepay-apis fills once a day from Frankfurter: one item per
day, `base = "USD"`, `rate_date = "YYYY-MM-DD"` and `rates` = units of
each currency per 1 USD. The table is small (about 30 items, one per
day for 30 days), so the engine loads all of it into memory at startup
and refreshes it in the background every RATES_REFRESH_SECONDS: a
decision never waits for DynamoDB.

- The day is the transaction's `transaction_date` in UTC.
- A day without a rate uses the last earlier day that has one
  (`fallback = True`), logged once per day asked.
- If the table is empty, down or not loaded yet, and there is no
  earlier day, the fixed 2026-10-01 snapshot below is used, with a
  warning. A failed refresh keeps the last table that loaded.
- USD is always 1.
"""

import bisect
import logging
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from boto3.dynamodb.types import TypeDeserializer

from shared import aws

log = logging.getLogger(__name__)

RATES_TABLE = os.getenv("RATES_TABLE", "pagoseguro-exchange-rates")
REFRESH_SECONDS = float(os.getenv("RATES_REFRESH_SECONDS", "3600"))

if REFRESH_SECONDS <= 0:
    raise ValueError("RATES_REFRESH_SECONDS must be positive.")

BASE = "USD"

# Units of each currency per 1 USD, Frankfurter v2, 2026-10-01 (the
# project's reference date). Only used when the table has no rate for
# the day or any earlier day.
FIXED_RATE_DATE = date(2026, 10, 1)
RATES_PER_USD = {
    "USD": Decimal("1"),
    "COP": Decimal("3317.65"),
    "EUR": Decimal("0.88284"),
    "JPY": Decimal("157.76"),
}

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class Rate:
    per_usd: Decimal  # units of the currency per 1 USD (USD -> 1)
    rate_date: date  # the Frankfurter day actually used
    fallback: bool  # True when rate_date is not the day asked for


# The loaded table: the days in order and the rates of each one. It is
# replaced whole (one assignment), so a decision reads one consistent
# version without a lock.
_table: tuple[list[date], dict[date, dict[str, Decimal]]] = ([], {})
_logged: set[tuple[date, str]] = set()
_started = threading.Lock()
_thread: threading.Thread | None = None


def utc_day(moment: datetime) -> date:
    """The day of a transaction: its date in UTC."""
    return moment.astimezone(timezone.utc).date()


def parse_items(items: list[dict]) -> dict[date, dict[str, Decimal]]:
    """The rates of each day, from DynamoDB items in the client's format.

    An item that is not USD-based, has no valid date or has a rate that
    is not a positive number is skipped with a warning: one bad day does
    not throw away the others.
    """
    deserialize = TypeDeserializer().deserialize
    table = {}
    for raw in items:
        try:
            item = {key: deserialize(value) for key, value in raw.items()}
            if item.get("base") != BASE:
                continue
            day = date.fromisoformat(item["rate_date"])
            rates = {
                code: Decimal(value) for code, value in item["rates"].items()
            }
            if any(not rate.is_finite() or rate <= 0 for rate in rates.values()):
                raise ValueError("rates must be positive numbers")
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            log.warning("Skipping exchange rate item %s: %s", raw.get("rate_date"), exc)
            continue
        rates[BASE] = Decimal("1")
        table[day] = rates
    return table


def load(table: dict[date, dict[str, Decimal]]) -> None:
    """Replace the rates in memory (refresh() and the tests use it)."""
    global _table
    _table = (sorted(table), dict(table))


def _query() -> list[dict]:
    """Every item of the table: one partition (base = USD), paginated."""
    client = aws.cliente("dynamodb")
    items, start = [], None
    while True:
        kwargs = {
            "TableName": RATES_TABLE,
            "KeyConditionExpression": "#b = :base",
            "ExpressionAttributeNames": {"#b": "base"},
            "ExpressionAttributeValues": {":base": {"S": BASE}},
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = client.query(**kwargs)
        items.extend(page.get("Items", []))
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def refresh() -> bool:
    """Read the table again. Never raises: if DynamoDB fails or the table
    is empty, the rates in memory stay as they are."""
    try:
        table = parse_items(_query())
    except Exception as exc:
        log.warning(
            "Could not read exchange rates from %s, keeping %d loaded days: %s",
            RATES_TABLE, len(_table[0]), exc,
        )
        return False
    if not table:
        log.warning(
            "Exchange rate table %s is empty, keeping %d loaded days.",
            RATES_TABLE, len(_table[0]),
        )
        return False
    load(table)
    days = _table[0]
    log.info("Loaded exchange rates of %d days (%s to %s).", len(days), days[0], days[-1])
    return True


def _refresh_forever(stop: threading.Event) -> None:
    while not stop.wait(REFRESH_SECONDS):
        refresh()


_stop = threading.Event()


def start() -> None:
    """Load the table and keep refreshing it in a background thread.
    Called once at the engine's startup; later calls do nothing."""
    global _thread
    with _started:
        if _thread is not None:
            return
        refresh()
        _stop.clear()
        _thread = threading.Thread(
            target=_refresh_forever, args=(_stop,), name="exchange-rates", daemon=True
        )
        _thread.start()


def stop() -> None:
    global _thread
    with _started:
        _stop.set()
        _thread = None


def _warn_once(on: date, currency: str, message: str, *args) -> None:
    key = (on, currency)
    if key in _logged:
        return
    if len(_logged) > 10_000:  # a long-running engine sees many days
        _logged.clear()
    _logged.add(key)
    log.warning(message, *args)


def rate_for(currency: str, on: date) -> Rate:
    """The rate of `currency` on day `on`, or of the last earlier day."""
    if currency not in RATES_PER_USD:
        raise ValueError(f"No exchange rate for {currency}.")
    if currency == BASE:
        return Rate(Decimal("1"), on, False)

    days, by_day = _table
    i = bisect.bisect_right(days, on)
    while i > 0:
        i -= 1
        day = days[i]
        rate = by_day[day].get(currency)
        if rate is not None:
            if day != on:
                _warn_once(
                    on, currency,
                    "No %s rate for %s: using the one of %s.", currency, on, day,
                )
            return Rate(rate, day, day != on)

    _warn_once(
        on, currency,
        "No %s rate for %s or any earlier day in %s: using the fixed %s rate.",
        currency, on, RATES_TABLE, FIXED_RATE_DATE,
    )
    return Rate(RATES_PER_USD[currency], FIXED_RATE_DATE, FIXED_RATE_DATE != on)


def convert(amount: Decimal, rate: Rate) -> Decimal:
    """The amount in USD with a given rate, rounded to cents."""
    return (Decimal(amount) / rate.per_usd).quantize(CENTS)


def to_usd(amount: Decimal, currency: str, on: date | None = None) -> Decimal:
    """The amount in USD at the rate of day `on` (today in UTC if not
    given), rounded to cents."""
    if on is None:
        on = datetime.now(timezone.utc).date()
    return convert(amount, rate_for(currency, on))
