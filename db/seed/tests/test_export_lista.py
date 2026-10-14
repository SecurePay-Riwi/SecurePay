"""Pruebas del archivo que el seed exporta para el servicio de listas.

No necesitan PostgreSQL: usan filas armadas a mano con los mismos
atributos que la tabla listas_restrictivas.
"""

import json
from datetime import date
from types import SimpleNamespace

from db.seed.export_lista import a_jsonl, guardar_local


def fila(documento, tipo, fecha):
    return SimpleNamespace(documento=documento, tipo=tipo, fecha_inclusion=fecha)


def test_una_persona_por_linea_ordenada_por_documento():
    filas = [
        fila("1000000016", "sanciones", date(2023, 4, 11)),
        fila("10000005", "PEP", date(2022, 1, 30)),
    ]

    lineas = a_jsonl(filas).splitlines()

    assert [json.loads(l) for l in lineas] == [
        {"documento": "1000000016", "tipo": "sanciones", "fecha_inclusion": "2023-04-11"},
        {"documento": "10000005", "tipo": "PEP", "fecha_inclusion": "2022-01-30"},
    ]


def test_mismo_archivo_sin_importar_el_orden_de_la_base(tmp_path):
    filas = [fila("2", "PEP", date(2024, 1, 1)), fila("1", "PEP", date(2024, 1, 1))]
    a = guardar_local(a_jsonl(filas), tmp_path / "a.jsonl").read_bytes()
    b = guardar_local(a_jsonl(filas[::-1]), tmp_path / "b.jsonl").read_bytes()
    assert a == b
    assert b"\r\n" not in a


def test_lista_vacia():
    assert a_jsonl([]) == ""
