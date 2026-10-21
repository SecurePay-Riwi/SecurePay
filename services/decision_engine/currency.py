"""Amounts in USD, for the rules whose thresholds are in dollars.

For now it uses a fixed snapshot of Frankfurter's rates for 2026-10-01
(the project's reference date), the same day the generator starts from.
HU-42 replaces it with the rate of the transaction's own day, read from
the `pagoseguro-exchange-rates` table; the callers do not change.
"""

from decimal import Decimal

# Units of each currency per 1 USD, Frankfurter v2, 2026-10-01.
RATES_PER_USD = {
    "USD": Decimal("1"),
    "COP": Decimal("3317.65"),
    "EUR": Decimal("0.88284"),
    "JPY": Decimal("157.76"),
}


def to_usd(amount: Decimal, currency: str) -> Decimal:
    """The amount in USD, rounded to cents."""
    try:
        rate = RATES_PER_USD[currency]
    except KeyError:
        raise ValueError(f"No exchange rate for {currency}.") from None

    return (Decimal(amount) / rate).quantize(Decimal("0.01"))
