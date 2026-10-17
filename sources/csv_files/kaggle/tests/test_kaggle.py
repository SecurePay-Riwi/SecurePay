"""Pruebas de la carga de los datasets de Kaggle.

Las pruebas unitarias no descargan de Kaggle, no necesitan token ni
internet: usan CSV pequeños en tmp_path y un S3 de mentira. La prueba de
integración (al final, marcada `integracion`) usa LocalStack y se salta
sola si no está levantado.
"""

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from shared.aws import cliente
from sources.csv_files.kaggle import config
from sources.csv_files.kaggle.download import asegurar_descargado
from sources.csv_files.kaggle.upload import (
    SUBIDO,
    YA_CARGADO,
    ErrorValidacion,
    construir_manifiesto,
    inspeccionar,
    subir,
    validar,
)

COLUMNAS = ("a", "b", "c")
CAMPOS_MANIFIESTO = {
    "dataset",
    "archivo_original",
    "filas",
    "columnas",
    "sha256",
    "bytes",
    "cargado_en",
}

# Dataset de prueba: 3 columnas y 4 filas, rutas de S3 aparte de las reales.
PRUEBA = config.Dataset(
    clave="prueba",
    dataset="dueño/prueba",
    archivo="prueba.csv",
    filas=4,
    columnas=COLUMNAS,
    clave_s3="raw/kaggle/prueba/prueba.csv",
)


def escribir_csv(carpeta, columnas=COLUMNAS, filas=4, nombre="prueba.csv"):
    ruta = carpeta / nombre
    lineas = [",".join(columnas)] + [f"{i},x{i},{i * 1.5}" for i in range(filas)]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


