"""Lee lo que produjo el generador de transacciones.

Los extractos tienen que cuadrar con lo que el core mandó al motor, así
que la entrada es la salida del generador (generated/instance-*/):

- events.jsonl: las transacciones tal como llegaron al motor.
- labels.jsonl: la respuesta del motor, cuando se mandaron por HTTP.

Solo quedan las transacciones que el socio vería con el dinero ya movido:
- Sin P2P: son internas de la billetera, ningún socio las ve.
- Sin reenvíos del core: el mismo id cuenta una sola vez.
- Sin rechazadas ni retenidas, si se sabe la respuesta del motor: esas no
  movieron dinero. Con GEN_OUTPUT=file no hay respuesta y entran todas.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sources.csv_files.partner_statements.money import redondear

# Lo que ve algún socio. Las P2P no salen de la billetera.
TIPOS_CON_SOCIO = {"RECARGA", "RETIRO", "QR"}


@dataclass(frozen=True)
class Operacion:
    """Una transacción de PagoSeguro que pasa por un socio."""

    id: str
    tipo: str
    canal: str
    monto: Decimal
    moneda: str
    fecha: datetime  # con zona horaria (UTC, como la manda el core)
    comercio: str | None = None


def _leer_jsonl(ruta: Path):
    with ruta.open(encoding="utf-8") as archivo:
        for linea in archivo:
            if linea.strip():
                yield json.loads(linea)


def _decisiones(carpeta: Path) -> dict[str, str]:
    """Id de transacción -> decisión del motor, si se mandó por HTTP."""
    ruta = carpeta / "labels.jsonl"
    if not ruta.exists():
        return {}
    decisiones = {}
    for fila in _leer_jsonl(ruta):
        decision = (fila.get("response") or {}).get("decision")
        if decision:
            decisiones[fila["id"]] = decision
    return decisiones


def leer(base: Path) -> list[Operacion]:
    """Todas las operaciones de todas las instancias, en orden de fecha."""
    carpetas = sorted(p for p in Path(base).glob("instance-*") if p.is_dir())
    if not carpetas:
        raise FileNotFoundError(
            f"No hay salida del generador en {base}. Corre primero: "
            "uv run python -m generators"
        )

    operaciones = {}
    for carpeta in carpetas:
        ruta = carpeta / "events.jsonl"
        if not ruta.exists():
            raise FileNotFoundError(f"Falta {ruta}: vuelve a correr el generador")
        decisiones = _decisiones(carpeta)

        for linea in _leer_jsonl(ruta):
            if linea["kind"] != "transaction":
                continue
            tx = linea["body"]
            if tx["type"] not in TIPOS_CON_SOCIO or tx["id"] in operaciones:
                continue
            # Sin respuesta (modo file o error de red) se asume aprobada.
            if decisiones.get(tx["id"], "APPROVE") != "APPROVE":
                continue

            operaciones[tx["id"]] = Operacion(
                id=tx["id"],
                tipo=tx["type"],
                canal=tx["channel"],
                # El defecto de decimales de más ("88.910") no cambia el
                # valor: el socio registra el monto con la precisión real.
                monto=redondear(tx["amount"], tx["currency"]),
                moneda=tx["currency"],
                fecha=datetime.fromisoformat(tx["transaction_date"]),
                comercio=tx.get("merchant_id"),
            )

    return sorted(operaciones.values(), key=lambda o: (o.fecha, o.id))
