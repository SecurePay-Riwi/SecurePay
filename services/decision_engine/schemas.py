
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Decision(str, Enum):
    APPROVE = "APPROVE"
    HOLD = "HOLD"
    REJECT = "REJECT"


class TransactionRequest(BaseModel):
    id: UUID
    user_id: UUID
    device_id: UUID
    merchant_id: UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    transaction_date: datetime
    channel: str = Field(min_length=1, max_length=30)


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    decision: Decision
    decision_reason: str
    processed_at: datetime
    idempotent_replay: bool = False
