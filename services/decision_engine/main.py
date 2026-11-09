import logging
from contextlib import asynccontextmanager

import valkey
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.decision_engine import currency, publisher, security_events
from services.decision_engine.decision_service import (
    InvalidReference,
    process_transaction,
)
from services.decision_engine.docs.app import APP
from services.decision_engine.docs.health import HEALTH
from services.decision_engine.docs.security import (
    RECORD_SECURITY_EVENT,
    SECURITY_REQUEST_EXAMPLES,
)
from services.decision_engine.docs.transactions import EVALUATE, REQUEST_EXAMPLES
from services.decision_engine.idempotency import EnProceso, IdReutilizado
from services.decision_engine.schemas import (
    HealthResponse,
    SecurityEventRequest,
    SecurityEventResponse,
    TransactionRequest,
    TransactionResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# The decision lines (HU-59) are bare JSON, so CloudWatch metric filters
# and Logs Insights read their fields: no prefix, not repeated by root.
_decisions_handler = logging.StreamHandler()
_decisions_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger("securepay.decisions").addHandler(_decisions_handler)
logging.getLogger("securepay.decisions").propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # HU-42: the day's exchange rates, in memory before the first decision.
    currency.start()
    yield
    currency.stop()
    # Al apagar: publica lo que quedó en memoria antes de salir.
    publisher.detener()


app = FastAPI(**APP, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://securepay-riwi.github.io",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
_default_openapi = app.openapi


def openapi() -> dict:
    """FastAPI documents a 422 for every endpoint with a body, but an
    invalid body gets 400 here (validation_exception_handler). Drop it
    where the endpoint never answers 422."""
    schema = _default_openapi()
    schema["paths"]["/security-events"]["post"]["responses"].pop("422", None)
    return schema


app.openapi = openapi


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    return JSONResponse(
        status_code=400,
        content={
            "detail": "La solicitud contiene datos inválidos.",
            # Los errores del validador traen la excepción original,
            # que JSONResponse no sabe convertir por sí solo.
            "errors": jsonable_encoder(exc.errors()),
        },
    )


@app.get("/health", response_model=HealthResponse, **HEALTH)
def health_check():
    # La mensajería no cambia el "ok": si SNS falla, el motor sigue
    # decidiendo y el balanceador no debe sacarlo de servicio.
    return {"status": "ok", "messaging": publisher.estado()}


@app.post("/transactions", response_model=TransactionResponse, **EVALUATE)
def evaluate_transaction(
    payload: TransactionRequest = Body(openapi_examples=REQUEST_EXAMPLES),
):
    # The engine reads accounts, merchants and the restricted list from
    # the cache (HU-67): it has no database session.
    try:
        resultado, replay = process_transaction(payload)

        return TransactionResponse(**resultado, idempotent_replay=replay)

    except EnProceso as exc:
        raise HTTPException(
            status_code=409,
            detail="La transacción con este id todavía se está procesando.",
        ) from exc

    except IdReutilizado as exc:
        raise HTTPException(
            status_code=409,
            detail="El id ya se usó con otro contenido.",
        ) from exc

    except InvalidReference as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except valkey.exceptions.ConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="El servicio de idempotencia no está disponible.",
        ) from exc


@app.post(
    "/security-events",
    response_model=SecurityEventResponse,
    **RECORD_SECURITY_EVENT,
)
def record_security_event(
    payload: SecurityEventRequest = Body(openapi_examples=SECURITY_REQUEST_EXAMPLES),
):
    try:
        security_events.record(payload)
    except valkey.exceptions.ConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="The security event store is not available.",
        ) from exc

    return SecurityEventResponse(recorded=True)
