
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.decision_engine.schemas import TransactionRequest


def _qr(**cambios) -> dict:
    """Un pago QR válido; cada prueba cambia solo lo que quiere probar."""
    payload = {
        "id": str(uuid4()),
        "type": "QR",
        "channel": "APP",
        "source_account_id": str(uuid4()),
        "destination_account_id": None,
        "merchant_id": str(uuid4()),
        "amount": "88.91",
        "currency": "COP",
        "source_balance_before": "1000.00",
        "source_balance_after": "911.09",
        "destination_balance_before": None,
        "destination_balance_after": None,
        "device_id": str(uuid4()),
        "transaction_date": "2026-10-01T12:00:00+00:00",
    }
    payload.update(cambios)
    return payload


def _p2p(**cambios) -> dict:
    payload = _qr(
        type="P2P",
        merchant_id=None,
        destination_account_id=str(uuid4()),
        destination_balance_before="50.00",
        destination_balance_after="138.91",
    )
    payload.update(cambios)
    return payload


def _recarga(**cambios) -> dict:
    payload = _qr(
        type="RECARGA",
        merchant_id=None,
        source_account_id=None,
        source_balance_before=None,
        source_balance_after=None,
        destination_account_id=str(uuid4()),
        destination_balance_before="50.00",
        destination_balance_after="138.91",
    )
    payload.update(cambios)
    return payload


def _retiro(**cambios) -> dict:
    payload = _qr(type="RETIRO", merchant_id=None)
    payload.update(cambios)
    return payload


@pytest.mark.parametrize("armar", [_qr, _p2p, _recarga, _retiro])
def test_valid_transaction_of_each_type_is_accepted(armar):
    TransactionRequest(**armar())


def test_trailing_zeros_are_normalized():
    transaction = TransactionRequest(**_qr(amount="88.910"))

    assert transaction.amount == Decimal("88.91")
    assert str(transaction.amount) == "88.91"


def test_same_amount_written_differently_gives_same_json():
    # La huella de idempotencia sale de este JSON: "88.910" y "88.91"
    # deben contar como el mismo contenido.
    payload = _qr()
    con_ceros = TransactionRequest(**{**payload, "amount": "88.910"})
    sin_ceros = TransactionRequest(**{**payload, "amount": "88.91"})

    assert con_ceros.model_dump(mode="json") == sin_ceros.model_dump(mode="json")


def test_yen_drops_zero_decimals():
    transaction = TransactionRequest(
        **_qr(
            currency="JPY",
            amount="12027.00",
            source_balance_before="50000.00",
            source_balance_after="37973",
        )
    )

    assert str(transaction.amount) == "12027"
    assert str(transaction.source_balance_before) == "50000"


@pytest.mark.parametrize(
    "cambios",
    [
        {"amount": "88.913"},
        {"source_balance_after": "911.091"},
        {"currency": "JPY", "amount": "88.5"},
        {"amount": "0"},
        {"amount": "-5.00"},
        {"currency": "GBP"},
        {"type": "TRANSFERENCIA"},
        {"channel": ""},
        # Sin zona horaria no se sabe a qué hora ocurrió.
        {"transaction_date": "2026-10-01T12:00:00"},
    ],
)
def test_invalid_values_are_rejected(cambios):
    with pytest.raises(ValidationError):
        TransactionRequest(**_qr(**cambios))


@pytest.mark.parametrize(
    "payload",
    [
        _qr(merchant_id=None),
        _qr(source_account_id=None),
        _p2p(destination_account_id=None),
        _p2p(source_account_id=None),
        _recarga(destination_account_id=None),
        _recarga(
            source_account_id=str(uuid4()),
            source_balance_before="10.00",
            source_balance_after="5.00",
        ),
        _retiro(source_account_id=None),
        _retiro(
            destination_account_id=str(uuid4()),
            destination_balance_before="10.00",
            destination_balance_after="20.00",
        ),
    ],
)
def test_wrong_accounts_for_the_type_are_rejected(payload):
    with pytest.raises(ValidationError):
        TransactionRequest(**payload)


@pytest.mark.parametrize(
    "payload",
    [
        _qr(source_balance_before=None),
        _qr(source_balance_after=None),
        _p2p(destination_balance_before=None),
        _recarga(destination_balance_after=None),
    ],
)
def test_present_account_without_balances_is_rejected(payload):
    with pytest.raises(ValidationError):
        TransactionRequest(**payload)


def test_same_source_and_destination_is_rejected():
    cuenta = str(uuid4())

    with pytest.raises(ValidationError):
        TransactionRequest(
            **_p2p(source_account_id=cuenta, destination_account_id=cuenta)
        )
