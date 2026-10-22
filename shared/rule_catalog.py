"""Rule catalog contract shared by the decision engine and the rules API.

The rules API writes catalogs with this shape and publishes them to
Valkey; the engine reads them and evaluates each enabled rule with its
parameters. Not part of the published securepay-shared package.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Valkey keys. Same hash tag so both live in one slot and can be written
# in one MULTI (ElastiCache Serverless spreads keys across nodes).
CATALOG_KEY = "{rules}:catalog"   # JSON of CatalogSnapshot
VERSION_KEY = "{rules}:version"   # CatalogSnapshot.version as a string

Action = Literal["APPROVE", "HOLD", "REJECT"]
RuleType = Literal[
    "restricted_list",   # RN-06
    "velocity",          # RN-02
    "mule",              # RN-03
    "shared_device",     # RN-04
    "splitting",         # RN-05
    "account_takeover",  # RN-07
    "default_timeout",   # RN-01 (used by the default decision, never by _decide)
]


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RestrictedListParams(_Params):
    pass


class VelocityParams(_Params):
    window_minutes: int = Field(10, gt=0, le=1440)   # out:{account} keeps 24 h
    limit: int = Field(5, gt=0)                      # fires when count > limit


class MuleParams(_Params):
    window_minutes: int = Field(30, gt=0, le=60)     # in:{account} keeps 60 min
    min_senders: int = Field(3, gt=0)                # fires when senders >= this
    withdrawn_pct: Decimal = Field(Decimal("80"), gt=0, le=100)


class SharedDeviceParams(_Params):
    window_days: int = Field(30, gt=0, le=30)        # dev:{device} keeps 30 days
    max_accounts: int = Field(3, gt=0)               # fires when accounts > this


class SplittingParams(_Params):
    window_hours: int = Field(24, gt=0, le=24)       # out:{account} keeps 24 h
    min_transactions: int = Field(3, gt=1)
    daily_limit_usd: Decimal = Field(Decimal("10000"), gt=0)


class AccountTakeoverParams(_Params):
    window_minutes: int = Field(60, gt=0, le=60)     # sec:{account} keeps 60 min
    # Fires when the amount in USD is above this.
    min_amount_usd: Decimal = Field(Decimal("200"), gt=0)


class DefaultTimeoutParams(_Params):
    limit_usd: Decimal = Field(Decimal("50"), gt=0)  # APPROVE below, HOLD from it up


PARAMS_BY_TYPE: dict[str, type[_Params]] = {
    "restricted_list": RestrictedListParams,
    "velocity": VelocityParams,
    "mule": MuleParams,
    "shared_device": SharedDeviceParams,
    "splitting": SplittingParams,
    "account_takeover": AccountTakeoverParams,
    "default_timeout": DefaultTimeoutParams,
}

# Rules that must always be enabled: the API refuses to disable them.
ALWAYS_ENABLED = {"default_timeout"}


class RuleEntry(BaseModel):
    """One rule of the catalog: which implementation (type) runs, with
    which parameters, and what it decides when it fires."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Goes to rules_triggered: stable, English snake_case.
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,49}$")
    type: RuleType
    rn: str | None = None                                # e.g. "RN-02"
    description: str = ""
    enabled: bool = True
    action: Action
    opens_case: bool = False
    score: int = Field(0, ge=0, le=100)                  # adds to risk_score
    params: dict = Field(default_factory=dict)
    rule_version: int = Field(1, ge=1)                   # +1 on every change

    @model_validator(mode="after")
    def _check_params(self):
        PARAMS_BY_TYPE[self.type](**self.params)
        return self

    def typed_params(self):
        return PARAMS_BY_TYPE[self.type](**self.params)


class CatalogSnapshot(BaseModel):
    """The whole catalog at one version. Immutable once published."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=0)                           # 0 = code defaults, no API yet
    created_at: datetime
    author: str
    rules: list[RuleEntry]

    @model_validator(mode="after")
    def _unique_codes(self):
        codes = [r.code for r in self.rules]
        if len(codes) != len(set(codes)):
            raise ValueError("Rule codes must be unique.")
        return self

    def get(self, code: str) -> RuleEntry | None:
        return next((r for r in self.rules if r.code == code), None)


DEFAULT_RULES = [
    RuleEntry(code="restricted_list", type="restricted_list", rn="RN-06",
              action="REJECT", opens_case=True,
              description="Account owner is on a restricted list."),
    RuleEntry(code="velocity", type="velocity", rn="RN-02", action="HOLD",
              params={"window_minutes": 10, "limit": 5}),
    RuleEntry(code="mule", type="mule", rn="RN-03", action="HOLD",
              opens_case=True,
              params={"window_minutes": 30, "min_senders": 3, "withdrawn_pct": "80"}),
    RuleEntry(code="shared_device", type="shared_device", rn="RN-04",
              action="APPROVE", score=30,
              params={"window_days": 30, "max_accounts": 3}),
    RuleEntry(code="splitting", type="splitting", rn="RN-05", action="APPROVE",
              opens_case=True, score=40,
              params={"window_hours": 24, "min_transactions": 3,
                      "daily_limit_usd": "10000"}),
    RuleEntry(code="account_takeover", type="account_takeover", rn="RN-07",
              action="HOLD", params={"window_minutes": 60, "min_amount_usd": "200"}),
    RuleEntry(code="default_timeout", type="default_timeout", rn="RN-01",
              action="HOLD", params={"limit_usd": "50"}),
]


def default_catalog() -> CatalogSnapshot:
    """Catalog used until the rules API publishes one (version 0)."""
    return CatalogSnapshot(
        version=0,
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        author="code",
        rules=DEFAULT_RULES,
    )
