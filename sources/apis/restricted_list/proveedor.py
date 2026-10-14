"""Lo que hace "malo" al proveedor: latencia y caídas al azar."""

import asyncio
import random

from fastapi import HTTPException


class ProveedorSimulado:
    def __init__(self, config):
        self.config = config
        self.azar = random.Random(config.semilla)

    def sortear(self) -> tuple[float, bool]:
        """Devuelve (segundos de espera, si esta petición falla)."""
        espera_ms = self.azar.uniform(
            self.config.latencia_min_ms, self.config.latencia_max_ms
        )
        falla = self.azar.random() * 100 < self.config.falla_pct
        return espera_ms / 1000, falla

    async def simular(self):
        """Espera y, a veces, responde 503.

        La caída llega después de la espera, como un proveedor saturado
        que tarda y al final no responde. Así el motor tiene que cortar
        por tiempo y no solo por error.
        """
        espera, falla = self.sortear()
        # asyncio.sleep y no time.sleep: no bloquea las demás peticiones.
        await asyncio.sleep(espera)
        if falla:
            raise HTTPException(status_code=503, detail="Proveedor no disponible")
