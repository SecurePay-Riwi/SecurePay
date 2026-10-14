"""Punto de entrada del generador de transacciones.

    uv run python -m generators

Lee la base una vez, genera el tráfico con fraude y defectos, y lo manda
al motor (GEN_OUTPUT=http) o lo escribe en un archivo (GEN_OUTPUT=file).
En los dos modos queda generated/instance-N/events.jsonl, que es de donde
leen los extractos de los socios.
"""

from generators import config
from generators.catalog import cargar
from generators.core import Core
from generators.defects import Defectos
from generators.money import cargar_tasas
from generators.patterns import CICLO
from generators.sender import Reporte, SalidaArchivo, SalidaHttp, carpeta_de_salida
from shared.db import engine


def main():
    config.validar()
    volumen = config.VOLUMES[config.MODE]
    instancia = config.INSTANCE_INDEX

    print(f"Modo: {config.MODE} · salida: {config.OUTPUT} · instancia {instancia + 1} de {config.INSTANCE_COUNT}")
    print("Cargando catálogo...")
    catalogo = cargar(
        engine,
        config.SEED,
        volumen["max_accounts"],
        instancia,
        config.INSTANCE_COUNT,
    )

    core = Core(
        catalogo,
        cargar_tasas(),
        volumen["transactions"],
        config.FRAUD_PERCENTAGE,
        config.SEED,
        config.FECHA_REFERENCIA,
        config.TX_PER_ACCOUNT_DAY,
        instancia,
    )
    core.patrones = CICLO
    defectos = Defectos(
        config.SEED,
        config.DUPLICATE_PERCENTAGE,
        config.OUT_OF_ORDER_PERCENTAGE,
        config.DECIMAL_DEFECT_PERCENTAGE,
    )

    carpeta = carpeta_de_salida(config.OUTPUT_DIR, instancia)
    # El archivo se escribe siempre: con GEN_OUTPUT=http queda además como
    # registro de lo que se mandó, y los extractos de los socios lo leen.
    archivo = SalidaArchivo(carpeta)
    http = None
    if config.OUTPUT == "http":
        http = SalidaHttp(config.ENGINE_URL, config.RATE_PER_SECOND)
    reporte = Reporte(carpeta)

    print(f"Generando {volumen['transactions']} transacciones...")
    enviados = 0
    try:
        for evento in defectos.aplicar(core.eventos()):
            resultado = http.enviar(evento) if http else None
            archivo.enviar(evento)
            reporte.anotar(evento, resultado)
            enviados += 1
            if enviados % 1_000 == 0:
                print(f"  {enviados} eventos enviados")
    finally:
        # Aunque se corte a la mitad (Ctrl+C), queda el reporte de lo enviado.
        archivo.cerrar()
        if http:
            http.cerrar()
        resumen = reporte.cerrar(
            defectos.reporte,
            {
                "seed": config.SEED,
                "mode": config.MODE,
                "transactions": volumen["transactions"],
                "fraud_percentage": config.FRAUD_PERCENTAGE,
                "instance": f"{instancia + 1}/{config.INSTANCE_COUNT}",
                "events_sent": enviados,
            },
        )

    print()
    print(f"Listo: {enviados} eventos. Archivos en {carpeta}")
    print(f"  Por patrón: {resumen['events_by_pattern']}")
    print(f"  Defectos: {resumen['defects_by_type']}")
    if resumen["responses_by_status"]:
        print(f"  Respuestas del motor: {resumen['responses_by_status']}")


if __name__ == "__main__":
    main()
