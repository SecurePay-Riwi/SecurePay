"""API del servicio simulado de listas restrictivas (bitácora 3.12).

- GET /lista: la lista completa. La usa la Lambda diaria que carga la
  lista en la caché del motor.
- GET /lista/{documento}: si un documento está listado. El motor la usa
  solo si la caché no está disponible.
- GET /health: sin latencia ni caídas, para el balanceador y el Compose.

La lista se carga en memoria una sola vez al arrancar, sin refresco: con
la misma semilla el seed produce siempre la misma lista. Si cambia, se
reinicia el servicio. En AWS es API Gateway + Lambda fuera de la VPC.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from sources.apis.restricted_list.config import Config, leer_config
from sources.apis.restricted_list.lista import cargar, normalizar
from sources.apis.restricted_list.proveedor import ProveedorSimulado


def create_app(config: Config | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = config or leer_config()
        # Si la lista no se puede leer, el servicio no arranca: es mejor
        # fallar claro que responder "no está listado" para todos.
        app.state.lista = cargar(cfg)
        app.state.proveedor = ProveedorSimulado(cfg)
        print(f"Lista restrictiva cargada: {len(app.state.lista)} personas")
        yield

    app = FastAPI(title="Proveedor de listas restrictivas (simulado)", lifespan=lifespan)

    @app.get("/health")
    def health(request: Request):
        return {"status": "ok", "total": len(request.app.state.lista)}

    @app.get("/lista")
    async def lista_completa(request: Request):
        await request.app.state.proveedor.simular()
        registros = list(request.app.state.lista.values())
        return {"total": len(registros), "registros": registros}

    @app.get("/lista/{documento}")
    async def consultar(documento: str, request: Request):
        await request.app.state.proveedor.simular()
        doc = normalizar(documento)
        if not doc:
            raise HTTPException(status_code=400, detail="El documento no tiene dígitos")
        registro = request.app.state.lista.get(doc)
        # Siempre 200 si el proveedor respondió: "no está" no es un 404,
        # para no confundirlo con una ruta mal escrita.
        if registro is None:
            return {"documento": doc, "listado": False}
        return {"listado": True, **registro}

    return app


app = create_app()
