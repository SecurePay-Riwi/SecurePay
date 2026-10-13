
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from shared.config import MONEDA_DECIMALES


class Decision(str, Enum):
    APPROVE = "APPROVE"
    HOLD = "HOLD"
    REJECT = "REJECT"


class TransactionType(str, Enum):
    P2P = "P2P"
    QR = "QR"
    RECARGA = "RECARGA"
    RETIRO = "RETIRO"


CAMPOS_DE_DINERO = (
    "amount",
    "source_balance_before",
    "source_balance_after",
    "destination_balance_before",
    "destination_balance_after",
)


class TransactionRequest(BaseModel):
    """La transacción tal como la manda el core (generators/core.py)."""

    id: UUID
    type: TransactionType
    channel: str = Field(min_length=1, max_length=30)
    source_account_id: UUID | None = None
    destination_account_id: UUID | None = None
    merchant_id: UUID | None = None
    amount: Decimal = Field(gt=0)
    currency: Literal["COP", "USD", "EUR", "JPY"]
    source_balance_before: Decimal | None = None
    source_balance_after: Decimal | None = None
    destination_balance_before: Decimal | None = None
    destination_balance_after: Decimal | None = None
    device_id: UUID
    transaction_date: AwareDatetime

    @model_validator(mode="after")
    def validar_transaccion(self):
        self._normalizar_dinero()
        self._validar_cuentas()
        return self

    def _normalizar_dinero(self):
        # Cada moneda tiene sus decimales (el yen no lleva). "88.910" se
        # acepta y queda en 88.91; "88.913" se rechaza porque redondearlo
        # cambiaría el valor que mandó el core.
        decimales = MONEDA_DECIMALES[self.currency]
        unidad = Decimal(1).scaleb(-decimales)

        for campo in CAMPOS_DE_DINERO:
            valor = getattr(self, campo)
            if valor is None:
                continue

            try:
                normalizado = valor.quantize(unidad)
            except InvalidOperation:
                raise ValueError(f"{campo} no es un valor válido.")

            if normalizado != valor:
                raise ValueError(
                    f"{campo} tiene más de {decimales} decimales, "
                    f"que es lo que admite {self.currency}."
                )

            setattr(self, campo, normalizado)

    def _validar_cuentas(self):
        origen = self.source_account_id
        destino = self.destination_account_id

        # Qué cuentas lleva cada tipo de transacción.
        if self.type == TransactionType.P2P and not (origen and destino):
            raise ValueError("Un P2P necesita cuenta de origen y de destino.")

        if self.type == TransactionType.RECARGA and (origen or not destino):
            raise ValueError("Una recarga solo lleva cuenta de destino.")

        if self.type == TransactionType.RETIRO and (destino or not origen):
            raise ValueError("Un retiro solo lleva cuenta de origen.")

        if self.type == TransactionType.QR and not (origen and self.merchant_id):
            raise ValueError("Un pago QR necesita cuenta de origen y comercio.")

        # Cada cuenta presente debe traer su saldo antes y después.
        if origen and (
            self.source_balance_before is None
            or self.source_balance_after is None
        ):
            raise ValueError("Faltan los saldos de la cuenta de origen.")

        if destino and (
            self.destination_balance_before is None
            or self.destination_balance_after is None
        ):
            raise ValueError("Faltan los saldos de la cuenta de destino.")

        if origen and origen == destino:
            raise ValueError("El origen y el destino no pueden ser la misma cuenta.")


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    decision: Decision
    decision_reason: str
    processed_at: datetime
    idempotent_replay: bool = False
