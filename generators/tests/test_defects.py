from collections import Counter
from datetime import datetime
from decimal import Decimal

DEFECTOS = (2, 2, 1)


def fecha(e):
    return datetime.fromisoformat(e.payload.get("transaction_date") or e.payload["event_date"])


def test_sin_defectos_el_stream_no_cambia(generar):
    con, d = generar(defectos=(0, 0, 0))
    assert d.reporte == []
    assert all("defects" not in e.etiqueta for e in con)


def test_los_defectos_no_cambian_las_transacciones_del_core(generar):
    limpio, _ = generar()
    sucio, _ = generar(defectos=DEFECTOS)
    originales = {e.payload["id"]: e.payload for e in limpio}
    # Los mismos eventos, más los reenvíos.
    assert {e.payload["id"] for e in sucio} == set(originales)
    for e in sucio:
        o = originales[e.payload["id"]]
        if "amount" in o:
            assert Decimal(e.payload["amount"]) == Decimal(o["amount"])
        assert {k: v for k, v in e.payload.items() if k != "amount"} == {
            k: v for k, v in o.items() if k != "amount"
        }


def test_hay_de_los_tres_defectos_y_quedan_en_el_reporte(generar):
    eventos, d = generar(cantidad=2_000, defectos=DEFECTOS)
    tipos = Counter(r["defect"] for r in d.reporte)
    assert set(tipos) == {"DUPLICATE", "OUT_OF_ORDER", "DECIMAL_PRECISION"}
    # Un reenvío copia también los defectos del original; de él solo se
    # cuenta el reenvío.
    marcados = Counter()
    for e in eventos:
        defectos = e.etiqueta.get("defects", [])
        marcados.update(["DUPLICATE"] if e.etiqueta.get("duplicate") else defectos)
    assert marcados == tipos


def test_un_reenvio_es_identico_al_original(generar):
    eventos, _ = generar(defectos=DEFECTOS)
    por_id = {}
    for e in eventos:
        por_id.setdefault(e.payload["id"], []).append(e)
    reenvios = [v for v in por_id.values() if len(v) > 1]
    assert reenvios
    for original, copia in reenvios:
        assert copia.etiqueta.get("duplicate") and not original.etiqueta.get("duplicate")
        assert copia.payload == original.payload


def test_un_evento_desordenado_llega_despues_de_uno_mas_reciente(generar):
    eventos, _ = generar(defectos=DEFECTOS)
    for i, e in enumerate(eventos):
        if "OUT_OF_ORDER" in e.etiqueta.get("defects", []):
            assert any(fecha(x) > fecha(e) for x in eventos[:i])


def test_precision_agrega_decimales_sin_cambiar_el_valor(generar):
    eventos, _ = generar(cantidad=2_000, defectos=DEFECTOS)
    con_defecto = [e for e in eventos if "DECIMAL_PRECISION" in e.etiqueta.get("defects", [])]
    assert con_defecto
    for e in con_defecto:
        decimales = -Decimal(e.payload["amount"]).as_tuple().exponent
        esperados = 0 if e.payload["currency"] == "JPY" else 2
        assert decimales > esperados
