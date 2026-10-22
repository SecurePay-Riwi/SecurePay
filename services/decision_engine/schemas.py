
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

    id: UUID = Field(
        description="Chosen by the core. It is the idempotency key."
    )
    type: TransactionType = Field(
        description="P2P, QR (payment to a merchant), RECARGA (top-up) or RETIRO (withdrawal)."
    )
    channel: str = Field(
        min_length=1, max_length=30, description="Where it was made, e.g. APP or WEB."
    )
    source_account_id: UUID | None = Field(
        default=None, description="Required in P2P, QR and RETIRO."
    )
    destination_account_id: UUID | None = Field(
        default=None, description="Required in P2P and RECARGA."
    )
    merchant_id: UUID | None = Field(default=None, description="Required in QR.")
    amount: Decimal = Field(
        gt=0, description="In the account's currency. At most 2 decimals (JPY: none)."
    )
    currency: Literal["COP", "USD", "EUR", "JPY"] = Field(
        description="Must be the currency of the account."
    )
    source_balance_before: Decimal | None = Field(
        default=None, description="Required when there is a source account."
    )
    source_balance_after: Decimal | None = Field(
        default=None, description="Required when there is a source account."
    )
    destination_balance_before: Decimal | None = Field(
        default=None, description="Required when there is a destination account."
    )
    destination_balance_after: Decimal | None = Field(
        default=None, description="Required when there is a destination account."
    )
    device_id: UUID = Field(description="It does not need to exist in the database.")
    transaction_date: AwareDatetime = Field(
        description="When it happened in the core, with time zone."
    )

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

    transaction_id: UUID = Field(description="The `id` that was sent.")
    decision: Decision = Field(description="APPROVE, HOLD or REJECT.")
    decision_reason: str = Field(description="Why, from the rule that decided.")
    # Con valor por defecto: una decisión guardada en Valkey antes de que
    # existieran estos campos se puede seguir repitiendo.
    rules_version: str | None = Field(
        default=None,
        description="Version of the rule catalog used: \"0\" is the code defaults, N a version published by the rules API. null in decisions stored before it existed.",
    )
    rules_triggered: list[str] = Field(
        default=[],
        description="Every rule that fired, not only the one that decided.",
    )
    # True when a rule whose catalog entry says opens_case fired.
    opens_case: bool = Field(
        default=False,
        description="True when a rule that opens a case for an analyst fired (by default: mule account, splitting, restricted list).",
    )
    risk_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Sum of the scores of the rules that fired, at most 100. 0 when no rule with a score fired.",
    )
    # True when the rules did not answer in time and RN-01's default
    # decision was applied.
    by_default: bool = Field(
        default=False,
        description="True when the rules did not answer in time and the default decision was applied.",
    )
    processed_at: datetime = Field(description="When the engine decided (UTC).")
    idempotent_replay: bool = Field(
        default=False,
        description="True when this is the stored decision returned to a resend of the same id.",
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = Field(
        description="Always ok while the process runs; messaging problems do not change it."
    )
    messaging: dict[str, int] = Field(
        description="SNS publisher counters: pending, published and failed decisions."
    )
