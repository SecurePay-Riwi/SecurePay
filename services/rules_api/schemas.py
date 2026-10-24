"""Request and response bodies of the rules API.

The rule itself is shared/rule_catalog.RuleEntry: its params are
validated against PARAMS_BY_TYPE there, never redefined here.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from shared.rule_catalog import Action, RuleEntry, RuleType


class RuleCreate(BaseModel):
    """A new rule. It always starts at rule_version 1."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Name in rules_triggered: English snake_case, 3 to 50 characters.")
    type: RuleType = Field(description="Which implementation runs it. Several rules can share a type with other params.")
    rn: str | None = Field(None, description="Business rule it implements, e.g. RN-02.")
    description: str = ""
    enabled: bool = True
    action: Action = Field(description="Decision when the rule fires.")
    opens_case: bool = False
    score: int = Field(0, ge=0, le=100, description="Adds to risk_score when the rule fires.")
    params: dict = Field(default_factory=dict, description="Thresholds, validated against the rule type.")


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
    catalog_version: int = Field(description="Catalog version after the request. The same as before when nothing changed.")


class VersionSummary(BaseModel):
    version: int
    created_at: datetime
    author: str
    change: dict = Field(description='{"operation", "code", "before", "after"}; before and after are the whole rule.')


class VersionPage(BaseModel):
    total: int = Field(description="Number of versions stored.")
    versions: list[VersionSummary] = Field(description="Newest first.")


class Published(BaseModel):
    version: int
    published: bool = Field(description="True when Valkey now holds this version.")


class Health(BaseModel):
    status: str
