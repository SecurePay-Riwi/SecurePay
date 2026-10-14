"""Los cuatro socios de pago y el formato de su archivo diario.

Cada socio ve solo las transacciones que pasan por él, según el tipo y el
canal que ya trae el generador, y escribe su archivo a su manera, como
pasa con bancos y redes reales:

| Socio               | Qué ve                         | Formato                      | Fechas  |
|---------------------|--------------------------------|------------------------------|---------|
| banco_andino        | Recargas por APP y WEB         | CSV con comas, punto decimal | UTC     |
| red_corresponsales  | Recargas y retiros en          | TXT de ancho fijo (H, D, T), | Bogotá  |
|                     | CORRESPONSAL                   | montos en unidades mínimas   |         |
| cajeros_express     | Retiros en CAJERO              | CSV con punto y coma y coma  | Bogotá  |
|                     |                                | decimal                      |         |
| qr_pagos            | Pagos QR a comercios           | TXT separado por "|",        | UTC     |
|                     |                                | unidades mínimas             |         |

Todos traen un registro de control con la cantidad de registros y la suma
de los montos (un "total hash": se suman aunque sean monedas distintas,
solo sirve para comprobar que el archivo llegó completo).

El "día" del archivo es el día en la zona horaria del socio: una recarga a
las 23:30 de Bogotá queda en el archivo de ese día aunque en UTC ya sea el
siguiente. Por eso la conciliación acepta ±1 día.

Cada socio también sabe leer su propio archivo (leer). Lo usan las
pruebas y lo usará la ingesta de extractos.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sources.csv_files.partner_statements.money import paso

# Bogotá es UTC-5 todo el año (sin horario de verano desde 1993). Se usa
# un desfase fijo en vez de ZoneInfo("America/Bogota") porque en Windows
# ZoneInfo necesita instalar el paquete tzdata.
BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")


@dataclass(frozen=True)
class Registro:
    """Una operación tal como la reporta el socio."""

    ref_pagoseguro: str
    ref_socio: str
    tipo: str
    monto: Decimal
    moneda: str
    fecha: datetime  # con zona horaria
    comercio: str | None = None


@dataclass
class Extracto:
    """El archivo de un socio para un día."""

    socio: str
    dia: date
    version: int
    registros: list[Registro]
    # Lo que dice el registro de control: (cantidad, total). None = el real.
    control: tuple[int, Decimal] | None = None

    def nombre_archivo(self, extension):
        return f"{self.socio}_{self.dia:%Y%m%d}_v{self.version}.{extension}"


@dataclass
class Leido:
    """Lo que se obtiene al leer un archivo: registros y control declarado."""

    registros: list[Registro]
    control: tuple[int, Decimal]
    extra: dict = field(default_factory=dict)


def a_unidades(monto: Decimal, moneda: str) -> int:
    """12.34 USD -> 1234; 1500 JPY -> 1500."""
    return int(monto / paso(moneda))


def de_unidades(unidades: int, moneda: str) -> Decimal:
    return (Decimal(unidades) * paso(moneda)).quantize(paso(moneda))


class Socio:
    nombre = ""
    prefijo = ""  # de su referencia propia
    extension = "csv"
    zona = timezone.utc

    def ve(self, op) -> bool:
        raise NotImplementedError

    def dia_de(self, fecha: datetime) -> date:
        """El día del archivo en que el socio pone esa operación."""
        return fecha.astimezone(self.zona).date()

    def total(self, registros) -> Decimal:
        """Suma de control tal como la calcula el socio."""
        return sum((r.monto for r in registros), Decimal(0))

    def control_real(self, registros) -> tuple[int, Decimal]:
        return len(registros), self.total(registros)

    def escribir(self, extracto: Extracto) -> str:
        raise NotImplementedError

    def leer(self, texto: str) -> Leido:
        raise NotImplementedError


class BancoAndino(Socio):
    """Recargas por la app o la web, pagadas desde una cuenta bancaria."""

    nombre = "banco_andino"
    prefijo = "BA"
    extension = "csv"
    zona = timezone.utc
    COLUMNAS = ["fecha_hora_utc", "referencia_banco", "referencia_pagoseguro",
                "tipo", "moneda", "monto"]

    def ve(self, op):
        return op.tipo == "RECARGA" and op.canal in ("APP", "WEB")

    def escribir(self, extracto):
        salida = io.StringIO()
        w = csv.writer(salida, lineterminator="\n")
        w.writerow(self.COLUMNAS)
        for r in extracto.registros:
            w.writerow([
                r.fecha.astimezone(self.zona).strftime("%Y-%m-%dT%H:%M:%SZ"),
                r.ref_socio, r.ref_pagoseguro, r.tipo, r.moneda, f"{r.monto}",
            ])
        cantidad, total = extracto.control or self.control_real(extracto.registros)
        w.writerow(["TOTAL", cantidad, f"{total}"])
        return salida.getvalue()

    def leer(self, texto):
        filas = list(csv.reader(io.StringIO(texto)))
        cuerpo, control = filas[1:-1], filas[-1]
        registros = [
            Registro(
                ref_pagoseguro=f[2], ref_socio=f[1], tipo=f[3], moneda=f[4],
                monto=Decimal(f[5]),
                fecha=datetime.strptime(f[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc),
            )
            for f in cuerpo
        ]
        return Leido(registros, (int(control[1]), Decimal(control[2])))


class RedCorresponsales(Socio):
    """Recargas y retiros en efectivo en tiendas corresponsales.

    Ancho fijo, como los archivos bancarios clásicos. Cada línea empieza
    con su tipo de registro:

        H  socio(20) día(8) versión(2)
        D  fecha local(14) ref socio(12) ref PagoSeguro(36) tipo(7) moneda(3) monto(15)
        T  cantidad(8) total(18)

    Los montos van en unidades mínimas con ceros a la izquierda: 1234.50
    COP se escribe 000000000123450.
    """

    nombre = "red_corresponsales"
    prefijo = "RC"
    extension = "txt"
    zona = BOGOTA

    def ve(self, op):
        return op.tipo in ("RECARGA", "RETIRO") and op.canal == "CORRESPONSAL"

    def total(self, registros):
        return Decimal(sum(a_unidades(r.monto, r.moneda) for r in registros))

    def escribir(self, extracto):
        lineas = [f"H{self.nombre:<20}{extracto.dia:%Y%m%d}{extracto.version:02d}"]
        for r in extracto.registros:
            lineas.append(
                "D"
                f"{r.fecha.astimezone(self.zona):%Y%m%d%H%M%S}"
                f"{r.ref_socio:<12}"
                f"{r.ref_pagoseguro:<36}"
                f"{r.tipo:<7}"
                f"{r.moneda:<3}"
                f"{a_unidades(r.monto, r.moneda):015d}"
            )
        cantidad, total = extracto.control or self.control_real(extracto.registros)
        lineas.append(f"T{cantidad:08d}{int(total):018d}")
        return "\n".join(lineas) + "\n"

    def leer(self, texto):
        registros, control, encabezado = [], None, {}
        for linea in texto.splitlines():
            if linea.startswith("H"):
                encabezado = {"socio": linea[1:21].strip(), "dia": linea[21:29],
                              "version": int(linea[29:31])}
            elif linea.startswith("D"):
                moneda = linea[70:73].strip()
                registros.append(Registro(
                    fecha=datetime.strptime(linea[1:15], "%Y%m%d%H%M%S").replace(tzinfo=self.zona),
                    ref_socio=linea[15:27].strip(),
                    ref_pagoseguro=linea[27:63].strip(),
                    tipo=linea[63:70].strip(),
                    moneda=moneda,
                    monto=de_unidades(int(linea[73:88]), moneda),
                ))
            elif linea.startswith("T"):
                control = (int(linea[1:9]), Decimal(int(linea[9:27])))
        return Leido(registros, control, encabezado)


class CajerosExpress(Socio):
    """Retiros en cajeros automáticos.

    CSV al estilo de una hoja de cálculo en español: punto y coma, coma
    decimal y fecha día/mes/año en hora de Bogotá. La última línea es el
    control.
    """

    nombre = "cajeros_express"
    prefijo = "CX"
    extension = "csv"
    zona = BOGOTA
    COLUMNAS = ["Fecha", "Hora", "Ref Cajero", "Ref Billetera", "Moneda", "Valor"]

    def ve(self, op):
        return op.tipo == "RETIRO" and op.canal == "CAJERO"

    @staticmethod
    def _coma(monto):
        return f"{monto}".replace(".", ",")

    def escribir(self, extracto):
        salida = io.StringIO()
        w = csv.writer(salida, delimiter=";", lineterminator="\n")
        w.writerow(self.COLUMNAS)
        for r in extracto.registros:
            local = r.fecha.astimezone(self.zona)
            w.writerow([f"{local:%d/%m/%Y}", f"{local:%H:%M:%S}", r.ref_socio,
                        r.ref_pagoseguro, r.moneda, self._coma(r.monto)])
        cantidad, total = extracto.control or self.control_real(extracto.registros)
        w.writerow(["CONTROL", cantidad, self._coma(total)])
        return salida.getvalue()

    def leer(self, texto):
        filas = list(csv.reader(io.StringIO(texto), delimiter=";"))
        cuerpo, control = filas[1:-1], filas[-1]
        registros = [
            Registro(
                fecha=datetime.strptime(f"{f[0]} {f[1]}", "%d/%m/%Y %H:%M:%S").replace(tzinfo=self.zona),
                ref_socio=f[2], ref_pagoseguro=f[3], tipo="RETIRO", moneda=f[4],
                monto=Decimal(f[5].replace(",", ".")),
            )
            for f in cuerpo
        ]
        return Leido(registros, (int(control[1]), Decimal(control[2].replace(",", "."))))


class QrPagos(Socio):
    """Adquirente que liquida los pagos QR a los comercios.

    Separado por "|", con el control en la primera línea (empieza con #) y
    los montos en unidades mínimas. La fecha va en UTC sin indicarlo, como
    pasa a menudo: hay que saberlo por el acuerdo con el socio.
    """

    nombre = "qr_pagos"
    prefijo = "QR"
    extension = "txt"
    zona = timezone.utc

    def ve(self, op):
        return op.tipo == "QR"

    def total(self, registros):
        return Decimal(sum(a_unidades(r.monto, r.moneda) for r in registros))

    def escribir(self, extracto):
        cantidad, total = extracto.control or self.control_real(extracto.registros)
        lineas = [f"#CTRL|{extracto.dia:%Y-%m-%d}|{cantidad}|{int(total)}",
                  "ref_qr|ref_pagoseguro|comercio|moneda|monto_minimo|fecha"]
        for r in extracto.registros:
            lineas.append("|".join([
                r.ref_socio, r.ref_pagoseguro, r.comercio or "", r.moneda,
                str(a_unidades(r.monto, r.moneda)),
                f"{r.fecha.astimezone(self.zona):%Y-%m-%d %H:%M:%S}",
            ]))
        return "\n".join(lineas) + "\n"

    def leer(self, texto):
        lineas = texto.splitlines()
        _, dia, cantidad, total = lineas[0].split("|")
        registros = []
        for linea in lineas[2:]:
            ref_qr, ref_ps, comercio, moneda, unidades, fecha = linea.split("|")
            registros.append(Registro(
                ref_pagoseguro=ref_ps, ref_socio=ref_qr, tipo="QR", moneda=moneda,
                monto=de_unidades(int(unidades), moneda), comercio=comercio or None,
                fecha=datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
            ))
        return Leido(registros, (int(cantidad), Decimal(total)), {"dia": dia})


SOCIOS = [BancoAndino(), RedCorresponsales(), CajerosExpress(), QrPagos()]


def socio_de(op):
    """El socio por el que pasa una operación, o None (no debería pasar)."""
    for socio in SOCIOS:
        if socio.ve(op):
            return socio
    return None

