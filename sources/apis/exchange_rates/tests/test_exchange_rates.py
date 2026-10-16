"""Tests for the Frankfurter client.

No internet: every test mocks the HTTP call. The validation logic is the
part that matters, and it is exercised with fixed responses.
"""

from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from sources.apis.exchange_rates import frankfurter


# --- Fixed responses --------------------------------------------------------

_OK_RESPONSE = [
    {"date": "2026-10-14", "base": "USD", "quote": "COP", "rate": 3317.65},
    {"date": "2026-10-14", "base": "USD", "quote": "EUR", "rate": 0.88286},
    {"date": "2026-10-14", "base": "USD", "quote": "JPY", "rate": 157.78},
]


def _response(json_data, status=200):
    """Build an httpx.Response so we do not need a real server."""
    return httpx.Response(
        status_code=status,
        json=json_data,
        request=httpx.Request("GET", "https://api.frankfurter.dev/v2/rates"),
    )


# --- Happy path -------------------------------------------------------------

def test_correct_response_returns_all_four_currencies():
    with patch("httpx.get", return_value=_response(_OK_RESPONSE)):
        result = frankfurter.fetch()

    assert result["date"] == "2026-10-14"
    assert set(result["rates"].keys()) == {"USD", "COP", "EUR", "JPY"}
    assert result["rates"]["USD"] == Decimal(1)
    assert result["rates"]["COP"] == Decimal("3317.65")


def test_rates_are_decimal_not_float():
    """boto3 rejects floats in DynamoDB, so this must always be Decimal."""
    with patch("httpx.get", return_value=_response(_OK_RESPONSE)):
        result = frankfurter.fetch()

    for rate in result["rates"].values():
        assert isinstance(rate, Decimal)


# --- Error cases ------------------------------------------------------------

def test_missing_currency_raises():
    incomplete = [r for r in _OK_RESPONSE if r["quote"] != "COP"]

    with patch("httpx.get", return_value=_response(incomplete)):
        with pytest.raises(ValueError, match="expected"):
            frankfurter.fetch()


def test_different_dates_raise():
    """A mix of dates means the response is inconsistent."""
    mixed = [
        {"date": "2026-10-14", "base": "USD", "quote": "COP", "rate": 3317.65},
        {"date": "2026-10-13", "base": "USD", "quote": "EUR", "rate": 0.88286},
        {"date": "2026-10-14", "base": "USD", "quote": "JPY", "rate": 157.78},
    ]

    with patch("httpx.get", return_value=_response(mixed)):
        with pytest.raises(ValueError, match="do not match"):
            frankfurter.fetch()


def test_zero_rate_raises():
    with_zero = [
        {"date": "2026-10-14", "base": "USD", "quote": "COP", "rate": 0},
        {"date": "2026-10-14", "base": "USD", "quote": "EUR", "rate": 0.88286},
        {"date": "2026-10-14", "base": "USD", "quote": "JPY", "rate": 157.78},
    ]

    with patch("httpx.get", return_value=_response(with_zero)):
        with pytest.raises(ValueError, match="Invalid rate"):
            frankfurter.fetch()


def test_503_is_retried_and_then_fails():
    """A persistent 5xx is retried 3 times, then raises RuntimeError.

    time.sleep is patched so the test does not actually wait.
    """
    response_503 = _response({}, status=503)

    with patch("httpx.get", return_value=response_503), \
         patch("time.sleep"):
        with pytest.raises(RuntimeError, match="did not respond"):
            frankfurter.fetch()