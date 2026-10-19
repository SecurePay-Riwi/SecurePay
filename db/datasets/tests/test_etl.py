"""Pruebas del ETL de datasets históricos. No usan base de datos ni los CSV reales."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from shared.config import CANALES
from db.datasets.config import (
    CATEGORIA_FRAUDTEST,
    FRAUDTEST_DESPLAZAMIENTO,
    PAYSIM_INICIO,
    TIPO_PAYSIM,
)
from db.datasets.config import ARCHIVOS, carpeta_raw
from db.datasets.extract import muestrear_fraudtest, muestrear_paysim
from db.datasets.transform import (
    Dimensiones,
    huella,
    transformar_fraudtest,
    transformar_paysim,
)

NS = uuid.UUID("12345678-1234-5678-1234-567812345678")
REFERENCIA = datetime(2026, 10, 1)


# --- Datos de prueba -------------------------------------------------------

def escribir_paysim(ruta, filas=600):
    """600 filas: una de cada 20 es fraude; una tiene monto 0 (se descarta)."""
    tipos = list(TIPO_PAYSIM)
    lineas = ["step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,"
              "nameDest,oldbalanceDest,newbalanceDest,isFraud,isFlaggedFraud"]
    for i in range(filas):
        monto = "0.0" if i == 7 else f"{100 + i}.25"
        fraude = 1 if i % 20 == 0 else 0
        # 40 cuentas origen que se repiten, para probar que cada una va a un solo usuario.
        lineas.append(f"{1 + i // 10},{tipos[i % 5]},{monto},C{i % 40},0,0,M{i},0,0,{fraude},0")
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def escribir_fraudtest(ruta, filas=400):
    categorias = list(CATEGORIA_FRAUDTEST)
    inicio = datetime(2020, 6, 21, 12, 0, 0)
    lineas = ["idx,trans_date_trans_time,cc_num,category,amt,is_fraud"]
    for i in range(filas):
        fecha = inicio + timedelta(minutes=37 * i)
        fraude = 1 if i % 25 == 0 else 0
        # 12 tarjetas que se repiten.
        tarjeta = 4000_0000_0000_0000 + i % 12
        lineas.append(f"{i},{fecha:%Y-%m-%d %H:%M:%S},{tarjeta},{categorias[i % 14]},{10 + i}.50,{fraude}")
    # fraudTest viene con saltos de línea de Windows.
    ruta.write_bytes(("\r\n".join(lineas) + "\r\n").encode("utf-8"))


def dimensiones():
    """3 usuarios con 1 o 2 dispositivos y 6 comercios activos de 3 categorías."""
    def uid(x):
        return uuid.uuid5(NS, x)

    # Todos existen antes de las fechas del ETL salvo "tardio".
    d = {
        uid("u0"): ((datetime(2024, 1, 1), uid("d0a")), (datetime(2025, 5, 1), uid("d0b"))),
        uid("u1"): ((datetime(2025, 1, 1), uid("d1a")),),
        uid("tardio"): ((datetime(2026, 9, 20), uid("dt")),),
    }
    usuarios = tuple(sorted(((v[0][0], u) for u, v in d.items()), key=lambda x: x[0]))
    comercios = tuple(sorted(
        [
            (datetime(2024, 3, 1), uid("m0"), "alimentos"),
            (datetime(2024, 3, 2), uid("m1"), "alimentos"),
            (datetime(2024, 4, 1), uid("m2"), "retail"),
            (datetime(2024, 5, 1), uid("m3"), "salud"),
            (datetime(2024, 6, 1), uid("m4"), "servicios"),
            (datetime(2026, 9, 25), uid("mnuevo"), "tecnologia"),
        ],
        key=lambda x: x[0],
    ))
    return Dimensiones(usuarios=usuarios, dispositivos=d, comercios=comercios), uid("tardio")


# --- Extracción ------------------------------------------------------------

def test_muestra_paysim_tiene_la_cantidad_exacta_de_fraudes(tmp_path):
    ruta = tmp_path / "paysim.csv"
    escribir_paysim(ruta)
    m = muestrear_paysim(ruta, total=100, fraude_pct=10)
    assert len(m.filas) == 100
    assert m.fraude == 10


def test_descarta_montos_en_cero(tmp_path):
    ruta = tmp_path / "paysim.csv"
    escribir_paysim(ruta)
    m = muestrear_paysim(ruta, total=100, fraude_pct=10)
    assert m.descartadas == 1
    assert all(f.monto > 0 for f in m.filas)


def test_misma_semilla_misma_muestra(tmp_path):
    ruta = tmp_path / "paysim.csv"
    escribir_paysim(ruta)
    a = muestrear_paysim(ruta, 100, 10)
    b = muestrear_paysim(ruta, 100, 10)
    assert [f.indice for f in a.filas] == [f.indice for f in b.filas]


def test_otra_semilla_otra_muestra(tmp_path, monkeypatch):
    import db.datasets.extract as extract

    ruta = tmp_path / "paysim.csv"
    escribir_paysim(ruta)
    a = muestrear_paysim(ruta, 100, 10)

    import random
    monkeypatch.setattr(
        extract, "nuevo_rng",
        lambda dataset, proposito: random.Random(f"otra:{dataset}:{proposito}"),
    )
    b = muestrear_paysim(ruta, 100, 10)
    assert [f.indice for f in a.filas] != [f.indice for f in b.filas]


def test_muestra_queda_en_el_orden_del_archivo(tmp_path):
    ruta = tmp_path / "paysim.csv"
    escribir_paysim(ruta)
    m = muestrear_paysim(ruta, 100, 10)
    indices = [f.indice for f in m.filas]
    assert indices == sorted(indices)


def test_si_faltan_fraudes_usa_los_que_hay(tmp_path):
    ruta = tmp_path / "paysim.csv"
    escribir_paysim(ruta)  # 30 fraudes en total
    m = muestrear_paysim(ruta, total=200, fraude_pct=50)  # pide 100
    assert m.fraude == 30
    assert m.pedidas_fraude == 100


def test_lee_fraudtest_con_saltos_de_linea_de_windows(tmp_path):
    ruta = tmp_path / "fraudTest.csv"
    escribir_fraudtest(ruta)
    m = muestrear_fraudtest(ruta, total=100, fraude_pct=10)
    assert len(m.filas) == 100 and m.fraude == 10
    assert all(isinstance(f.fecha, datetime) for f in m.filas)


# --- Transformación --------------------------------------------------------

def lote_paysim(tmp_path, total=200):
    ruta = tmp_path / "paysim.csv"
    escribir_paysim(ruta)
    dims, _ = dimensiones()
    m = muestrear_paysim(ruta, total, 10)
    return transformar_paysim(m.filas, dims), dims


def lote_fraudtest(tmp_path, total=200):
    ruta = tmp_path / "fraudTest.csv"
    escribir_fraudtest(ruta)
    dims, _ = dimensiones()
    m = muestrear_fraudtest(ruta, total, 10)
    return transformar_fraudtest(m.filas, dims), dims


def test_transformar_es_reproducible(tmp_path):
    a, _ = lote_paysim(tmp_path)
    b, _ = lote_paysim(tmp_path)
    assert huella(a.filas) == huella(b.filas)


def test_la_huella_cambia_si_cambia_un_dato(tmp_path):
    lote, _ = lote_paysim(tmp_path)
    original = huella(lote.filas)
    lote.filas[0]["amount"] += Decimal("0.01")
    assert huella(lote.filas) != original


def test_ids_deterministas_y_sin_repetir(tmp_path):
    lote, _ = lote_paysim(tmp_path)
    ids = [f["id"] for f in lote.filas]
    assert len(set(ids)) == len(ids)


def test_el_dispositivo_es_del_usuario_y_ya_existia(tmp_path):
    for lote, dims in (lote_paysim(tmp_path), lote_fraudtest(tmp_path)):
        for f in lote.filas:
            propios = dict((d, fecha) for fecha, d in dims.dispositivos[f["user_id"]])
            assert f["device_id"] in propios
            fecha = f["transaction_date"].replace(tzinfo=None)
            assert fecha >= propios[f["device_id"]]


def test_el_comercio_ya_existia(tmp_path):
    for lote, dims in (lote_paysim(tmp_path), lote_fraudtest(tmp_path)):
        creacion = {m[1]: m[0] for m in dims.comercios}
        for f in lote.filas:
            assert f["transaction_date"].replace(tzinfo=None) >= creacion[f["merchant_id"]]


def test_usuario_que_nace_despues_no_recibe_transacciones_anteriores(tmp_path):
    lote, dims = lote_fraudtest(tmp_path)
    tardio = dimensiones()[1]
    for f in lote.filas:
        if f["user_id"] == tardio:
            assert f["transaction_date"].replace(tzinfo=None) >= datetime(2026, 9, 20)


def test_fechas_de_paysim_y_fraudtest_caen_antes_de_la_referencia(tmp_path):
    for lote, _ in (lote_paysim(tmp_path), lote_fraudtest(tmp_path)):
        for f in lote.filas:
            assert f["transaction_date"].replace(tzinfo=None) < REFERENCIA + timedelta(days=1)
            assert f["transaction_date"].tzinfo is not None


def test_fechas_paysim_parten_de_la_hora_1(tmp_path):
    lote, _ = lote_paysim(tmp_path)
    primera = lote.filas[0]["transaction_date"].replace(tzinfo=None)
    assert PAYSIM_INICIO <= primera < PAYSIM_INICIO + timedelta(hours=1, days=1)


def test_fraudtest_conserva_la_separacion_entre_transacciones(tmp_path):
    ruta = tmp_path / "fraudTest.csv"
    escribir_fraudtest(ruta)
    dims, _ = dimensiones()
    m = muestrear_fraudtest(ruta, 100, 10)
    lote = transformar_fraudtest(m.filas, dims)
    for origen, destino in zip(m.filas, lote.filas):
        esperada = origen.fecha + FRAUDTEST_DESPLAZAMIENTO
        real = destino["transaction_date"].replace(tzinfo=None)
        # Solo se adelanta si el usuario o el comercio aún no existían.
        assert real >= esperada


def test_canales_validos_segun_el_tipo(tmp_path):
    lote, _ = lote_paysim(tmp_path)
    validos = {c for canales in CANALES.values() for c in canales}
    assert {f["channel"] for f in lote.filas} <= validos
    lote, _ = lote_fraudtest(tmp_path)
    assert {f["channel"] for f in lote.filas} <= {"APP", "WEB"}


def test_fraud_pattern_solo_en_fraudes_y_cabe_en_la_columna(tmp_path):
    for lote, _ in (lote_paysim(tmp_path), lote_fraudtest(tmp_path)):
        for f in lote.filas:
            if f["is_fraud"]:
                assert f["fraud_pattern"].startswith("kaggle_")
                assert len(f["fraud_pattern"]) <= 50
            else:
                assert f["fraud_pattern"] is None


def test_fraudtest_usa_comercio_de_la_categoria_equivalente_si_existe(tmp_path):
    lote, dims = lote_fraudtest(tmp_path, total=300)
    categoria = {m[1]: m[2] for m in dims.comercios}
    assert lote.categoria_respetada_pct is not None
    # Con comercios de 3 categorías y fechas posteriores a su creación, las
    # categorías que existen en el seed siempre se respetan.
    assert lote.categoria_respetada_pct > 50
    mapeo_ok = [
        categoria[f["merchant_id"]] in set(CATEGORIA_FRAUDTEST.values())
        for f in lote.filas
    ]
    assert all(mapeo_ok)


def test_cada_dataset_tiene_su_propio_azar(tmp_path):
    """Cambiar el tamaño de PaySim no mueve los datos de fraudTest."""
    ruta = tmp_path / "fraudTest.csv"
    escribir_fraudtest(ruta)
    dims, _ = dimensiones()
    m = muestrear_fraudtest(ruta, 100, 10)
    a = huella(transformar_fraudtest(m.filas, dims).filas)

    # Se transforma PaySim en medio; no debe afectar a fraudTest.
    ruta_p = tmp_path / "paysim.csv"
    escribir_paysim(ruta_p)
    transformar_paysim(muestrear_paysim(ruta_p, 300, 10).filas, dims)
    b = huella(transformar_fraudtest(m.filas, dims).filas)
    assert a == b


def test_cada_titular_queda_ligado_a_un_solo_usuario(tmp_path):
    """Una tarjeta de Sparkov o una cuenta de PaySim no se reparte entre usuarios."""
    dims, _ = dimensiones()
    casos = (
        (escribir_paysim, "paysim.csv", muestrear_paysim, transformar_paysim),
        (escribir_fraudtest, "fraudTest.csv", muestrear_fraudtest, transformar_fraudtest),
    )
    for escribir, nombre, muestrear, transformar in casos:
        ruta = tmp_path / nombre
        escribir(ruta)
        muestra = muestrear(ruta, 200, 10)
        lote = transformar(muestra.filas, dims)
        usuarios_por_titular = {}
        for origen, destino in zip(muestra.filas, lote.filas):
            usuarios_por_titular.setdefault(origen.titular, set()).add(destino["user_id"])
        assert all(len(u) == 1 for u in usuarios_por_titular.values())
        assert {t: next(iter(u)) for t, u in usuarios_por_titular.items()} == lote.titulares
        # Hay menos titulares que filas: las tarjetas y cuentas se repiten.
        assert len(lote.titulares) < len(lote.filas)


def test_un_usuario_puede_tener_varias_tarjetas(tmp_path):
    lote, _ = lote_fraudtest(tmp_path)
    # 12 tarjetas y 3 usuarios: alguno recibe más de una.
    assert len(set(lote.titulares.values())) < len(lote.titulares)


# --- Carpeta de los CSV ----------------------------------------------------

def _con_archivos(carpeta, nombres=ARCHIVOS):
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre in nombres:
        (carpeta / nombre).write_text("x")
    return carpeta


def test_carpeta_raw_prefiere_la_primera_que_tiene_los_dos_archivos(tmp_path, monkeypatch):
    monkeypatch.delenv("HIST_RAW_DIR", raising=False)
    a, b = tmp_path / "a", tmp_path / "b"
    _con_archivos(a)
    _con_archivos(b)
    assert carpeta_raw(candidatas=(a, b)) == a


def test_carpeta_raw_usa_la_segunda_si_la_primera_esta_vacia(tmp_path, monkeypatch):
    monkeypatch.delenv("HIST_RAW_DIR", raising=False)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    _con_archivos(b)
    assert carpeta_raw(candidatas=(a, b)) == b


def test_carpeta_raw_exige_los_dos_archivos_juntos(tmp_path, monkeypatch):
    """Un CSV en cada carpeta no sirve: se devuelve la primera para que el error la nombre."""
    monkeypatch.delenv("HIST_RAW_DIR", raising=False)
    a, b = tmp_path / "a", tmp_path / "b"
    _con_archivos(a, ARCHIVOS[:1])
    _con_archivos(b, ARCHIVOS[1:])
    assert carpeta_raw(candidatas=(a, b)) == a


def test_carpeta_raw_manda_lo_explicito(tmp_path, monkeypatch):
    a = _con_archivos(tmp_path / "a")
    monkeypatch.setenv("HIST_RAW_DIR", str(tmp_path / "desde_env"))
    assert carpeta_raw(candidatas=(a,)) == tmp_path / "desde_env"
    assert carpeta_raw(explicita=tmp_path / "x", candidatas=(a,)) == tmp_path / "x"
