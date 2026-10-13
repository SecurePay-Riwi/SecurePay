"""Salida del generador: a dónde van los eventos y qué queda registrado.

- SalidaHttp: manda cada evento al motor, como el core, al ritmo pedido.
- SalidaArchivo: los escribe en un .jsonl, para probar sin el motor.
- Reporte: guarda lo que el motor no ve (etiquetas de fraude y defectos) y
  lo que respondió, para medir después si acertó.
"""

import json
import time
from collections import Counter
from pathlib import Path

import httpx

# Rutas del motor. Los eventos de seguridad todavía no tienen endpoint:
# mientras no exista, el motor responderá 404 y quedará contado.
RUTAS = {"transaction": "/transactions", "security": "/security-events"}


class Ritmo:
    """Espera lo justo entre envíos para no pasar de N por segundo."""

    def __init__(self, por_segundo):
        self.intervalo = 1 / por_segundo if por_segundo > 0 else 0
        self.siguiente = time.perf_counter()

    def esperar(self):
        if not self.intervalo:
            return
        ahora = time.perf_counter()
        if self.siguiente > ahora:
            time.sleep(self.siguiente - ahora)
        # Se suma al horario previsto, no a "ahora": si un envío se demora,
        # los siguientes se ponen al día y el promedio se mantiene.
        self.siguiente = max(self.siguiente, ahora) + self.intervalo


class SalidaHttp:
    def __init__(self, url, por_segundo, reintentos=3):
        self.cliente = httpx.Client(base_url=url, timeout=5)
        self.ritmo = Ritmo(por_segundo)
        self.reintentos = reintentos

    def enviar(self, evento):
        self.ritmo.esperar()
        ruta = RUTAS[evento.tipo]

        for intento in range(self.reintentos + 1):
            try:
                respuesta = self.cliente.post(ruta, json=evento.payload)
            except httpx.TransportError as error:
                # Sin conexión o sin respuesta: se reintenta con el mismo id,
                # que es seguro porque el motor es idempotente.
                if intento == self.reintentos:
                    return {"status": None, "error": type(error).__name__}
                time.sleep(0.2 * 2**intento)
                continue

            resultado = {"status": respuesta.status_code}
            if respuesta.headers.get("content-type", "").startswith("application/json"):
                cuerpo = respuesta.json()
                resultado["decision"] = cuerpo.get("decision")
                resultado["reason"] = cuerpo.get("decision_reason")
            return resultado

    def cerrar(self):
        self.cliente.close()


class SalidaArchivo:
    def __init__(self, carpeta):
        self.archivo = (carpeta / "events.jsonl").open("w", encoding="utf-8")

    def enviar(self, evento):
        # Una línea por evento, en el orden en que llegarían al motor.
        linea = {"kind": evento.tipo, "endpoint": RUTAS[evento.tipo], "body": evento.payload}
        self.archivo.write(json.dumps(linea, ensure_ascii=False) + "\n")
        return None

    def cerrar(self):
        self.archivo.close()


class Reporte:
    def __init__(self, carpeta):
        self.carpeta = carpeta
        self.etiquetas = (carpeta / "labels.jsonl").open("w", encoding="utf-8")
        self.patrones = Counter()
        self.tipos = Counter()
        self.respuestas = Counter()

    def anotar(self, evento, resultado):
        fila = {"id": evento.payload["id"], "kind": evento.tipo, **evento.etiqueta}
        if resultado is not None:
            fila["response"] = resultado
            self.respuestas[str(resultado.get("status"))] += 1
        self.etiquetas.write(json.dumps(fila, ensure_ascii=False) + "\n")

        self.tipos[evento.payload["type"]] += 1
        if not evento.etiqueta.get("duplicate"):
            self.patrones[evento.etiqueta["pattern"] or "NORMAL"] += 1

    def cerrar(self, defectos, parametros):
        self.etiquetas.close()
        resumen = {
            "parameters": parametros,
            "events_by_type": dict(self.tipos),
            "events_by_pattern": dict(self.patrones),
            "defects_by_type": dict(Counter(d["defect"] for d in defectos)),
            "responses_by_status": dict(self.respuestas),
            "defects": defectos,
        }
        ruta = self.carpeta / "generation_report.json"
        ruta.write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
        return resumen


def carpeta_de_salida(base, instancia):
    carpeta = Path(base) / f"instance-{instancia}"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta
