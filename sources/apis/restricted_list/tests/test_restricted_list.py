"""Pruebas del servicio simulado de listas restrictivas.

No necesitan base ni LocalStack: leen un archivo temporal con el mismo
formato que exporta el seed. La prueba contra S3 se omite si LocalStack
no está levantado.
"""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sources.apis.restricted_list.config import Config
from sources.apis.restricted_list.lista import normalizar, parsear
from sources.apis.restricted_list.main import create_app
from sources.apis.restricted_list.proveedor import ProveedorSimulado

REGISTROS = [
    {"documento": "1000000016", "tipo": "sanciones", "fecha_inclusion": "2023-04-11"},
    {"documento": "10000005", "tipo": "PEP", "fecha_inclusion": "2022-01-30"},
]


@pytest.fixture
def archivo(tmp_path) -> Path:
    ruta = tmp_path / "lista_restrictiva.jsonl"
    ruta.write_text("".join(json.dumps(r) + "\n" for r in REGISTROS), encoding="utf-8")
    return ruta


def cliente(archivo, **cambios) -> TestClient:
    """Cliente sin latencia ni caídas, salvo que la prueba las pida."""
    valores = {"archivo": archivo, "latencia_min_ms": 0, "latencia_max_ms": 0, "falla_pct": 0}
    valores.update(cambios)
    return TestClient(create_app(Config(**valores)))


@pytest.mark.parametrize(
    "escrito",
    ["1000000016", "1.000.000.016", "CC 1000000016", "CC1.000.000.016", " 1000 000 016 "],
)
def test_normaliza_los_formatos_del_seed(escrito):
    assert normalizar(escrito) == "1000000016"


def test_documento_listado(archivo):
    with cliente(archivo) as c:
        r = c.get("/lista/CC 1.000.000.016")
    assert r.status_code == 200
    assert r.json() == {
        "listado": True,
        "documento": "1000000016",
        "tipo": "sanciones",
        "fecha_inclusion": "2023-04-11",
    }


def test_documento_no_listado_es_200(archivo):
    with cliente(archivo) as c:
        r = c.get("/lista/1000000099")
    assert r.status_code == 200
    assert r.json() == {"documento": "1000000099", "listado": False}


def test_documento_sin_digitos_es_400(archivo):
    with cliente(archivo) as c:
        assert c.get("/lista/abc").status_code == 400


def test_lista_completa(archivo):
    with cliente(archivo) as c:
        r = c.get("/lista")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] == 2
    assert {x["documento"] for x in cuerpo["registros"]} == {"1000000016", "10000005"}


def test_caido_responde_503(archivo):
    with cliente(archivo, falla_pct=100) as c:
        assert c.get("/lista/1000000016").status_code == 503
        assert c.get("/lista").status_code == 503
        # /health no simula caídas: el servicio sigue vivo.
        assert c.get("/health").json() == {"status": "ok", "total": 2}


def test_latencia_simulada(archivo):
    with cliente(archivo, latencia_min_ms=200, latencia_max_ms=250) as c:
        inicio = time.perf_counter()
        c.get("/lista/1000000016")
        assert time.perf_counter() - inicio >= 0.2

        inicio = time.perf_counter()
        c.get("/health")
        assert time.perf_counter() - inicio < 0.2


def test_sorteo_dentro_de_rango_y_reproducible():
    config = Config(latencia_min_ms=50, latencia_max_ms=3000, falla_pct=5, semilla=7)
    p1, p2 = ProveedorSimulado(config), ProveedorSimulado(config)
    sorteos = [p1.sortear() for _ in range(2000)]

    assert sorteos[:50] == [p2.sortear() for _ in range(50)]
    assert all(0.05 <= espera <= 3.0 for espera, _ in sorteos)
    caidas = sum(falla for _, falla in sorteos) / len(sorteos) * 100
    assert 3 <= caidas <= 7


def test_no_arranca_sin_archivo(tmp_path):
    with pytest.raises(FileNotFoundError):
        with cliente(tmp_path / "no_existe.jsonl"):
            pass


def test_linea_invalida_falla_claro():
    with pytest.raises(ValueError, match="Línea 2"):
        parsear('{"documento": "1"}\n{"tipo": "PEP"}\n')


@pytest.mark.parametrize(
    "cambios",
    [{"fuente": "ftp"}, {"latencia_min_ms": 10, "latencia_max_ms": 5}, {"falla_pct": 101}],
)
def test_config_invalida(cambios):
    with pytest.raises(ValueError):
        Config(**cambios).validar()


def test_lee_de_s3_en_localstack(archivo):
    import boto3

    s3 = boto3.client("s3", region_name="us-east-2")
    bucket = "pagoseguro-proveedor-listas"
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        pytest.skip("LocalStack no está disponible (docker compose up -d)")

    clave = "pruebas/lista_restrictiva.jsonl"
    s3.put_object(Bucket=bucket, Key=clave, Body=archivo.read_bytes())
    try:
        with cliente(archivo, fuente="s3", bucket=bucket, clave_s3=clave) as c:
            assert c.get("/lista/1000000016").json()["listado"] is True
    finally:
        s3.delete_object(Bucket=bucket, Key=clave)
