"""Recalcula las reglas del motor sobre lo que genera el generador.

Es un verificador independiente: no usa los patrones, solo los eventos.
Cada evento debe disparar exactamente la regla que dice su etiqueta, y
los casos de control ninguna. Si el generador se equivoca de lado de un
umbral, esta prueba lo detecta antes de culpar al motor.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from generators import config
from generators.money import a_usd

R = config.REGLAS


def reglas_que_dispara(eventos, tasas, en_lista):
    """Devuelve, por cada evento, el conjunto de reglas que dispara."""
    salientes = defaultdict(list)  # cuenta -> [(fecha, tipo, monto_usd)]
    entrantes = defaultdict(list)  # cuenta -> [(fecha, remitente)]
    seguridad = defaultdict(list)  # cuenta -> [(fecha, tipo)]
    resultado = []

    for e in eventos:
        p = e.payload
        if e.tipo == "security":
            seguridad[p["account_id"]].append((datetime.fromisoformat(p["event_date"]), p["type"]))
            resultado.append((e, set()))
            continue

        t = datetime.fromisoformat(p["transaction_date"])
        origen, destino = p["source_account_id"], p["destination_account_id"]
        monto = Decimal(p["amount"])
        usd = a_usd(monto, p["currency"], tasas)
        reglas = set()

        if origen:
            salientes[origen].append((t, p["type"], usd))

            ventana = timedelta(minutes=R["velocidad"]["minutos"])
            p2p = [x for x, tipo, _ in salientes[origen] if tipo == "P2P" and t - x < ventana]
            if p["type"] == "P2P" and len(p2p) > R["velocidad"]["transferencias"]:
                reglas.add("velocidad")

            if p["type"] == "RETIRO":
                ventana = timedelta(minutes=R["mula"]["minutos"])
                remitentes = {r for x, r in entrantes[origen] if t - x < ventana}
                minimo = Decimal(R["mula"]["retiro_pct"]) / 100 * Decimal(p["source_balance_before"])
                if len(remitentes) >= R["mula"]["remitentes"] and monto >= minimo:
                    reglas.add("mula")

            limite = R["fraccionamiento"]["limite_usd"]
            ventana = timedelta(hours=R["fraccionamiento"]["horas"])
            dia = [u for x, _, u in salientes[origen] if t - x < ventana]
            if (
                len(dia) >= R["fraccionamiento"]["transacciones"]
                and all(u < limite for u in dia)
                and sum(dia) > limite
            ):
                reglas.add("fraccionamiento")

            ventana = timedelta(minutes=R["toma_cuenta"]["minutos"])
            recientes = {tipo for x, tipo in seguridad[origen] if timedelta(0) <= t - x < ventana}
            if usd > R["toma_cuenta"]["monto_usd"] and recientes >= {"DEVICE_CHANGE", "PASSWORD_CHANGE"}:
                reglas.add("toma_cuenta")

        if origen and destino:
            entrantes[destino].append((t, origen))
        if origen in en_lista or destino in en_lista:
            reglas.add("lista_restrictiva")

        resultado.append((e, reglas))
    return resultado


@pytest.mark.parametrize("fraude", [5, 20])
def test_cada_evento_dispara_solo_la_regla_de_su_etiqueta(generar, tasas, en_lista, fraude):
    eventos, _ = generar(cantidad=2_000, fraude=fraude)

    disparadas = Counter()
    for e, reglas in reglas_que_dispara(eventos, tasas, en_lista):
        esperada = e.etiqueta["expected_rule"]
        # El dispositivo compartido sale del seed, no de la transacción.
        if esperada == "dispositivo_compartido":
            esperada = None
        assert reglas == ({esperada} if esperada else set()), e.etiqueta
        disparadas.update(reglas)

    # En 2.000 transacciones aparecen todos los patrones.
    assert set(disparadas) == {"velocidad", "mula", "fraccionamiento", "toma_cuenta", "lista_restrictiva"}


def test_los_controles_existen_y_no_son_fraude(generar):
    eventos, _ = generar(cantidad=2_000)
    controles = [e for e in eventos if (e.etiqueta["pattern"] or "").endswith("_CONTROL")]
    nombres = {e.etiqueta["pattern"] for e in controles}
    assert nombres == {
        "VELOCITY_CONTROL", "MULE_CONTROL", "SPLITTING_CONTROL", "ACCOUNT_TAKEOVER_CONTROL"
    }
    assert not any(e.etiqueta["is_fraud"] or e.etiqueta["expected_rule"] for e in controles)
