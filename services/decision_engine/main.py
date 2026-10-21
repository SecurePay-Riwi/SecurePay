
import logging
from collections.abc import Generator
from contextlib import asynccontextmanager

import valkey
from fastapi import Body, Depends, FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from shared.db import get_session
from services.decision_engine.docs.app import APP
from services.decision_engine.docs.health import HEALTH
from services.decision_engine.docs.transactions import EVALUATE, REQUEST_EXAMPLES
from services.decision_engine.schemas import (
    HealthResponse,
    TransactionRequest,
    TransactionResponse,
)
from services.decision_engine.decision_service import (
    LATE_SESSION,
    InvalidReference,
    process_transaction,
)
from services.decision_engine import publisher
from services.decision_engine.idempotency import EnProceso, IdReutilizado
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Al apagar: publica lo que quedó en memoria antes de salir.
    publisher.detener()


app = FastAPI(**APP, lifespan=lifespan)

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

def get_db() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        # A decision that timed out still uses the session in the
        # background and closes it itself when it ends.
        if not session.info.get(LATE_SESSION):
            session.close()


@app.get("/health", response_model=HealthResponse, **HEALTH)
def health_check():
    # La mensajería no cambia el "ok": si SNS falla, el motor sigue
    # decidiendo y el balanceador no debe sacarlo de servicio.
    return {"status": "ok", "messaging": publisher.estado()}


@app.post("/transactions", response_model=TransactionResponse, **EVALUATE)
def evaluate_transaction(
    payload: TransactionRequest = Body(openapi_examples=REQUEST_EXAMPLES),
    session: Session = Depends(get_db),
):
    try:
        resultado, replay = process_transaction(session, payload)

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

    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=500,
            detail="Error interno al procesar la transacción.",
        ) from exc
