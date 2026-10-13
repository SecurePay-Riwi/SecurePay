"""Fechas al azar que salen iguales en cualquier sistema operativo.

No se le piden a Faker: en Windows sortea segundos enteros y en Linux
segundos con decimales, así que con la misma semilla da fechas distintas
y desde ahí se corre todo el azar del seed. Aquí siempre se sortean
segundos (o días) enteros.
"""

from datetime import timedelta, timezone


def _sin_zona(fecha):
    # Las columnas guardan la hora UTC sin zona horaria.
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


def fecha_hora_entre(rng, desde, hasta):
    """Fecha y hora al azar entre dos fechas, con segundos enteros."""
    desde, hasta = _sin_zona(desde), _sin_zona(hasta)
    segundos = int((hasta - desde).total_seconds())
    return desde + timedelta(seconds=rng.randint(0, segundos))


def fecha_entre(rng, desde, hasta):
    """Día al azar entre dos fechas (sin hora), incluidas las dos."""
    return desde + timedelta(days=rng.randint(0, (hasta - desde).days))
