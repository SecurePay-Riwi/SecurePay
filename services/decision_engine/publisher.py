"""Publicación de las decisiones en SNS sin hacer esperar al core.

La petición solo deja el evento en una cola en memoria y responde. Un hilo
de fondo junta hasta 10 eventos y los publica con PublishBatch (lotes de
10, bitácora sección 3). Así:

- La llamada a SNS no se suma a los 200 ms de la respuesta.
- Si SNS está caído o lento, el motor sigue respondiendo.
- Lo que no se pudo publicar tras los reintentos queda en el log como
  error, con el evento completo y la marca EVENTO_NO_PUBLICADO. En AWS ese
  log va a CloudWatch, donde una alarma lo detecta y el evento se puede
  volver a publicar.

El hilo arranca solo con el primer evento y, al apagar el motor,
detener() publica lo que quedó pendiente antes de salir.
"""

import json
import logging
import os
import queue
import threading
import time

from shared.aws import cliente

log = logging.getLogger(__name__)

TOPIC_ARN = os.getenv("SNS_DECISIONES_TOPIC_ARN", "")
# PublishBatch acepta hasta 10 mensajes por llamada.
TAMANO_LOTE = 10
# Cuánto espera el hilo a completar un lote antes de mandar lo que tiene.
ESPERA_LOTE_S = float(os.getenv("PUBLISH_BATCH_WAIT_MS", "500")) / 1000
# Eventos que caben en memoria si SNS no responde: a 50 tx/s, 10.000 son
# unos 3 minutos. Si se llena, los nuevos se registran como fallidos.
CAPACIDAD = int(os.getenv("PUBLISH_BUFFER_SIZE", "10000"))
REINTENTOS = int(os.getenv("PUBLISH_RETRIES", "3"))
ESPERA_REINTENTO_S = 0.2

MARCA_FALLA = "EVENTO_NO_PUBLICADO"

_FIN = object()  # aviso al hilo de que debe vaciar la cola y terminar


class Publicador:
    def __init__(
        self,
        topic_arn=TOPIC_ARN,
        crear_cliente=lambda: cliente("sns"),
        capacidad=CAPACIDAD,
        espera_lote_s=ESPERA_LOTE_S,
        reintentos=REINTENTOS,
        espera_reintento_s=ESPERA_REINTENTO_S,
    ):
        self.topic_arn = topic_arn
        self._crear_cliente = crear_cliente
        self._cliente = None
        self._cola = queue.Queue(maxsize=capacidad)
        self.espera_lote_s = espera_lote_s
        self.reintentos = reintentos
        self.espera_reintento_s = espera_reintento_s

        self._hilo = None
        self._candado = threading.Lock()
        self.publicados = 0
        self.fallidos = 0

    # --- Lo que usa la petición -------------------------------------------

    def publicar(self, evento: dict) -> None:
        """Deja el evento para el hilo de fondo. Nunca bloquea ni falla."""
        self._asegurar_hilo()
        try:
            self._cola.put_nowait(evento)
        except queue.Full:
            self._registrar_falla(evento, "la cola en memoria está llena")

    def estado(self) -> dict:
        return {
            "pendientes": self._cola.qsize(),
            "publicados": self.publicados,
            "fallidos": self.fallidos,
        }

    def detener(self, timeout: float = 5) -> None:
        """Publica lo pendiente y termina el hilo. Se llama al apagar."""
        with self._candado:
            hilo = self._hilo
        if hilo is None or not hilo.is_alive():
            return

        try:
            self._cola.put(_FIN, timeout=timeout)
            hilo.join(timeout)
        except queue.Full:
            pass

        # Lo que no alcanzó a salir se registra para no perderlo en silencio.
        while True:
            try:
                evento = self._cola.get_nowait()
            except queue.Empty:
                break
            if evento is not _FIN:
                self._registrar_falla(evento, "el motor se apagó antes de publicarlo")

    # --- Hilo de fondo ----------------------------------------------------

    def _asegurar_hilo(self):
        if self._hilo is not None and self._hilo.is_alive():
            return
        with self._candado:
            if self._hilo is None or not self._hilo.is_alive():
                self._hilo = threading.Thread(
                    target=self._bucle, name="publicador-sns", daemon=True
                )
                self._hilo.start()

    def _bucle(self):
        while True:
            primero = self._cola.get()
            if primero is _FIN:
                return

            lote, terminar = self._completar_lote(primero)
            self._enviar(lote)

            if terminar:
                return

    def _completar_lote(self, primero):
        """Junta hasta 10 eventos, esperando como mucho ESPERA_LOTE_S."""
        lote = [primero]
        limite = time.monotonic() + self.espera_lote_s

        while len(lote) < TAMANO_LOTE:
            restante = limite - time.monotonic()
            if restante <= 0:
                break
            try:
                evento = self._cola.get(timeout=restante)
            except queue.Empty:
                break
            if evento is _FIN:
                return lote, True
            lote.append(evento)

        return lote, False

    def _enviar(self, lote):
        if not self.topic_arn:
            for evento in lote:
                self._registrar_falla(evento, "falta SNS_DECISIONES_TOPIC_ARN")
            return

        # Id solo sirve para saber cuál falló dentro del lote.
        pendientes = dict(enumerate(lote))
        motivo = ""

        for intento in range(self.reintentos + 1):
            try:
                if self._cliente is None:
                    self._cliente = self._crear_cliente()

                respuesta = self._cliente.publish_batch(
                    TopicArn=self.topic_arn,
                    PublishBatchRequestEntries=[
                        {"Id": str(i), "Message": json.dumps(evento, ensure_ascii=False)}
                        for i, evento in pendientes.items()
                    ],
                )
                fallidos = {int(f["Id"]) for f in respuesta.get("Failed", [])}
                if fallidos:
                    motivo = respuesta["Failed"][0].get("Message", "SNS rechazó el mensaje")
            except Exception as exc:  # red caída, SNS caído, credenciales...
                fallidos = set(pendientes)
                motivo = f"{type(exc).__name__}: {exc}"

            with self._candado:
                self.publicados += len(pendientes) - len(fallidos)

            pendientes = {i: pendientes[i] for i in fallidos}
            if not pendientes:
                return

            if intento < self.reintentos:
                time.sleep(self.espera_reintento_s * 2**intento)

        for evento in pendientes.values():
            self._registrar_falla(evento, motivo)

    def _registrar_falla(self, evento, motivo):
        with self._candado:
            self.fallidos += 1
        log.error(
            "%s (%s): %s",
            MARCA_FALLA,
            motivo,
            json.dumps(evento, ensure_ascii=False),
        )


# Un publicador por proceso del motor, como el cliente de Valkey.
_publicador = Publicador()


def publicar(evento: dict) -> None:
    _publicador.publicar(evento)


def estado() -> dict:
    return _publicador.estado()


def detener() -> None:
    _publicador.detener()
