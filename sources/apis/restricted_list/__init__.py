"""Servicio simulado del proveedor de listas restrictivas.

Hace de tercero: responde lento y a veces se cae, a propósito, para que
el motor tenga que defenderse (caché, circuit breaker y decisión por
defecto). Ver la bitácora 3.10 y 3.12.

Se levanta con:

    uv run uvicorn sources.apis.restricted_list.main:app --port 8001
"""
