"""Swagger documentation of the rules API: summaries, descriptions and an
example of every status code. tests/test_openapi.py checks them."""

from pydantic import BaseModel, Field

from shared.rule_catalog import DEFAULT_RULES

APP = {
    "title": "SecurePay rules API",
    "version": "1.0.0",
    "description": (
        "Creates, changes, enables and disables the antifraud rules of the "
        "decision engine. Every change is a new catalog version, stored in "
        "PostgreSQL and never modified, and published to Valkey, where the "
        "engine picks it up in about a second without a restart.\n\n"
        "Send `X-User` with your name: it is the author of the version "
        "(`anonymous` when missing)."
    ),
}


class Error(BaseModel):
    detail: str = Field(description="What went wrong.")


class ValidationError(BaseModel):
    detail: str = Field(description="Always the same summary message.")
    errors: list[dict] = Field(description="One entry per problem, as Pydantic reports it.")


VELOCITY = DEFAULT_RULES[1].model_dump(mode="json")
SLOW_VELOCITY = {**VELOCITY, "params": {"window_minutes": 10, "limit": 2}, "rule_version": 2}
VELOCITY_1H = {
    "code": "velocity_1h", "type": "velocity", "rn": "RN-02",
    "description": "More than 20 transfers in one hour.", "enabled": True,
    "action": "HOLD", "opens_case": False, "score": 0,
    "params": {"window_minutes": 60, "limit": 20},
}

INVALID_EXAMPLE = {
    "detail": "The request contains invalid rule data.",
    "errors": [{
        "type": "greater_than", "loc": ["window_minutes"],
        "msg": "Input should be greater than 0", "input": 0,
    }],
}


def _ok(description: str, example) -> dict:
    return {"description": description, "content": {"application/json": {"example": example}}}


def _error(description: str, detail: str) -> dict:
    return {"description": description, "model": Error,
            "content": {"application/json": {"example": {"detail": detail}}}}


INVALID = {"description": "Invalid body, header or parameters.", "model": ValidationError,
           "content": {"application/json": {"example": INVALID_EXAMPLE}}}
DB_DOWN = _error("PostgreSQL is not available.", "The rule catalog database is not available.")
NO_RULE = _error("No rule with that code.", "Rule 'velocity_2h' does not exist.")
NO_VERSION = _error("No catalog version with that number.", "Catalog version 999 does not exist.")


def _change(rule: dict, version: int) -> dict:
    return {"rule": rule, "catalog_version": version}


SNAPSHOT = {
    "version": 2,
    "created_at": "2026-10-24T12:00:00Z",
    "author": "Yulianis",
    "rules": [r.model_dump(mode="json") for r in DEFAULT_RULES],
}

HEALTH = {
    "summary": "Check that the API and its database are up",
    "tags": ["Health"],
    "responses": {200: _ok("Up.", {"status": "ok"}), 503: DB_DOWN},
}

GET_CATALOG = {
    "summary": "Get the active catalog",
    "description": "The latest version with every rule, the disabled ones included.",
    "tags": ["Rules"],
    "responses": {200: _ok("The latest catalog version.", SNAPSHOT), 503: DB_DOWN},
}

GET_RULE = {
    "summary": "Get one rule",
    "tags": ["Rules"],
    "responses": {200: _ok("The rule as the latest version has it.", VELOCITY), 404: NO_RULE, 503: DB_DOWN},
}

CREATE = {
    "summary": "Create a rule",
    "description": (
        "A new rule with an existing `type` and its own `params`; the engine "
        "evaluates it from the next catalog version. It starts at "
        "`rule_version` 1. `versions` and `publish` are not valid codes, and "
        "there is only one `default_timeout` rule."
    ),
    "tags": ["Rules"],
    "responses": {
        201: _ok("Created. A new catalog version.", _change({**VELOCITY_1H, "rule_version": 1}, 3)),
        400: INVALID,
        409: _error("A rule with that code exists.", "Rule 'velocity' already exists."),
        503: DB_DOWN,
    },
}

UPDATE = {
    "summary": "Change a rule",
    "description": (
        "Replaces `description`, `action`, `opens_case`, `score` and `params`; "
        "`code` and `type` never change. `rule_version` goes up by one. If the "
        "body is invalid the rule keeps working as before. A body equal to "
        "the rule creates no version."
    ),
    "tags": ["Rules"],
    "responses": {
        200: _ok("Changed, or already like that.", _change(SLOW_VELOCITY, 2)),
        400: INVALID,
        404: NO_RULE,
        503: DB_DOWN,
    },
}

ENABLE = {
    "summary": "Enable a rule",
    "description": "If it is already enabled, nothing changes and no version is created.",
    "tags": ["Rules"],
    "responses": {
        200: _ok("Enabled.", _change({**VELOCITY, "rule_version": 3}, 4)),
        400: INVALID,
        404: NO_RULE,
        503: DB_DOWN,
    },
}

DISABLE = {
    "summary": "Disable a rule",
    "description": (
        "The engine stops evaluating it from the next version; its history "
        "keeps being recorded, so it works right away when enabled again. "
        "If it is already disabled, no version is created."
    ),
    "tags": ["Rules"],
    "responses": {
        200: _ok("Disabled.", _change({**VELOCITY, "enabled": False, "rule_version": 2}, 3)),
        400: INVALID,
        404: NO_RULE,
        409: _error("The default decision cannot be disabled.", "Rule 'default_timeout' must stay enabled."),
        503: DB_DOWN,
    },
}

LIST_VERSIONS = {
    "summary": "List the catalog versions",
    "description": "Newest first, with who made each change and the rule before and after.",
    "tags": ["Versions"],
    "responses": {
        200: _ok("One page of versions.", {
            "total": 2,
            "versions": [
                {"version": 2, "created_at": "2026-10-24T12:00:00Z", "author": "Yulianis",
                 "change": {"operation": "update", "code": "velocity",
                            "before": VELOCITY, "after": SLOW_VELOCITY}},
                {"version": 1, "created_at": "2026-10-24T11:00:00Z", "author": "code",
                 "change": {"operation": "seed", "code": None, "before": None, "after": None}},
            ],
        }),
        400: INVALID,
        503: DB_DOWN,
    },
}

GET_VERSION = {
    "summary": "Get one catalog version",
    "tags": ["Versions"],
    "responses": {200: _ok("The whole catalog of that version.", SNAPSHOT),
                  400: INVALID, 404: NO_VERSION, 503: DB_DOWN},
}

ACTIVATE = {
    "summary": "Go back to an old version",
    "description": (
        "Creates a new version whose rules are the ones of the old version "
        "(history is never rewritten). Rules created after it are disabled. "
        "If the catalog is already like that, no version is created."
    ),
    "tags": ["Versions"],
    "responses": {200: _ok("The catalog now active.", {**SNAPSHOT, "version": 5}),
                  400: INVALID, 404: NO_VERSION, 503: DB_DOWN},
}

PUBLISH = {
    "summary": "Publish the latest version to Valkey again",
    "description": "For operations: after Valkey lost its data, or when a publish failed.",
    "tags": ["Versions"],
    "responses": {
        200: _ok("Valkey holds the latest version.", {"version": 2, "published": True}),
        503: _error("Valkey or PostgreSQL is not available.", "Valkey is not available."),
    },
}
