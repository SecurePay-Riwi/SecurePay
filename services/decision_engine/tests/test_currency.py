"""HU-42 / RN-11: the rate of the transaction's day, from the
pagoseguro-exchange-rates table loaded in memory.

DynamoDB is replaced by a fake client: these tests need no LocalStack.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from services.decision_engine import currency

OCT_1 = date(2026, 10, 1)
OCT_2 = date(2026, 10, 2)
OCT_5 = date(2026, 10, 5)


def item(day: str, **rates) -> dict:
    """An item as the DynamoDB client returns it."""
    return {
        "base": {"S": "USD"},
        "rate_date": {"S": day},
        "rates": {
            "M": {code: {"N": str(v)} for code, v in {"USD": 1, **rates}.items()}
        },
        "source": {"S": "https://api.frankfurter.dev/v2/rates"},
        "expires_at": {"N": "1790000000"},
    }


ITEMS = [
    item("2026-10-01", COP="3317.65", EUR="0.88286", JPY="157.78"),
    item("2026-10-02", COP="3900", EUR="0.9", JPY="150"),
    # 2026-10-03 and 04 have no item.
    item("2026-10-05", COP="4000", EUR="0.8", JPY="160"),
]


class FakeDynamo:
    """Answers Query in pages of `page` items, or fails."""

    def __init__(self, items, page=2, error=None):
        self.items, self.page, self.error = items, page, error
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        start = kwargs.get("ExclusiveStartKey", {}).get("i", 0)
        page = {"Items": self.items[start : start + self.page]}
        if start + self.page < len(self.items):
            page["LastEvaluatedKey"] = {"i": start + self.page}
        return page


@pytest.fixture
def dynamo(monkeypatch):
    def use(items=ITEMS, **kwargs):
        fake = FakeDynamo(items, **kwargs)
        monkeypatch.setattr(currency.aws, "cliente", lambda service: fake)
        return fake

    return use


@pytest.fixture(autouse=True)
def fresh_logs():
    currency._logged.clear()


@pytest.mark.parametrize(
    ("code", "on", "per_usd", "amount", "usd"),
    [
        ("COP", OCT_2, "3900", "390000", "100.00"),
        ("EUR", OCT_2, "0.9", "90", "100.00"),
        ("JPY", OCT_2, "150", "15000", "100.00"),
        ("USD", OCT_2, "1", "100", "100.00"),
        ("COP", OCT_1, "3317.65", "3317.65", "1.00"),
    ],
)
def test_each_currency_uses_its_day(dynamo, code, on, per_usd, amount, usd):
    dynamo()
    assert currency.refresh()

    rate = currency.rate_for(code, on)

    assert rate == currency.Rate(Decimal(per_usd), on, False)
    assert currency.to_usd(Decimal(amount), code, on) == Decimal(usd)


def test_the_whole_table_is_read_page_by_page(dynamo):
    fake = dynamo(page=2)

    assert currency.refresh()

    assert len(fake.calls) == 2
    assert fake.calls[0]["TableName"] == currency.RATES_TABLE
    assert fake.calls[0]["ExpressionAttributeValues"] == {":base": {"S": "USD"}}
    assert currency.rate_for("EUR", OCT_5).per_usd == Decimal("0.8")


def test_day_without_rate_uses_the_last_earlier_one_and_logs_it(dynamo, caplog):
    dynamo()
    currency.refresh()
    oct_4 = date(2026, 10, 4)

    with caplog.at_level(logging.WARNING, logger=currency.__name__):
        rate = currency.rate_for("COP", oct_4)
        currency.rate_for("COP", oct_4)

    assert rate == currency.Rate(Decimal("3900"), OCT_2, True)
    # Logged once per day, not once per transaction.
    assert [r.getMessage() for r in caplog.records] == [
        "No COP rate for 2026-10-04: using the one of 2026-10-02."
    ]


def test_day_after_the_last_one_uses_the_last_one(dynamo):
    dynamo()
    currency.refresh()

    rate = currency.rate_for("JPY", date(2026, 11, 2))

    assert rate == currency.Rate(Decimal("160"), OCT_5, True)


def test_currency_missing_on_a_day_uses_an_earlier_day(dynamo):
    dynamo(
        [
            item("2026-10-01", COP="3317.65", EUR="0.88", JPY="157"),
            item("2026-10-02", EUR="0.9", JPY="150"),
        ]
    )
    currency.refresh()

    assert currency.rate_for("COP", OCT_2) == currency.Rate(
        Decimal("3317.65"), OCT_1, True
    )
    assert currency.rate_for("EUR", OCT_2).fallback is False


def test_table_down_at_startup_uses_the_fixed_rates(dynamo, caplog):
    dynamo(error=ConnectionError("LocalStack is down"))

    with caplog.at_level(logging.WARNING, logger=currency.__name__):
        assert currency.refresh() is False
        rate = currency.rate_for("COP", OCT_2)

    assert rate == currency.Rate(Decimal("3317.65"), currency.FIXED_RATE_DATE, True)
    assert "Could not read exchange rates" in caplog.text
    assert "using the fixed 2026-10-01 rate" in caplog.text


def test_table_down_later_keeps_the_last_loaded_rates(dynamo):
    dynamo()
    currency.refresh()
    dynamo(error=ConnectionError("timeout"))

    assert currency.refresh() is False
    assert currency.rate_for("COP", OCT_2).per_usd == Decimal("3900")


def test_empty_table_keeps_what_was_loaded(dynamo):
    dynamo()
    currency.refresh()
    dynamo([])

    assert currency.refresh() is False
    assert currency.rate_for("EUR", OCT_5).per_usd == Decimal("0.8")


def test_empty_table_at_startup_uses_the_fixed_rates(dynamo):
    dynamo([])

    assert currency.refresh() is False
    assert currency.rate_for("JPY", OCT_5) == currency.Rate(
        Decimal("157.76"), currency.FIXED_RATE_DATE, True
    )


def test_day_before_every_rate_uses_the_fixed_rates(dynamo):
    dynamo()
    currency.refresh()

    rate = currency.rate_for("EUR", date(2026, 9, 30))

    assert rate.rate_date == currency.FIXED_RATE_DATE
    assert rate.per_usd == currency.RATES_PER_USD["EUR"]


def test_bad_items_are_skipped(dynamo, caplog):
    bad_rate = item("2026-10-03", COP="0", EUR="0.9", JPY="150")
    bad_date = item("not-a-date", COP="1", EUR="1", JPY="1")
    other_base = {**item("2026-10-04", COP="1", EUR="1", JPY="1"), "base": {"S": "EUR"}}
    dynamo([ITEMS[0], bad_rate, bad_date, other_base])

    with caplog.at_level(logging.WARNING, logger=currency.__name__):
        assert currency.refresh()

    assert currency._table[0] == [OCT_1]
    assert "Skipping exchange rate item" in caplog.text


def test_usd_is_always_one_even_without_a_table():
    assert currency.rate_for("USD", OCT_5) == currency.Rate(Decimal("1"), OCT_5, False)


def test_unknown_currency_is_an_error():
    with pytest.raises(ValueError):
        currency.rate_for("GBP", OCT_5)


def test_the_day_is_the_transaction_date_in_utc():
    bogota = timezone(timedelta(hours=-5))

    # 21:00 in Bogotá on 1 October is already 2 October in UTC.
    assert currency.utc_day(datetime(2026, 10, 1, 21, 0, tzinfo=bogota)) == OCT_2


def test_start_loads_once_and_stop_ends_the_refresh(dynamo):
    fake = dynamo()
    try:
        currency.start()
        currency.start()
        assert len(fake.calls) == 2  # one load (two pages), not two
        assert currency.rate_for("COP", OCT_5).per_usd == Decimal("4000")
    finally:
        currency.stop()
