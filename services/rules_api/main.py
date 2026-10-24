"""Rules API (HU-19 to HU-22): create, change, enable and disable the
antifraud rules, and keep every catalog version.

PostgreSQL is the truth (store.py); after each commit the new catalog is
published to Valkey (publisher.py), where the decision engine reads it
without a restart. If publishing fails the change is kept: the next
write, POST /rules/publish or a restart publishes it again.
"""

import logging
from contextlib import asynccontextmanager

import valkey
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from services.rules_api import docs, publisher, store
from services.rules_api.schemas import (
    Health,
    Published,
    RuleChange,
    RuleCreate,
    RuleUpdate,
    VersionPage,
    VersionSummary,
)
from shared.rule_catalog import ALWAYS_ENABLED, CatalogSnapshot, RuleEntry

logger = logging.getLogger(__name__)

# Paths under /rules that a rule code would hide.
RESERVED_CODES = {"versions", "publish"}

INVALID = "The request contains invalid rule data."


def _publish(snapshot: CatalogSnapshot, force: bool = False) -> bool:
    try:
        return publisher.publish(snapshot, force=force)
    except valkey.exceptions.ValkeyError:
        logger.exception("Catalog version %s not published to Valkey", snapshot.version)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.create_schema()
    # Valkey has no persistence in Compose: it may have lost the catalog.
    _publish(store.latest(), force=True)
    yield


app = FastAPI(**docs.APP, lifespan=lifespan)
_default_openapi = app.openapi


def openapi() -> dict:
    """FastAPI documents a 422 for every endpoint with input, but invalid
    input gets 400 here (validation_exception_handler)."""
    schema = _default_openapi()
    for operations in schema["paths"].values():
        for operation in operations.values():
            operation["responses"].pop("422", None)
    return schema


