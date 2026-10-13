"""El tráfico que produce el core: cantidad, orden, saldos y etiquetas."""

from collections import Counter
from datetime import datetime
from decimal import Decimal


def fecha(evento):
    p = evento.payload
    return datetime.fromisoformat(p.get("transaction_date") or p["event_date"])


def transacciones(eventos):
    return [e for e in eventos if e.tipo == "transaction"]


def test_produce_exactamente_las_transacciones_pedidas(generar):
    eventos, _ = generar(cantidad=500)
    assert len(transacciones(eventos)) == 500


def test_misma_semilla_mismos_eventos(generar):
    a, _ = generar()
    b, _ = generar()
    assert [e.payload for e in a] == [e.payload for e in b]
    assert [e.etiqueta for e in a] == [e.etiqueta for e in b]


def test_otra_semilla_otros_eventos(generar):
    a, _ = generar(semilla=1)
    b, _ = generar(semilla=2)
    assert [e.payload for e in a] != [e.payload for e in b]


def test_los_eventos_salen_en_orden_de_fecha(generar):
    eventos, _ = generar()
    fechas = [fecha(e) for e in eventos]
    assert fechas == sorted(fechas)


def test_los_ids_no_se_repiten(generar):
    eventos, _ = generar()
    ids = Counter(e.payload["id"] for e in eventos)
    assert max(ids.values()) == 1


def test_los_saldos_encadenan_y_nunca_quedan_negativos(generar):
    eventos, _ = generar()
    ultimo = {}
    for e in transacciones(eventos):
        p = e.payload
        for lado in ("source", "destination"):
            cuenta = p[f"{lado}_account_id"]
            if not cuenta:
                continue
            antes = Decimal(p[f"{lado}_balance_before"])
            despues = Decimal(p[f"{lado}_balance_after"])
            if cuenta in ultimo:
                assert antes == ultimo[cuenta]
            signo = -1 if lado == "source" else 1
            assert despues == antes + signo * Decimal(p["amount"])
            assert despues >= 0
            ultimo[cuenta] = despues


def test_cada_tipo_lleva_solo_sus_cuentas(generar):
    eventos, _ = generar()
    for e in transacciones(eventos):
        p = e.payload
        origen, destino, comercio = (
            p["source_account_id"], p["destination_account_id"], p["merchant_id"]
        )
        if p["type"] == "RECARGA":
            assert destino and not origen and not comercio
        elif p["type"] == "RETIRO":
            assert origen and not destino and not comercio
        elif p["type"] == "QR":
            assert origen and comercio and not destino
        else:
            assert origen and destino and origen != destino and not comercio


def test_los_montos_respetan_los_decimales_de_su_moneda(generar):
    eventos, _ = generar()
    for e in transacciones(eventos):
        decimales = -Decimal(e.payload["amount"]).as_tuple().exponent
        assert decimales == (0 if e.payload["currency"] == "JPY" else 2)


def test_las_etiquetas_no_viajan_al_motor(generar):
    eventos, _ = generar(defectos=(2, 2, 1))
    prohibidas = {"pattern", "pattern_id", "is_fraud", "expected_rule", "defects", "duplicate"}
    for e in eventos:
        assert not prohibidas & set(e.payload)


def test_el_fraude_queda_cerca_del_porcentaje_pedido(generar):
    for pct in (5, 20):
        tx = transacciones(generar(cantidad=2_000, fraude=pct)[0])
        real = 100 * sum(e.etiqueta["is_fraud"] for e in tx) / len(tx)
        assert abs(real - pct) < 1.5


def test_sin_fraude_solo_hay_trafico_normal(generar):
    eventos, _ = generar(fraude=0)
    patrones = {e.etiqueta["pattern"] for e in eventos}
    assert patrones <= {None, "SHARED_DEVICE"}
