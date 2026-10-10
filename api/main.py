
from collections.abc import Generator

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from seeds.db import get_session
from api.schemas import TransactionRequest, TransactionResponse
from api.services.decision_service import process_transaction
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(
    title="SecurePay Antifraude API",
    version="1.0.0",
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    return JSONResponse(
        status_code=400,
        content={
            "detail": "La solicitud contiene datos inválidos.",
            "errors": exc.errors(),
        },
    )

def get_db() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post(
    "/transactions",
    response_model=TransactionResponse,
    status_code=200,
)
def evaluate_transaction(
    payload: TransactionRequest,
    session: Session = Depends(get_db),
):
    try:
        transaction, replay = process_transaction(session, payload)

        return TransactionResponse(
            transaction_id=transaction.id,
            decision=transaction.decision,
            decision_reason=transaction.decision_reason,
            processed_at=transaction.processed_at,
            idempotent_replay=replay,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflicto al guardar la transacción.",
        ) from exc

    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=500,
            detail="Error interno al procesar la transacción.",
        ) from exc
