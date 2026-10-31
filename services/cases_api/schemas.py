"""Request and response bodies of the cases API.

Join point: each owner adds the models of their endpoints here. The
tables and states are shared/cases.py; never redefine them.
Money is Decimal (a decimal string in JSON), dates are UTC.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Health(BaseModel):
    status: str


# --- Compliance (HU-34) ------------------------------------------------------

class RestrictedListReport(BaseModel):
    """RN-06: one listed document of a transaction (a compliance_reports row)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Report id.")
    case_id: UUID = Field(description="The case the transaction opened.")
    transaction_id: UUID = Field(description="The transaction where the owner took part.")
    account_id: UUID = Field(description="The account whose owner is listed (source or destination).")
    document: str = Field(description="The owner's document, digits only, as the list stores it.")
    list_type: str = Field(description="The list it is on, as the provider names it (e.g. PEP, sanciones).")
    matched_at: datetime = Field(description="When the consumer wrote the report, UTC (right after the decision).")
    notified_at: datetime | None = Field(
        description="When the compliance summary e-mail included it, UTC; null until the next run of the alerts task.",
    )


class RestrictedListReportPage(BaseModel):
    items: list[RestrictedListReport] = Field(description="The reports of the page, newest first.")
    total: int = Field(description="Reports in the period, all pages.")
    page: int = Field(description="Page number, from 1.")
    size: int = Field(description="Reports per page.")
