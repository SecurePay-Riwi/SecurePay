"""Descarga de Frankfurter las tasas de la fecha de referencia.

Se corre una sola vez y el archivo resultante se sube al repo:

    uv run python -m generators.fetch_rates

Así el generador no depende de internet en cada corrida y todas las
corridas usan exactamente las mismas tasas.
"""

import json
import urllib.request

from generators.config import FECHA_REFERENCIA, TASAS_FILE

# La versión 2 trae COP; la versión 1 no.
URL = "https://api.frankfurter.dev/v2/rates"

BASE = "USD"
MONEDAS = ("COP", "EUR", "JPY")


def descargar():
    fecha = FECHA_REFERENCIA.date().isoformat()
    url = f"{URL}?date={fecha}&base={BASE}&quotes={','.join(MONEDAS)}"

    # Sin un User-Agent propio, Frankfurter rechaza la petición (403):
    # bloquea el que urllib manda por defecto ("Python-urllib/3.12").
    peticion = urllib.request.Request(
        url,
        headers={"User-Agent": "securepay-generator", "Accept": "application/json"},
    )

    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        registros = json.load(respuesta)

    # Cada registro llega como {"date", "base", "quote", "rate"}.
    tasas = {r["quote"]: r["rate"] for r in registros}

    faltantes = set(MONEDAS) - set(tasas)
    if faltantes:
        raise ValueError(f"Frankfurter no devolvió: {sorted(faltantes)}")

    fechas = {r["date"] for r in registros}
    if fechas != {fecha}:
        raise ValueError(f"Se pidió {fecha} y llegaron fechas {sorted(fechas)}")

    contenido = {
        "fuente": url,
        "fecha": fecha,
        "base": BASE,
        # Unidades de cada moneda por 1 USD.
        "tasas": {BASE: 1, **tasas},
        # La respuesta tal cual llegó, por si hay que revisarla.
        "respuesta": registros,
    }

    TASAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASAS_FILE.write_text(
        json.dumps(contenido, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Tasas de {fecha} guardadas en {TASAS_FILE}")
    for moneda, tasa in contenido["tasas"].items():
        print(f"  1 {BASE} = {tasa} {moneda}")


if __name__ == "__main__":
    descargar()
