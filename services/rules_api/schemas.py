"""Request and response bodies of the rules API.

The rule itself is shared/rule_catalog.RuleEntry: its params are
validated against PARAMS_BY_TYPE there, never redefined here.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from shared.rule_catalog import Action, CatalogSnapshot, RuleEntry, RuleType


class RuleCreate(BaseModel):
    """A new rule. It always starts at rule_version 1."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        description="Name in rules_triggered: English snake_case, 3 to 50 characters."
    )
    type: RuleType = Field(
        description="Which implementation runs it. Several rules can share a type with other params."
    )
    rn: str | None = Field(None, description="Business rule it implements, e.g. RN-02.")
    description: str = ""
    enabled: bool = True
    action: Action = Field(description="Decision when the rule fires.")
    opens_case: bool = False
    score: int = Field(
        0, ge=0, le=100, description="Adds to risk_score when the rule fires."
    )
    params: dict = Field(
        default_factory=dict, description="Thresholds, validated against the rule type."
    )


class RuleUpdate(BaseModel):
    """Replaces what a rule decides and its thresholds. The code and the
    type never change: create another rule instead."""

    model_config = ConfigDict(extra="forbid")

    description: str = ""
    action: Action
    opens_case: bool = False
    score: int = Field(0, ge=0, le=100)
    params: dict = Field(default_factory=dict)


class RuleChange(BaseModel):
    rule: RuleEntry
    catalog_version: int = Field(
        description="Catalog version after the request. The same as before when nothing changed."
    )


class VersionSummary(BaseModel):
    version: int
    created_at: datetime
    author: str
    change: dict = Field(
        description='{"operation", "code", "before", "after"}; before and after are the whole rule.'
    )


class VersionPage(BaseModel):
    total: int = Field(description="Number of versions stored.")
    versions: list[VersionSummary] = Field(description="Newest first.")


class Published(BaseModel):
    version: int
    published: bool = Field(description="True when Valkey now holds this version.")


class Health(BaseModel):
    status: str


class SimulationRequest(BaseModel):
    """A candidate catalog replayed over one day of the history (HU-24)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    day: date | None = Field(
        None, description="The day replayed (UTC). One day at a time (D5)."
    )
    from_: date | None = Field(
        None, alias="from", description="Not accepted: a range gives 422."
    )
    to: date | None = Field(None, description="Not accepted: a range gives 422.")
    candidate: CatalogSnapshot | list[RuleEntry] = Field(
        description="The catalog to try: a whole CatalogSnapshot or its list of rules."
    )
    against_version: int | None = Field(
        None,
        ge=0,
        description="Catalog version to compare with; the latest when missing.",
    )


class SimulationSide(BaseModel):
    rules_version: str = Field(description='The catalog version, or "candidate".')
    decisions: dict[str, int] = Field(
        description="APPROVE, HOLD and REJECT of the day."
    )
    cases: int = Field(description="Decisions with opens_case.")
    amount_usd: dict[str, str] = Field(description="USD decided per decision.")
    metrics: list[dict] = Field(
        description="rule_metrics against the labels of the lake (HU-44)."
    )


class Simulation(BaseModel):
    day: date
    transactions: int = Field(description="Transactions of the day replayed.")
    current: SimulationSide
    candidate: SimulationSide
    changed: int = Field(description="Transactions whose decision changes.")
    changes: dict[str, int] = Field(description='E.g. {"HOLD->APPROVE": 2}.')
    released_usd: str = Field(
        description="USD the candidate approves that the current catalog held or rejected."
    )
    stopped_usd: str = Field(
        description="USD the candidate holds or rejects that the current catalog approved."
    )
    examples: list[dict] = Field(
        description="Up to 10 transactions that change, largest amount first."
    )
