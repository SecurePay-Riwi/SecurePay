"""Dónde quedan los extractos: carpeta local y, si se pide, la capa raw.

La ruta es la misma en los dos lados, particionada por socio y día:

    <carpeta>/<socio>/fecha=AAAA-MM-DD/<socio>_AAAAMMDD_vN.<ext>
    s3://<bucket>/raw/extractos/<socio>/fecha=AAAA-MM-DD/<mismo nombre>

El día es el del archivo (zona del socio), que es como lo entrega el socio.
"""

import json
import shutil
from pathlib import Path


def ruta_relativa(socio, extracto) -> str:
    return (
        f"{socio.nombre}/fecha={extracto.dia:%Y-%m-%d}/"
        f"{extracto.nombre_archivo(socio.extension)}"
    )


class SalidaLocal:
    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        # Se borra lo de una corrida anterior: con otros porcentajes podrían
        # quedar versiones viejas mezcladas con las nuevas.
        if self.carpeta.exists():
            shutil.rmtree(self.carpeta)
        self.carpeta.mkdir(parents=True)

    def guardar(self, relativa: str, contenido: str):
        ruta = self.carpeta / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n": el mismo archivo byte a byte en Windows y en Linux.
        ruta.write_text(contenido, encoding="utf-8", newline="\n")

    def reporte(self, datos: dict) -> Path:
        ruta = self.carpeta / "extracts_report.json"
        ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
        return ruta


class SalidaS3:
    def __init__(self, bucket: str, prefijo: str):
        # Import aquí: el modo file no necesita boto3 ni LocalStack.
        from shared.aws import cliente

        self.s3 = cliente("s3", read_timeout=10)
        self.bucket = bucket
        self.prefijo = prefijo

    def guardar(self, relativa: str, contenido: str):
        tipo = "text/csv" if relativa.endswith(".csv") else "text/plain"
        self.s3.put_object(
            Bucket=self.bucket,
            Key=f"{self.prefijo}/{relativa}",
            Body=contenido.encode("utf-8"),
            ContentType=f"{tipo}; charset=utf-8",
        )