app.openapi = openapi


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"detail": INVALID, "errors": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(OperationalError)
async def database_down_handler(request, exc: OperationalError):
    logger.warning("Rules API could not reach PostgreSQL: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "The rule catalog database is not available."})


def _author(value: str) -> str:
    author = value.strip()
    if not 1 <= len(author) <= 100:
        raise HTTPException(status_code=400, detail="X-User must have 1 to 100 characters.")
    return author


def _invalid(exc: ValidationError) -> HTTPException:
    errors = exc.errors(include_url=False, include_context=False)
    return HTTPException(status_code=400, detail={"detail": INVALID, "errors": jsonable_encoder(errors)})


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    # A dict detail is already a whole body ({"detail", "errors"}).
    body = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
    return JSONResponse(status_code=exc.status_code, content=body)


def _get(rules: dict[str, RuleEntry], code: str) -> RuleEntry:
    rule = rules.get(code)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule '{code}' does not exist.")
    return rule


def _record(operation: str, code: str, before: RuleEntry | None, after: RuleEntry | None) -> dict:
    return {
        "operation": operation,
        "code": code,
        "before": None if before is None else before.model_dump(mode="json"),
        "after": None if after is None else after.model_dump(mode="json"),
    }


def _write(author: str, change) -> RuleChange:
    """Run a change; publish its version. NoChange answers the current rule."""
    try:
        snapshot, changed = store.write(author, change)
    except store.NoChange as same:
        rule = same.args[0]
        return RuleChange(rule=rule, catalog_version=store.latest().version)

    _publish(snapshot)
    return RuleChange(rule=changed[0], catalog_version=snapshot.version)


@app.get("/health", response_model=Health, **docs.HEALTH)
def health_check():
    store.latest()
    return Health(status="ok")


@app.get("/rules", response_model=CatalogSnapshot, **docs.GET_CATALOG)
def get_catalog():
    return store.latest()


# /rules/versions and /rules/publish go before /rules/{code}.
@app.get("/rules/versions", response_model=VersionPage, **docs.LIST_VERSIONS)
def list_versions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    total, rows = store.versions(limit, offset)
    return VersionPage(
        total=total,
        versions=[
            VersionSummary(version=r.version, created_at=r.created_at, author=r.author, change=r.change)
            for r in rows
        ],
    )


@app.get("/rules/versions/{version}", response_model=CatalogSnapshot, **docs.GET_VERSION)
def get_version(version: int):
    snapshot = store.version(version)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Catalog version {version} does not exist.")
    return snapshot


@app.post("/rules/versions/{version}/activate", response_model=CatalogSnapshot, **docs.ACTIVATE)
def activate_version(version: int, x_user: str = Header("anonymous")):
    """A new version whose rules are the ones of an old version. History
    is never rewritten. Rules created after that version are disabled."""
    author = _author(x_user)
    old = store.version(version)
    if old is None:
        raise HTTPException(status_code=404, detail=f"Catalog version {version} does not exist.")
    target = {rule.code: rule for rule in old.rules}

    def change(session, rules):
        changed = []
        for code, current in rules.items():
            wanted = target.get(code)
            if wanted is None:
                if current.enabled and current.type not in ALWAYS_ENABLED:
                    wanted = current.model_copy(update={"enabled": False})
                else:
                    continue
            if wanted.model_dump(exclude={"rule_version"}) == current.model_dump(exclude={"rule_version"}):
                continue
            new = wanted.model_copy(update={"rule_version": current.rule_version + 1})
            store.save(session, new, author)
            changed.append(new)
        if not changed:
            raise store.NoChange(None)
        return {"operation": "activate", "code": None, "from_version": version,
                "before": None, "after": None}, changed

    try:
        snapshot, _ = store.write(author, change)
    except store.NoChange:
        return store.latest()
    _publish(snapshot)
    return snapshot


@app.post("/rules/publish", response_model=Published, **docs.PUBLISH)
def publish_latest():
    snapshot = store.latest()
    try:
        publisher.publish(snapshot, force=True)
    except valkey.exceptions.ValkeyError as exc:
        raise HTTPException(status_code=503, detail="Valkey is not available.") from exc
    return Published(version=snapshot.version, published=True)


@app.get("/rules/{code}", response_model=RuleEntry, **docs.GET_RULE)
def get_rule(code: str):
    return _get({r.code: r for r in store.latest().rules}, code)


@app.post("/rules", response_model=RuleChange, status_code=201, **docs.CREATE)
def create_rule(body: RuleCreate, x_user: str = Header("anonymous")):
    author = _author(x_user)
    if body.code in RESERVED_CODES:
        raise HTTPException(status_code=400, detail=f"'{body.code}' is a reserved path, not a rule code.")
    if body.type in ALWAYS_ENABLED:
        raise HTTPException(status_code=400, detail=f"There is only one '{body.type}' rule.")
    try:
        rule = RuleEntry(**body.model_dump(), rule_version=1)
    except ValidationError as exc:
        raise _invalid(exc) from exc

    def change(session, rules):
        if rule.code in rules:
            raise HTTPException(status_code=409, detail=f"Rule '{rule.code}' already exists.")
        store.save(session, rule, author)
        return _record("create", rule.code, None, rule), [rule]

    return _write(author, change)


@app.put("/rules/{code}", response_model=RuleChange, **docs.UPDATE)
def update_rule(code: str, body: RuleUpdate, x_user: str = Header("anonymous")):
    author = _author(x_user)

    def change(session, rules):
        before = _get(rules, code)
        try:
            after = RuleEntry(**{**before.model_dump(), **body.model_dump(),
                                 "rule_version": before.rule_version + 1})
        except ValidationError as exc:
            raise _invalid(exc) from exc
        if after.model_dump(exclude={"rule_version"}) == before.model_dump(exclude={"rule_version"}):
            raise store.NoChange(before)
        store.save(session, after, author)
        return _record("update", code, before, after), [after]

    return _write(author, change)


def _toggle(code: str, enabled: bool, x_user: str) -> RuleChange:
    author = _author(x_user)

    def change(session, rules):
        before = _get(rules, code)
        if not enabled and before.type in ALWAYS_ENABLED:
            raise HTTPException(status_code=409, detail=f"Rule '{code}' must stay enabled.")
        if before.enabled == enabled:
            raise store.NoChange(before)
        after = before.model_copy(update={"enabled": enabled, "rule_version": before.rule_version + 1})
        store.save(session, after, author)
        return _record("enable" if enabled else "disable", code, before, after), [after]

    return _write(author, change)


@app.post("/rules/{code}/enable", response_model=RuleChange, **docs.ENABLE)
def enable_rule(code: str, x_user: str = Header("anonymous")):
    return _toggle(code, True, x_user)


@app.post("/rules/{code}/disable", response_model=RuleChange, **docs.DISABLE)
def disable_rule(code: str, x_user: str = Header("anonymous")):
    return _toggle(code, False, x_user)
