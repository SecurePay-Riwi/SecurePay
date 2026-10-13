"""El core simulado: reloj, saldos, tráfico normal y agenda de patrones.

Entrega los eventos en orden de fecha, uno por uno, sin guardarlos todos
en memoria. Los patrones de fraude (patterns.py) no producen sus eventos
de golpe: los dejan agendados para una fecha futura y el core los entrega
cuando el reloj llega ahí, mezclados con el tráfico normal. Los saldos se
mueven en el momento de entregar cada evento, así el "antes" y el
"después" siempre cuadran en orden de fecha.
"""

import heapq
import random
import uuid
from dataclasses import dataclass
from datetime import timedelta

from generators import config
from generators.money import desde_usd, redondear

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")


@dataclass
class Evento:
    tipo: str  # "transaction" o "security"
    # Lo que recibe el motor, tal como lo mandaría el core.
    payload: dict
    # Lo que sabe el generador y el motor no: va al reporte, nunca al motor.
    etiqueta: dict


def etiqueta(patron=None, instancia=None, fraude=False, regla=None):
    return {
        "pattern": patron,
        "pattern_id": instancia,
        "is_fraud": fraude,
        # Regla que debería activarse con este evento; None si ninguna.
        "expected_rule": regla,
    }


class Core:
    def __init__(
        self,
        catalogo,
        tasas,
        cantidad,
        fraud_pct,
        semilla,
        inicio,
        tx_por_cuenta_dia=1,
        instancia=0,
    ):
        self.rng = random.Random(f"{semilla}:{instancia}")
        self.semilla = semilla
        self.instancia = instancia
        self.tasas = tasas
        self.cantidad = cantidad
        self.fraud_pct = fraud_pct
        self.comercios = catalogo.comercios
        self.cuentas = list(catalogo.cuentas.values())

        # Las cuentas en lista restrictiva solo las usa su patrón: cualquier
        # transacción suya debe terminar en RECHAZAR, no es tráfico normal.
        self.normales = [c for c in self.cuentas if not c.en_lista]
        self.en_lista = [c for c in self.cuentas if c.en_lista]
        self.por_moneda = {}
        for c in self.normales:
            self.por_moneda.setdefault(c.moneda, []).append(c)

        # Reloj simulado: la fecha que llevan las transacciones.
        self.reloj = inicio
        self.inicio = inicio
        self.segundos_entre = 86_400 / (len(self.cuentas) * tx_por_cuenta_dia)

        # Agenda de los patrones: (fecha, orden, accion, es_transaccion).
        self.agenda = []
        self._orden = 0
        # Cuentas apartadas por un patrón hasta cierta fecha. El tráfico
        # normal no las toca, para no alterar los conteos de las reglas.
        self.ocupadas = {}

        self.emitidas = 0  # transacciones ya entregadas
        self.pendientes = 0  # transacciones agendadas sin entregar
        self.fraude_agendado = 0  # transacciones de fraude agendadas

        # Lista de (patrón, es_fraude) que se recorre en ciclo; la llena
        # patterns.py. Vacía, el core solo produce tráfico normal.
        self.patrones = []
        self._siguiente = 0
        self._instancias = 0
        self._contador = 0

    # --- Identificadores ---------------------------------------------------

    def nuevo_id(self, tipo):
        """Id fijo para la misma semilla e instancia, distinto entre ellas."""
        self._contador += 1
        nombre = f"{tipo}:{self.semilla}:{self.instancia}:{self._contador}"
        return str(uuid.uuid5(NAMESPACE, nombre))

    def nueva_instancia(self, patron):
        self._instancias += 1
        return f"{patron}-{self.instancia}-{self._instancias}"

    # --- Cuentas -----------------------------------------------------------

    def libre(self, cuenta):
        return self.ocupadas.get(cuenta.id, self.inicio) <= self.reloj

    def reservar(self, cuentas, hasta):
        for c in cuentas:
            self.ocupadas[c.id] = hasta

    def elegir(self, cuentas, excluir=(), intentos=20):
        """Una cuenta libre al azar, o None si no la encuentra."""
        if not cuentas:
            return None
        for _ in range(intentos):
            c = self.rng.choice(cuentas)
            if self.libre(c) and c not in excluir:
                return c
        return None

    # --- Eventos -----------------------------------------------------------

    def transaccion(
        self,
        tipo,
        monto,
        fecha,
        origen=None,
        destino=None,
        comercio=None,
        dispositivo=None,
        etiq=None,
    ):
        """Arma la transacción y mueve los saldos, como el core.

        Una recarga solo tiene destino; un retiro o un pago QR, solo origen.
        """
        cuenta = origen or destino
        monto = redondear(monto, cuenta.moneda)

        if origen and monto > origen.saldo:
            raise ValueError("El core no deja sacar más del saldo disponible")

        payload = {
            "id": self.nuevo_id("tx"),
            "type": tipo,
            "channel": self.rng.choice(config.CANALES[tipo]),
            "source_account_id": None,
            "destination_account_id": None,
            "merchant_id": str(comercio) if comercio else None,
            "amount": str(monto),
            "currency": cuenta.moneda,
            "source_balance_before": None,
            "source_balance_after": None,
            "destination_balance_before": None,
            "destination_balance_after": None,
            "device_id": str(dispositivo or self.rng.choice(cuenta.dispositivos)),
            "transaction_date": fecha.isoformat(),
        }

        if origen:
            payload["source_account_id"] = str(origen.id)
            payload["source_balance_before"] = str(origen.saldo)
            origen.saldo -= monto
            payload["source_balance_after"] = str(origen.saldo)

        if destino:
            payload["destination_account_id"] = str(destino.id)
            payload["destination_balance_before"] = str(destino.saldo)
            destino.saldo += monto
            payload["destination_balance_after"] = str(destino.saldo)

        return Evento("transaction", payload, etiq or etiqueta())

    def seguridad(self, tipo, cuenta, dispositivo, fecha, etiq):
        """Evento de seguridad: cambio de dispositivo o de contraseña."""
        payload = {
            "id": self.nuevo_id("sec"),
            "type": tipo,  # DEVICE_CHANGE o PASSWORD_CHANGE
            "user_id": str(cuenta.user_id),
            "account_id": str(cuenta.id),
            "device_id": str(dispositivo),
            "event_date": fecha.isoformat(),
        }
        return Evento("security", payload, etiq)

    # --- Tráfico normal ----------------------------------------------------

    def normal(self):
        """Una transacción cualquiera de una cuenta libre."""
        tipos = list(config.TIPOS)
        tipo = self.rng.choices(tipos, weights=[config.TIPOS[t] for t in tipos])[0]
        cuenta = self.elegir(self.normales)
        if cuenta is None:
            raise RuntimeError("No hay cuentas libres para el tráfico normal")

        monto = desde_usd(
            self.rng.uniform(config.MONTO_NORMAL_USD["min"], config.MONTO_NORMAL_USD["max"]),
            cuenta.moneda,
            self.tasas,
        )

        destino = None
        if tipo == "P2P":
            destino = self.elegir(self.por_moneda[cuenta.moneda], excluir=(cuenta,))
            if destino is None:
                tipo = "QR"  # No hay otra cuenta libre en su moneda.

        # Sin saldo suficiente, la persona recarga en vez de gastar.
        if tipo != "RECARGA" and monto > cuenta.saldo:
            tipo = "RECARGA"

        # Las cuentas con dispositivo compartido hacen tráfico normal, pero
        # la regla del dispositivo compartido debería subirles el riesgo.
        etiq = etiqueta()
        if cuenta.compartida:
            etiq = etiqueta("SHARED_DEVICE", regla="dispositivo_compartido")

        if tipo == "RECARGA":
            monto = desde_usd(
                self.rng.uniform(
                    config.MONTO_RECARGA_USD["min"], config.MONTO_RECARGA_USD["max"]
                ),
                cuenta.moneda,
                self.tasas,
            )
            return self.transaccion(tipo, monto, self.reloj, destino=cuenta, etiq=etiq)

        if tipo == "P2P":
            return self.transaccion(
                tipo, monto, self.reloj, origen=cuenta, destino=destino, etiq=etiq
            )

        comercio = self.rng.choice(self.comercios) if tipo == "QR" else None
        return self.transaccion(
            tipo, monto, self.reloj, origen=cuenta, comercio=comercio, etiq=etiq
        )

    # --- Agenda de patrones ------------------------------------------------

    def agendar(self, fecha, accion, es_transaccion=True):
        """Deja un paso de un patrón para cuando el reloj llegue a su fecha.

        accion(fecha) devuelve el Evento; se llama al entregarlo, no antes.
        """
        heapq.heappush(self.agenda, (fecha, self._orden, accion, es_transaccion))
        self._orden += 1
        if es_transaccion:
            self.pendientes += 1

    def _iniciar_patrones(self):
        """Arranca patrones mientras el fraude agendado esté bajo la meta."""
        for _ in range(len(self.patrones)):
            meta = self.fraud_pct / 100 * (self.emitidas + 1)
            if self.fraude_agendado >= meta:
                return

            patron, es_fraude = self.patrones[self._siguiente]
            self._siguiente = (self._siguiente + 1) % len(self.patrones)

            # Sin espacio para el patrón completo, no se empieza.
            if self.emitidas + self.pendientes + patron.max_tx > self.cantidad:
                return

            agendadas = patron.iniciar(self, es_fraude)
            if es_fraude:
                self.fraude_agendado += agendadas

    def eventos(self):
        """Entrega los eventos en orden de fecha hasta llegar a la cantidad."""
        proxima = self.reloj + timedelta(seconds=self.rng.expovariate(1 / self.segundos_entre))

        while True:
            self._iniciar_patrones()
            cupo_normal = self.emitidas + self.pendientes < self.cantidad

            if self.agenda and (not cupo_normal or self.agenda[0][0] <= proxima):
                fecha, _, accion, es_transaccion = heapq.heappop(self.agenda)
                self.reloj = max(self.reloj, fecha)
                evento = accion(fecha)
                if es_transaccion:
                    self.pendientes -= 1
                    self.emitidas += 1
                yield evento

            elif cupo_normal:
                self.reloj = proxima
                self.emitidas += 1
                yield self.normal()
                proxima = self.reloj + timedelta(
                    seconds=self.rng.expovariate(1 / self.segundos_entre)
                )

            else:
                return