class S3Falso:
    """Imita lo mínimo de boto3 que usa upload.py y guarda lo subido."""

    def __init__(self, falla_csv=False, falla_manifiesto=False):
        self.objetos: dict[str, bytes] = {}
        self.llamadas: list[str] = []
        self.falla_csv = falla_csv
        self.falla_manifiesto = falla_manifiesto

    @staticmethod
    def _error(codigo, operacion):
        return ClientError({"Error": {"Code": codigo, "Message": codigo}}, operacion)

    def upload_file(self, ruta, bucket, clave):
        self.llamadas.append("upload_file")
        if self.falla_csv:
            raise self._error("InternalError", "UploadFile")
        with open(ruta, "rb") as f:
            self.objetos[clave] = f.read()

    def put_object(self, Bucket, Key, Body, **_):
        self.llamadas.append("put_object")
        if self.falla_manifiesto:
            raise self._error("InternalError", "PutObject")
        self.objetos[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objetos:
            raise self._error("NoSuchKey", "GetObject")

        class Cuerpo:
            def __init__(self, datos):
                self.datos = datos

            def read(self):
                return self.datos

        return {"Body": Cuerpo(self.objetos[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objetos:
            raise self._error("404", "HeadObject")
        return {"ContentLength": len(self.objetos[Key])}


# --- Validación ------------------------------------------------------------


def test_valid_csv_passes_validation(tmp_path):
    ruta = escribir_csv(tmp_path)
    columnas, filas, sha = validar(PRUEBA, ruta)
    assert columnas == list(COLUMNAS)
    assert filas == 4
    assert len(sha) == 64


def test_columns_in_wrong_order_fail(tmp_path):
    ruta = escribir_csv(tmp_path, columnas=("b", "a", "c"))
    with pytest.raises(ErrorValidacion, match="otro orden"):
        validar(PRUEBA, ruta)


def test_missing_column_fails(tmp_path):
    ruta = escribir_csv(tmp_path, columnas=("a", "b"))
    with pytest.raises(ErrorValidacion, match="faltan"):
        validar(PRUEBA, ruta)


def test_wrong_row_count_fails(tmp_path):
    ruta = escribir_csv(tmp_path, filas=3)
    with pytest.raises(ErrorValidacion, match="3 filas"):
        validar(PRUEBA, ruta)


def test_missing_file_fails(tmp_path):
    with pytest.raises(ErrorValidacion, match="no existe"):
        validar(PRUEBA, tmp_path / "no_esta.csv")


def test_header_only_file_counts_zero_rows(tmp_path):
    ruta = escribir_csv(tmp_path, filas=0)
    assert inspeccionar(ruta)[1] == 0


def test_real_contracts_match_the_guide():
    paysim, sparkov = config.PAYSIM, config.FRAUDTEST
    assert len(paysim.columnas) == 11 and paysim.filas == 6_362_620
    assert paysim.columnas[0] == "step" and paysim.columnas[-1] == "isFlaggedFraud"
    assert sparkov.dataset == "kartik2112/fraud-detection"
    assert sparkov.archivo == "fraudTest.csv" and sparkov.filas == 555_719
    assert len(sparkov.columnas) == 23
    # La primera columna del CSV no tiene nombre (índice de pandas).
    assert sparkov.columnas[:2] == ("", "trans_date_trans_time")
    assert sparkov.columnas[-2:] == ("merch_long", "is_fraud")
    assert paysim.clave_s3 == "raw/kaggle/paysim/paysim.csv"
    assert paysim.clave_manifiesto == "raw/kaggle/paysim/_manifest.json"
    assert sparkov.clave_s3 == "raw/kaggle/sparkov/fraudtest/fraudTest.csv"
    assert sparkov.clave_manifiesto == "raw/kaggle/sparkov/fraudtest/_manifest.json"


def test_contract_has_exactly_paysim_and_fraudtest():
    assert [d.dataset for d in config.DATASETS] == [
        "ealaxi/paysim1",
        "kartik2112/fraud-detection",
    ]


def test_no_dataset_in_the_contract_has_anonymized_columns():
    """El dataset de tarjetas con columnas V1..V28 se descartó por decisión del
    equipo (sin tarjeta, comercio ni secuencia no se puede medir ninguna regla).
    Esta prueba evita que vuelva a colarse en el contrato."""
    for ds in config.DATASETS:
        anonimas = [c for c in ds.columnas if c[:1] == "V" and c[1:].isdigit()]
        assert not anonimas, f"{ds.clave} tiene columnas anonimizadas: {anonimas}"
    assert not hasattr(config, "CREDITCARD")


def test_creditcard_does_not_pass_as_fraudtest(tmp_path):
    """creditcard.csv (mlg-ulb/creditcardfraud, Time, V1..V28, Amount, Class)
    es otro dataset: aunque tenga el nombre correcto, no pasa la validación."""
    ruta = tmp_path / config.FRAUDTEST.archivo
    columnas = ["Time", *(f"V{i}" for i in range(1, 29)), "Amount", "Class"]
    ruta.write_text(",".join(columnas) + "\n" + ",".join(["0"] * 31) + "\n")
    with pytest.raises(ErrorValidacion, match="encabezado"):
        validar(config.FRAUDTEST, ruta)


def test_fraudtest_header_with_unnamed_first_column_passes(tmp_path):
    """La primera columna sin nombre no debe confundir a la validación."""
    ruta = tmp_path / config.FRAUDTEST.archivo
    fila = ",".join(["0"] * len(config.FRAUDTEST.columnas))
    ruta.write_text(",".join(config.FRAUDTEST.columnas) + "\n" + fila + "\n")
    assert inspeccionar(ruta)[0] == list(config.FRAUDTEST.columnas)
    # Solo falla por el número de filas, no por el encabezado.
    with pytest.raises(ErrorValidacion, match="1 filas"):
        validar(config.FRAUDTEST, ruta)


# --- Hash y manifiesto -----------------------------------------------------


def test_sha256_is_correct(tmp_path):
    ruta = escribir_csv(tmp_path)
    esperado = hashlib.sha256(ruta.read_bytes()).hexdigest()
    assert inspeccionar(ruta)[2] == esperado


def test_manifest_has_all_required_fields(tmp_path):
    ruta = escribir_csv(tmp_path)
    columnas, filas, sha = validar(PRUEBA, ruta)
    m = construir_manifiesto(PRUEBA, columnas, filas, sha, ruta.stat().st_size)

    assert set(m) == CAMPOS_MANIFIESTO
    assert m["dataset"] == "dueño/prueba"
    assert m["archivo_original"] == "prueba.csv"
    assert m["filas"] == 4
    assert m["columnas"] == list(COLUMNAS)
    assert m["sha256"] == sha
    assert m["bytes"] == ruta.stat().st_size
    assert m["cargado_en"].endswith("Z")


# --- Subida e idempotencia -------------------------------------------------


def test_first_upload_writes_csv_then_manifest(tmp_path):
    ruta, s3 = escribir_csv(tmp_path), S3Falso()
    r = subir(PRUEBA, ruta, s3, "bucket")

    assert r.estado == SUBIDO and r.filas == 4
    assert s3.llamadas == ["upload_file", "put_object"]  # primero el CSV
    assert s3.objetos[PRUEBA.clave_s3] == ruta.read_bytes()
    manifiesto = json.loads(s3.objetos[PRUEBA.clave_manifiesto])
    assert set(manifiesto) == CAMPOS_MANIFIESTO


def test_same_hash_is_not_uploaded_again(tmp_path):
    ruta, s3 = escribir_csv(tmp_path), S3Falso()
    subir(PRUEBA, ruta, s3, "bucket")
    s3.llamadas.clear()

    r = subir(PRUEBA, ruta, s3, "bucket")

    assert r.estado == YA_CARGADO
    assert s3.llamadas == []


def test_different_hash_is_uploaded(tmp_path):
    ruta, s3 = escribir_csv(tmp_path), S3Falso()
    subir(PRUEBA, ruta, s3, "bucket")
    sha_anterior = json.loads(s3.objetos[PRUEBA.clave_manifiesto])["sha256"]

    ruta.write_text("a,b,c\n9,z,9\n8,z,8\n7,z,7\n6,z,6\n")  # mismas filas, otros datos
    r = subir(PRUEBA, ruta, s3, "bucket")

    assert r.estado == SUBIDO
    assert json.loads(s3.objetos[PRUEBA.clave_manifiesto])["sha256"] != sha_anterior
    assert s3.objetos[PRUEBA.clave_s3] == ruta.read_bytes()


def test_manifest_without_csv_in_s3_is_uploaded_again(tmp_path):
    ruta, s3 = escribir_csv(tmp_path), S3Falso()
    subir(PRUEBA, ruta, s3, "bucket")
    del s3.objetos[PRUEBA.clave_s3]  # alguien borró el CSV

    assert subir(PRUEBA, ruta, s3, "bucket").estado == SUBIDO
    assert PRUEBA.clave_s3 in s3.objetos


def test_failed_csv_upload_publishes_no_manifest(tmp_path):
    ruta, s3 = escribir_csv(tmp_path), S3Falso(falla_csv=True)
    with pytest.raises(ClientError):
        subir(PRUEBA, ruta, s3, "bucket")

    assert PRUEBA.clave_manifiesto not in s3.objetos
    assert s3.llamadas == ["upload_file"]


def test_failed_manifest_write_is_not_reported_as_success(tmp_path):
    ruta, s3 = escribir_csv(tmp_path), S3Falso(falla_manifiesto=True)
    with pytest.raises(ClientError):
        subir(PRUEBA, ruta, s3, "bucket")

    assert PRUEBA.clave_manifiesto not in s3.objetos


def test_invalid_file_uploads_nothing(tmp_path):
    ruta, s3 = escribir_csv(tmp_path, filas=2), S3Falso()
    with pytest.raises(ErrorValidacion):
        subir(PRUEBA, ruta, s3, "bucket")

    assert s3.llamadas == [] and s3.objetos == {}


def test_s3_errors_other_than_not_found_are_not_hidden(tmp_path):
    class S3SinPermiso(S3Falso):
        def get_object(self, Bucket, Key):
            raise self._error("AccessDenied", "GetObject")

    with pytest.raises(ClientError):
        subir(PRUEBA, escribir_csv(tmp_path), S3SinPermiso(), "bucket")


# --- Descarga (sin Kaggle) -------------------------------------------------


def test_existing_file_is_not_downloaded(tmp_path, monkeypatch):
    monkeypatch.delenv("KAGGLE_FORCE_DOWNLOAD", raising=False)
    escribir_csv(tmp_path)
    llamadas = []

    ruta = asegurar_descargado(PRUEBA, tmp_path, lambda *a: llamadas.append(a))

    assert ruta == tmp_path / "prueba.csv" and llamadas == []


def test_missing_file_is_downloaded(tmp_path, monkeypatch):
    monkeypatch.delenv("KAGGLE_FORCE_DOWNLOAD", raising=False)
    llamadas = []

    asegurar_descargado(PRUEBA, tmp_path, lambda *a: llamadas.append(a))

    assert llamadas == [("dueño/prueba", tmp_path, False)]


def test_force_download_redownloads(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGGLE_FORCE_DOWNLOAD", "true")
    escribir_csv(tmp_path)
    llamadas = []

    asegurar_descargado(PRUEBA, tmp_path, lambda *a: llamadas.append(a))

    assert llamadas == [("dueño/prueba", tmp_path, True)]


def test_download_without_token_fails_clearly(tmp_path, monkeypatch):
    from sources.csv_files.kaggle.download import descargar

    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="KAGGLE_API_TOKEN"):
        descargar("dueño/prueba", tmp_path)


def test_config_reads_environment(monkeypatch):
    monkeypatch.setenv("DATALAKE_BUCKET", "otro-bucket")
    monkeypatch.setenv("KAGGLE_DOWNLOAD_DIR", "otra/carpeta")
    assert config.bucket() == "otro-bucket"
    assert str(config.carpeta_descarga()) == "otra/carpeta"
    monkeypatch.delenv("KAGGLE_DOWNLOAD_DIR")
    assert str(config.carpeta_descarga()) == "data/kaggle"


# --- Integración con LocalStack (se salta sola si no está levantado) -------


@pytest.fixture
def s3_localstack():
    try:
        s3 = cliente("s3")
        s3.head_bucket(Bucket=config.bucket())
    except Exception:
        pytest.skip("LocalStack no está disponible (docker compose up -d)")
    return s3


@pytest.mark.integracion
def test_upload_and_idempotency_against_localstack(tmp_path, s3_localstack):
    # Rutas propias de la prueba: no toca raw/kaggle/paysim ni /sparkov.
    base = f"raw/kaggle/_pruebas/{uuid4().hex}"
    ds = replace(PRUEBA, clave_s3=f"{base}/prueba.csv")
    ruta = escribir_csv(tmp_path)
    bucket = config.bucket()

    try:
        assert subir(ds, ruta, s3_localstack, bucket).estado == SUBIDO
        assert subir(ds, ruta, s3_localstack, bucket).estado == YA_CARGADO

        llaves = [
            o["Key"]
            for o in s3_localstack.list_objects_v2(Bucket=bucket, Prefix=base)["Contents"]
        ]
        assert sorted(llaves) == [f"{base}/_manifest.json", f"{base}/prueba.csv"]

        cuerpo = s3_localstack.get_object(Bucket=bucket, Key=ds.clave_manifiesto)["Body"].read()
        assert json.loads(cuerpo)["sha256"] == hashlib.sha256(ruta.read_bytes()).hexdigest()
    finally:
        for llave in (ds.clave_s3, ds.clave_manifiesto):
            s3_localstack.delete_object(Bucket=bucket, Key=llave)
