"""HTTP API for managing antifraud rules and catalog versions."""
import logging
from typing import Any

import valkey
from fastapi import FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from shared.rule_catalog import ALWAYS_ENABLED, CatalogSnapshot, RuleEntry
from services.rules_api import store

logger = logging.getLogger(__name__)
app = FastAPI(title="SecurePay Rules API", description="Manage versioned antifraud rules. Updates are published to Valkey and read by the decision engine without redeploying it.", version="0.1.0")


class RuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rn: str | None = None
    description: str | None = None
    action: str | None = None
    opens_case: bool | None = None
    score: int | None = Field(default=None, ge=0, le=100)
    params: dict[str, Any] | None = None


class EnabledUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"detail": "The request contains invalid rule data.", "errors": jsonable_encoder(exc.errors())})


@app.exception_handler(valkey.exceptions.ValkeyError)
async def valkey_exception_handler(request: Request, exc: Exception):
    logger.warning("Rules API could not access Valkey: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "The rule catalog is unavailable."})


def _author(value: str) -> str:
    author = value.strip()
    if not author or len(author) > 100:
        raise HTTPException(status_code=400, detail="X-Rule-Author must contain 1 to 100 characters.")
    return author


def _find(snapshot: CatalogSnapshot, code: str) -> RuleEntry:
    rule = snapshot.get(code)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule '{code}' was not found.")
    return rule


@app.get("/health")
def health_check():
    store.current_catalog()
    return {"status": "ok"}


@app.get("/rules", response_model=CatalogSnapshot)
def list_rules():
    return store.current_catalog()


@app.post("/rules", response_model=CatalogSnapshot, status_code=201)
def create_rule(rule: RuleEntry, x_rule_author: str = Header(default="api", alias="X-Rule-Author")):
    author = _author(x_rule_author)
    current = store.current_catalog()
    if current.get(rule.code):
        raise HTTPException(status_code=409, detail=f"Rule '{rule.code}' already exists.")
    if rule.type == "default_timeout":
        raise HTTPException(status_code=400, detail="The default_timeout rule cannot be duplicated.")
    new_rule = rule.model_copy(update={"rule_version": 1})
    snapshot = store.next_snapshot(current, [*current.rules, new_rule], author)
    store.publish_snapshot(snapshot)
    return snapshot


@app.patch("/rules/{code}", response_model=CatalogSnapshot)
def update_rule(code: str, changes: RuleUpdate, x_rule_author: str = Header(default="api", alias="X-Rule-Author")):
    author = _author(x_rule_author)
    current = store.current_catalog()
    rule = _find(current, code)
    updates = changes.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="At least one rule field must be provided.")
    try:
        updated = RuleEntry.model_validate({**rule.model_dump(), **updates, "rule_version": rule.rule_version + 1})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid rule update: {exc}") from exc
    rules = [updated if item.code == code else item for item in current.rules]
    snapshot = store.next_snapshot(current, rules, author)
    store.publish_snapshot(snapshot)
    return snapshot


@app.patch("/rules/{code}/enabled", response_model=CatalogSnapshot)
def set_enabled(code: str, change: EnabledUpdate, x_rule_author: str = Header(default="api", alias="X-Rule-Author")):
    author = _author(x_rule_author)
    current = store.current_catalog()
    rule = _find(current, code)
    if not change.enabled and code in ALWAYS_ENABLED:
        raise HTTPException(status_code=400, detail=f"Rule '{code}' must remain enabled.")
    updated = rule.model_copy(update={"enabled": change.enabled, "rule_version": rule.rule_version + 1})
    rules = [updated if item.code == code else item for item in current.rules]
    snapshot = store.next_snapshot(current, rules, author)
    store.publish_snapshot(snapshot)
    return snapshot


@app.get("/rules/versions")
def list_versions():
    return {"versions": [{"version": item.version, "created_at": item.created_at, "author": item.author, "rules_count": len(item.rules)} for item in store.catalog_versions()]}


@app.get("/rules/versions/{version}", response_model=CatalogSnapshot)
def get_version(version: int):
    for snapshot in store.catalog_versions():
        if snapshot.version == version:
            return snapshot
    raise HTTPException(status_code=404, detail=f"Catalog version {version} was not found.")
