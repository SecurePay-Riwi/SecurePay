import json
import random
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
    Escribe el documento de los usuarios seleccionados en otro formato,
    como llegaría de sistemas distintos. El motor debe normalizarlo
    (dejar solo los dígitos) antes de buscarlo en la lista restrictiva.

    Formatos, a partir del canónico 1000000016:
    - Con puntos: 1.000.000.016
    - Con prefijo del tipo de documento: CC 1000000016
    - Con espacios alrededor: " 1000000016 "
    """

    seleccionados = seleccionar_registros(registros, porcentaje, seed)

    defectos = []

    for i, usuario in enumerate(seleccionados):
        canonico = usuario["documento"]
        tipo = i % 3

        if tipo == 0:
            usuario["documento"] = f"{int(canonico):,}".replace(",", ".")
            formato = "PUNTOS"
        elif tipo == 1:
            usuario["documento"] = f"CC {canonico}"
            formato = "PREFIJO"
        else:
            usuario["documento"] = f" {canonico} "
            formato = "ESPACIOS"

        defectos.append({
            "id": usuario["id"],
            "tipo": formato,
            "campo": "documento",
            "canonico": canonico,
            "valor": usuario["documento"],
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