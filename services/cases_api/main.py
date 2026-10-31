"""Cases API (Sprint 4): what the analyst sees and does with a case.

The consumers create the cases, this API reads them and changes their
state on the analyst's request (assign, resolve), and the alerts task
escalates them. The tables and states are shared/cases.py; each route
file belongs to one story:

    routes_cases.py       inbox, detail, assign, resolve (HU-26, HU-27, HU-30)
    routes_reports.py     suspicious operations report (HU-35)
    routes_accounts.py    account history, related accounts (HU-28, HU-29)
    routes_compliance.py  restricted list reports (HU-34)

Routes get their session and the X-User header from deps.py.
"""

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from services.cases_api import (
    deps,
    docs,
    routes_accounts,
    routes_cases,
    routes_compliance,
    routes_reports,
)
from services.cases_api.schemas import Health
from shared.cases import create_schema

logger = logging.getLogger(__name__)

INVALID = "The request contains invalid data."


@asynccontextmanager
async def lifespan(app: FastAPI):
    with deps.SessionLocal() as session:
        create_schema(session)
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
    logger.warning("Cases API could not reach PostgreSQL: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "The cases database is not available."})


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    body = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/health", response_model=Health, **docs.HEALTH)
def health_check(session: Annotated[Session, Depends(deps.get_session)]):
    session.execute(text("SELECT 1"))
    return Health(status="ok")


app.include_router(routes_cases.router)
app.include_router(routes_reports.router)
app.include_router(routes_accounts.router)
app.include_router(routes_compliance.router)
