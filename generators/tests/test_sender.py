import json

from generators.sender import Reporte, SalidaArchivo, carpeta_de_salida


def test_archivo_y_reporte(generar, tmp_path):
    eventos, d = generar(cantidad=200, defectos=(2, 2, 1))
    carpeta = carpeta_de_salida(tmp_path, 0)
    salida, reporte = SalidaArchivo(carpeta), Reporte(carpeta)
    for e in eventos:
        reporte.anotar(e, salida.enviar(e))
    salida.cerrar()
    resumen = reporte.cerrar(d.reporte, {"seed": 42})

    lineas = [json.loads(x) for x in (carpeta / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    etiquetas = (carpeta / "labels.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lineas) == len(etiquetas) == len(eventos)
    assert {x["endpoint"] for x in lineas} <= {"/transactions", "/security-events"}
    # Lo que va al motor no lleva etiquetas.
    assert all("is_fraud" not in x["body"] for x in lineas)

    guardado = json.loads((carpeta / "generation_report.json").read_text(encoding="utf-8"))
    assert guardado == resumen
    assert sum(guardado["events_by_type"].values()) == len(eventos)
