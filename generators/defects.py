"""Defectos de calidad del stream del core, con porcentaje configurable.

Son los tres que el enunciado le asigna al generador:
- Reenvíos: la misma transacción, con el mismo id, llega dos veces.
- Desorden: un evento llega después de otros que ocurrieron más tarde.
- Precisión: el monto llega con más decimales de los que admite su moneda.

Se aplican sobre los eventos ya generados, en el orden de envío, sin tocar
los saldos ni las etiquetas de fraude. Cada defecto queda en el reporte
para poder comprobar después cómo los trató el motor.
"""

import heapq
import random
from dataclasses import replace


class Defectos:
    def __init__(self, semilla, duplicados_pct, desorden_pct, decimales_pct):
        # Su propio generador al azar: activar o no los defectos no cambia
        # las transacciones que produce el core.
        self.rng = random.Random(f"{semilla}:defectos")
        self.duplicados_pct = duplicados_pct
        self.desorden_pct = desorden_pct
        self.decimales_pct = decimales_pct
        self.reporte = []

    def _toca(self, porcentaje):
        return self.rng.random() * 100 < porcentaje

    def _anotar(self, defecto, evento, detalle, **etiqueta_extra):
        """Lo guarda en el reporte y devuelve el evento con el defecto marcado.

        Devuelve una copia: el evento original no se modifica.
        """
        self.reporte.append(
            {"defect": defecto, "event_id": evento.payload["id"], "detail": detalle}
        )
        defectos = evento.etiqueta.get("defects", []) + [defecto]
        return replace(
            evento, etiqueta={**evento.etiqueta, **etiqueta_extra, "defects": defectos}
        )

    def _mas_decimales(self, evento):
        """Agrega ceros al final del monto: mismo valor, otra precisión.

        "88.91" pasa a "88.910" y "12027" (yenes) a "12027.00". El valor no
        cambia, así los saldos siguen cuadrando; lo que cambia es que llega
        con más decimales de los que admite la moneda.
        """
        monto = evento.payload["amount"]
        extra = "0" * self.rng.randint(1, 2)
        nuevo = f"{monto}{extra}" if "." in monto else f"{monto}.{extra}"

        evento = replace(evento, payload={**evento.payload, "amount": nuevo})
        return self._anotar("DECIMAL_PRECISION", evento, f"{monto} -> {nuevo}")

    def aplicar(self, eventos):
        """Recibe los eventos en orden de fecha y los entrega con defectos."""
        # Eventos retenidos: (se liberan después del envío n, orden, evento).
        retenidos = []
        orden = 0
        enviados = 0

        def retener(despues_de, evento):
            nonlocal orden
            heapq.heappush(retenidos, (despues_de, orden, evento))
            orden += 1

        for evento in eventos:
            es_tx = evento.tipo == "transaction"

            if es_tx and self._toca(self.decimales_pct):
                evento = self._mas_decimales(evento)

            if self._toca(self.desorden_pct):
                # Llega entre 1 y 10 eventos más tarde, con su fecha original.
                saltos = self.rng.randint(1, 10)
                evento = self._anotar("OUT_OF_ORDER", evento, f"llega {saltos} eventos tarde")
                retener(enviados + saltos, evento)
            else:
                yield evento
                enviados += 1

                if es_tx and self._toca(self.duplicados_pct):
                    # El core reintenta: mismo payload, mismo id.
                    saltos = self.rng.randint(0, 3)
                    copia = self._anotar(
                        "DUPLICATE", evento, f"reenviada {saltos} eventos después",
                        duplicate=True,
                    )
                    retener(enviados + saltos, copia)

            while retenidos and retenidos[0][0] <= enviados:
                yield heapq.heappop(retenidos)[2]
                enviados += 1

        # Lo que quedó retenido al final sale en su orden.
        while retenidos:
            yield heapq.heappop(retenidos)[2]
