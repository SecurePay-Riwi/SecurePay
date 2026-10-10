import json
import random
from datetime import date
from pathlib import Path

def seleccionar_registros(registros, porcentaje, seed=42):
    """
    Selecciona de forma reproducible un porcentaje de registros.
    """
    if porcentaje <= 0 or not registros:
        return []

    cantidad = round(len(registros) * porcentaje / 100)

    if cantidad == 0:
        return []

    rng = random.Random(seed)

    return rng.sample(registros, cantidad)


def inyectar_defectos_usuarios(registros, porcentaje, seed=42):
    """
    Inyecta diferentes tipos de defectos en los usuarios seleccionados.

    Tipos de defectos:
    - NULL en telefono
    - Formato inválido en email
    - Fecha de nacimiento fuera de rango
    """

    seleccionados = seleccionar_registros(registros, porcentaje, seed)

    defectos = []

    for i, usuario in enumerate(seleccionados):
        tipo = i % 3

        if tipo == 0:
            usuario["telefono"] = None
            defectos.append({
                "id": usuario["id"],
                "tipo": "NULL",
                "campo": "telefono",
            })

        elif tipo == 1:
            usuario["email"] = f"email_invalido_{i}"
            defectos.append({
                "id": usuario["id"],
                "tipo": "INVALID_FORMAT",
                "campo": "email",
            })

        else:
            usuario["fecha_nacimiento"] = date(1800, 1, 1)
            defectos.append({
                "id": usuario["id"],
                "tipo": "OUT_OF_RANGE",
                "campo": "fecha_nacimiento",
            })

    return defectos

def guardar_reporte_defectos(defectos):
    """
    Guarda los defectos generados en un archivo JSON
    para facilitar su inspección y validación.
    """

    ruta = Path("defect_report.json")

    with ruta.open("w", encoding="utf-8") as archivo:
        json.dump(
            defectos,
            archivo,
            indent=4,
            ensure_ascii=False,
            default=str
        )

    return ruta