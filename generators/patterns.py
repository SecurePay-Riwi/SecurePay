"""Patrones de fraude, uno por regla, cada uno con su caso de control.

Cada patrón aparta sus cuentas, agenda sus pasos en el core y devuelve
cuántas transacciones agendó. El caso de control hace lo mismo pero se
queda justo del lado que NO debe disparar la regla: si el motor lo marca,
el motor tiene un error.

Los umbrales salen de config.REGLAS; los montos se piensan en USD y se
convierten a la moneda de cada cuenta con las tasas guardadas.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from generators import config
from generators.core import NAMESPACE, etiqueta
from generators.money import a_usd, desde_usd, redondear


def elegir_varias(core, cuentas, n, excluir=(), saldo_min_usd=0):
    """n cuentas libres y distintas, con al menos ese saldo; None si no hay."""
    elegidas = []
    for _ in range(n * 10):
        c = core.elegir(cuentas, excluir=tuple(excluir) + tuple(elegidas))
        if c is None:
            break
        if a_usd(c.saldo, c.moneda, core.tasas) >= saldo_min_usd:
            elegidas.append(c)
        if len(elegidas) == n:
            return elegidas
    return None


def usd(core, minimo, maximo, moneda):
    """Monto al azar entre dos valores en USD, ya en la moneda de la cuenta."""
    return desde_usd(core.rng.uniform(minimo, maximo), moneda, core.tasas)


class Velocidad:
    """Más de 5 transferencias salientes en 10 minutos desde la misma cuenta.

    Fraude: 6 transferencias en 8 minutos. Control: 5 en 8 minutos.
    """

    nombre = "VELOCITY"
    regla = config.REGLAS["velocidad"]
    max_tx = regla["transferencias"] + 2  # transferencias + posible recarga

    def iniciar(self, core, fraude):
        n = self.regla["transferencias"] + (1 if fraude else 0)
        ventana = timedelta(minutes=self.regla["minutos"])

        origen = core.elegir(core.normales)
        if origen is None:
            return 0
        destinos = elegir_varias(core, core.por_moneda[origen.moneda], n, excluir=(origen,))
        if destinos is None:
            return 0

        montos = [usd(core, 10, 40, origen.moneda) for _ in range(n)]
        inst = core.nueva_instancia(self.nombre)
        nombre = self.nombre if fraude else f"{self.nombre}_CONTROL"

        # Se aparta la cuenta una ventana completa antes de empezar: así
        # ninguna transferencia normal suya cae dentro de los 10 minutos.
        inicio = core.reloj + ventana
        fin = inicio + timedelta(minutes=8) + ventana
        core.reservar([origen, *destinos], fin)
        agendadas = 0

        # Si no le alcanza, primero recarga (antes de la ventana).
        faltante = sum(montos) - origen.saldo
        if faltante > 0:
            recarga = faltante + usd(core, 50, 100, origen.moneda)
            core.agendar(
                inicio - timedelta(minutes=5),
                lambda fecha: core.transaccion(
                    "RECARGA", recarga, fecha, destino=origen,
                    etiq=etiqueta(nombre, inst, fraude),
                ),
            )
            agendadas += 1

        for i, (destino, monto) in enumerate(zip(destinos, montos)):
            # La transferencia que pasa el umbral es la que dispara la regla.
            dispara = fraude and i == n - 1
            core.agendar(
                inicio + timedelta(minutes=8 * i / (n - 1)),
                lambda fecha, d=destino, m=monto, x=dispara: core.transaccion(
                    "P2P", m, fecha, origen=origen, destino=d,
                    etiq=etiqueta(nombre, inst, fraude, "velocidad" if x else None),
                ),
            )
            agendadas += 1

        return agendadas


class Mula:
    """Recibe de 3 o más remitentes distintos y retira el 80 % o más del
    saldo en menos de 30 minutos.

    Fraude: 3 remitentes y retiro del 90 % a los 20 minutos.
    Control: 2 remitentes y el mismo retiro.
    """

    nombre = "MULE"
    regla = config.REGLAS["mula"]
    max_tx = regla["remitentes"] + 1

    def iniciar(self, core, fraude):
        k = self.regla["remitentes"] - (0 if fraude else 1)
        ventana = timedelta(minutes=self.regla["minutos"])

        mula = core.elegir(core.normales)
        if mula is None:
            return 0
        remitentes = elegir_varias(
            core, core.por_moneda[mula.moneda], k, excluir=(mula,), saldo_min_usd=100
        )
        if remitentes is None:
            return 0

        inst = core.nueva_instancia(self.nombre)
        nombre = self.nombre if fraude else f"{self.nombre}_CONTROL"
        inicio = core.reloj + ventana
        core.reservar([mula, *remitentes], inicio + 2 * ventana)

        for i, remitente in enumerate(remitentes):
            # Entre el 30 % y el 50 % del saldo de cada remitente.
            fraccion = Decimal(str(round(core.rng.uniform(0.3, 0.5), 4)))
            monto = redondear(remitente.saldo * fraccion, mula.moneda)
            core.agendar(
                inicio + timedelta(minutes=2 + 4 * i),
                lambda fecha, r=remitente, m=monto: core.transaccion(
                    "P2P", m, fecha, origen=r, destino=mula,
                    etiq=etiqueta(nombre, inst, fraude),
                ),
            )

        # El retiro se calcula al entregarlo, con el saldo que tenga la
        # mula en ese momento (ya con las transferencias recibidas).
        retiro_pct = Decimal(self.regla["retiro_pct"] + 10) / 100
        core.agendar(
            inicio + timedelta(minutes=20),
            lambda fecha: core.transaccion(
                "RETIRO", redondear(mula.saldo * retiro_pct, mula.moneda), fecha,
                origen=mula,
                etiq=etiqueta(nombre, inst, fraude, "mula" if fraude else None),
            ),
        )
        return k + 1


class Fraccionamiento:
    """3 o más transacciones en 24 horas, cada una bajo el límite diario de
    reporte y que juntas lo pasan.

    Fraude: 3 retiros de USD 3.400 a 3.900 (suman más de 10.000).
    Control: 3 retiros de USD 2.000 a 3.000 (suman menos de 10.000).
    """

    nombre = "SPLITTING"
    regla = config.REGLAS["fraccionamiento"]
    max_tx = regla["transacciones"] + 1

    def iniciar(self, core, fraude):
        cuenta = core.elegir(core.normales)
        if cuenta is None:
            return 0

        limite = self.regla["limite_usd"]
        n = self.regla["transacciones"]
        # Rangos pensados para que, con cualquier redondeo, el fraude siempre
        # pase el límite y el control nunca lo alcance.
        rango = (0.34 * limite, 0.39 * limite) if fraude else (0.20 * limite, 0.30 * limite)
        montos = [usd(core, *rango, cuenta.moneda) for _ in range(n)]

        inst = core.nueva_instancia(self.nombre)
        nombre = self.nombre if fraude else f"{self.nombre}_CONTROL"
        dia = timedelta(hours=self.regla["horas"])

        # Nadie tiene tanto saldo en el seed: primero una recarga, 25 horas
        # antes de los retiros para que quede fuera de su ventana de 24 h.
        inicio = core.reloj + timedelta(minutes=5)
        retiros_desde = inicio + dia + timedelta(hours=1)
        core.reservar([cuenta], retiros_desde + timedelta(hours=7) + dia)

        recarga = sum(montos) + usd(core, 100, 300, cuenta.moneda)
        core.agendar(
            inicio,
            lambda fecha: core.transaccion(
                "RECARGA", recarga, fecha, destino=cuenta,
                etiq=etiqueta(nombre, inst, fraude),
            ),
        )

        for i, (horas, monto) in enumerate(zip((0, 3, 7), montos)):
            dispara = fraude and i == n - 1
            core.agendar(
                retiros_desde + timedelta(hours=horas),
                lambda fecha, m=monto, x=dispara: core.transaccion(
                    "RETIRO", m, fecha, origen=cuenta,
                    etiq=etiqueta(nombre, inst, fraude, "fraccionamiento" if x else None),
                ),
            )
        return n + 1


class TomaCuenta:
    """Cambio de dispositivo + cambio de contraseña + transacción de más de
    USD 200, todo en menos de 1 hora.

    Fraude: la transacción llega 20 minutos después del cambio de dispositivo.
    Control: llega 70 minutos después, fuera de la hora.
    """

    nombre = "ACCOUNT_TAKEOVER"
    regla = config.REGLAS["toma_cuenta"]
    max_tx = 2  # recarga posible + la transacción

    def iniciar(self, core, fraude):
        cuenta = core.elegir(core.normales)
        if cuenta is None:
            return 0

        inst = core.nueva_instancia(self.nombre)
        nombre = self.nombre if fraude else f"{self.nombre}_CONTROL"
        minimo = self.regla["monto_usd"]
        monto = usd(core, minimo * 1.25, minimo * 2, cuenta.moneda)

        # El dispositivo nuevo del atacante: no existe en la base.
        nuevo = uuid.uuid5(NAMESPACE, f"device:takeover:{inst}")

        inicio = core.reloj + timedelta(minutes=5)
        cambio = inicio + timedelta(hours=1)
        espera = timedelta(minutes=20 if fraude else self.regla["minutos"] + 10)
        core.reservar([cuenta], cambio + espera + timedelta(minutes=5))
        agendadas = 0

        if monto > cuenta.saldo:
            recarga = monto - cuenta.saldo + usd(core, 50, 100, cuenta.moneda)
            core.agendar(
                inicio,
                lambda fecha: core.transaccion(
                    "RECARGA", recarga, fecha, destino=cuenta,
                    etiq=etiqueta(nombre, inst, fraude),
                ),
            )
            agendadas += 1

        def cambio_dispositivo(fecha):
            # Desde ahora el core conoce el dispositivo nuevo de la cuenta.
            cuenta.dispositivos.append(nuevo)
            return core.seguridad(
                "DEVICE_CHANGE", cuenta, nuevo, fecha, etiqueta(nombre, inst, fraude)
            )

        core.agendar(cambio, cambio_dispositivo, es_transaccion=False)
        core.agendar(
            cambio + timedelta(minutes=5),
            lambda fecha: core.seguridad(
                "PASSWORD_CHANGE", cuenta, nuevo, fecha, etiqueta(nombre, inst, fraude)
            ),
            es_transaccion=False,
        )
        core.agendar(
            cambio + espera,
            lambda fecha: core.transaccion(
                "RETIRO", monto, fecha, origen=cuenta, dispositivo=nuevo,
                etiq=etiqueta(nombre, inst, fraude, "toma_cuenta" if fraude else None),
            ),
        )
        return agendadas + 1


class ListaRestrictiva:
    """Una transacción de un cliente cuyo documento está en la lista.

    No tiene control: que un documento esté o no en la lista es exacto. El
    caso difícil, el mismo documento escrito en otro formato, ya lo inyecta
    el seed.
    """

    nombre = "RESTRICTED_LIST"
    max_tx = 1

    def iniciar(self, core, fraude):
        cuenta = core.elegir(core.en_lista)
        if cuenta is None:
            return 0

        inst = core.nueva_instancia(self.nombre)
        monto = usd(core, 20, 100, cuenta.moneda)
        etiq = etiqueta(self.nombre, inst, True, "lista_restrictiva")
        fecha = core.reloj + timedelta(minutes=1)
        core.reservar([cuenta], fecha + timedelta(minutes=1))

        comercio = core.rng.choice(core.comercios)

        def accion(f):
            # Sin saldo, recarga; una recarga suya también debe rechazarse.
            if monto > cuenta.saldo:
                return core.transaccion("RECARGA", monto, f, destino=cuenta, etiq=etiq)
            return core.transaccion(
                "QR", monto, f, origen=cuenta, comercio=comercio, etiq=etiq
            )

        core.agendar(fecha, accion)
        return 1


# Orden en que se van arrancando. Cada patrón de fraude va seguido de su
# control, así en una corrida corta aparecen todos.
CICLO = [
    (Velocidad(), True),
    (Velocidad(), False),
    (Mula(), True),
    (Mula(), False),
    (Fraccionamiento(), True),
    (Fraccionamiento(), False),
    (TomaCuenta(), True),
    (TomaCuenta(), False),
    (ListaRestrictiva(), True),
]
