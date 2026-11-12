"""Architecture flow on AWS: doc-website/static/img/architecture-flow.jpg.

Labels in Spanish, like the first version of the diagram (the pages say
so under the image). Run from the repository root:

    uv run --group load python doc-website/diagrams/architecture_flow.py

(any environment with Playwright works; the image needs Chromium).
Change it when a service, a flow or the monthly cost changes.
"""

from __future__ import annotations

from pathlib import Path

from common import Card, Svg, legend, panel, render

W, H = 2350, 1210
CW, CH = 280, 66


def x(c: int) -> float:
    return 40 + c * 330


def y(r: int) -> float:
    return 110 + r * 118


def lane(c: int) -> float:
    """Vertical lane between column c and c+1."""
    return x(c) + CW + 25


def gap(r: int) -> float:
    """Horizontal lane between row r and r+1."""
    return y(r) + CH + 26


def card(c, r, title, sub, flow, icon, tag, **kw) -> Card:
    return Card(x(c), y(r), title, sub, flow, icon, tag, w=CW, h=CH, **kw)


s = Svg(W, H)
s.text(40, 44, "PagoSeguro Antifraude · diagrama de flujo de la arquitectura en AWS", size=24, weight="bold")
s.text(40, 68, "Lo construido con Terraform (noviembre de 2026) · el color de cada tarjeta y de cada flecha dice a qué flujo pertenece", size=13, color="#5b6676")
s.box(W - 330, 30, 290, 30, fill="#e3eaf5", stroke="#cdd6e3", rx=15)
s.text(W - 185, 50, "us-east-2 (Ohio) · 2 zonas de disponibilidad", size=12, weight="bold", anchor="middle")

# Column 0: the wallet's entry and the exchange rates.
core = card(0, 0, "Core de la billetera", "Generador del stream\n50 tx/s · pico de 300", "realtime", "external", "TX")
alb = card(0, 2, "Application Load Balancer", "HTTPS 443 · reparte entre 2 zonas", "realtime", "network", "ALB")
rates = card(0, 3, "Amazon DynamoDB", "Tasas de cambio del día", "batch", "database", "DDB")
rates_fn = card(0, 4, "Lambda · tasas de cambio", "Una vez al día (11:00 Bogotá)", "batch", "compute", "λ")
frank = card(0, 5, "API de Frankfurter", "Tasas públicas · 4 monedas", "batch", "external", "FX")

# Column 1: the engine and its cache.
sns_dec = card(1, 1, "Amazon SNS · decisiones", "Copia cada decisión a 3 colas", "async", "integration", "SNS")
engine = card(1, 2, "Fargate · motor de decisión", "4 a 24 tareas · responde en ≤ 200 ms\nSi tarda, decide según el monto", "realtime", "compute", "ECS")
cache = card(1, 3, "ElastiCache Serverless (Valkey)", "Idempotencia, historial, reglas,\ncuentas, comercios y lista", "realtime", "database", "VK")
loader = card(1, 4, "Lambda · carga de lista", "Diaria (01:00 Bogotá): cuentas,\ncomercios y lista restrictiva", "batch", "compute", "λ")

# Column 2: the asynchronous path and the raw layer.
sqs = card(2, 1, "Amazon SQS · 3 colas + DLQ", "Casos · historial · analítica", "async", "integration", "SQS")
consumers = card(2, 2, "Lambda ×3 · consumidores", "Casos e historial en lotes de 10;\nanalítica en lotes de 1.000 o 60 s", "async", "compute", "λ")
raw = card(2, 3, "S3 · capa cruda (raw)", "Decisiones, extractos, Kaggle,\nexport de casos y diferencias", "batch", "storage", "S3")
partners = card(2, 4, "Socios · extractos diarios", "Cada socio deja su archivo en S3\n(en la demo lo sube el apply)", "batch", "external", "TXT")
kaggle = card(2, 5, "Históricos de Kaggle", "PaySim y Sparkov etiquetados", "batch", "external", "CSV")

# Column 3: schedules, alerts, the database and the APIs.
sched = card(3, 0, "EventBridge Scheduler", "5 horarios: conciliación, chequeo,\nalertas, carga de lista, tasas", "batch", "management", "EB")
alerts = card(3, 1, "Lambda · alertas", "Cada 5 min: escala casos de 4 h,\nresumen a cumplimiento, purga", "batch", "compute", "λ")
rds = card(3, 2, "Amazon RDS PostgreSQL", "Usuarios, reglas, casos, historial\n30 días y conciliación · Multi-AZ", "admin", "database", "RDS")
api = card(3, 3, "API Gateway + Lambda", "API de reglas y API de casos\nToken de Cognito (analista/gerente)", "admin", "integration", "API")
people = card(3, 4, "Analistas y gerente de riesgo", "Revisan casos y versionan reglas\n(consolas web de las APIs)", "admin", "external", "👤")
admin = card(3, 5, "Fargate · tarea admin", "Seed de la BD y ETL de Kaggle\n(imagen del seed, en el apply)", "batch", "compute", "ECS")
dbboot = card(3, 6, "Lambda · db-bootstrap", "Crea tablas, usuarios y permisos\n(única con la clave maestra)", "batch", "compute", "λ")

# Column 4: the nightly pipeline.
sfn = card(4, 1, "Step Functions · cada noche", "Extractos → match → diferencias →\nexport → Kaggle → ETL → vistas", "batch", "integration", "SF")
night = card(4, 2, "Lambda ×3 · pasos de la noche", "Lee extractos · guarda diferencias\nexporta RDS → S3 y mide Kaggle", "batch", "compute", "λ")
glue = card(4, 3, "AWS Glue 6.0 · Spark", "Match de conciliación y ETL\nde analítica (2 workers G.1X)", "batch", "analytics", "GL")
curated = card(4, 4, "S3 · capa curada (curated)", "Limpia y tipada · Parquet", "batch", "storage", "S3")
model = card(4, 5, "S3 · capa analítica (analytics)", "Modelo dimensional · 13 tablas\nParticionado por fecha", "analytics", "storage", "S3")

# Columns 5 and 6: notices, evidence and the dashboard.
mails = card(5, 1, "Amazon SNS · correos", "Tesorería (desde la noche), supervisor,\ncumplimiento y alarmas al equipo", "async", "integration", "SNS")
evidence = card(5, 3, "S3 · evidencia de casos", "Object Lock 10 años (COMPLIANCE)\nGlacier Instant Retrieval", "admin", "storage", "S3")
catalog = card(5, 5, "AWS Glue Data Catalog", "Esquema de las tablas\n(desde shared/analytics.py)", "analytics", "analytics", "GL")
athena = card(6, 5, "Amazon Athena", "Vistas q1 a q6 · workgroup powerbi", "analytics", "analytics", "ATH")
pbi = card(6, 6, "Power BI Desktop", "6 páginas · driver ODBC de Athena", "analytics", "external", "BI")

cards = [core, alb, rates, rates_fn, frank, sns_dec, engine, cache, loader, sqs, consumers, raw,
         partners, kaggle, sched, alerts, rds, api, people, admin, dbboot, sfn, night, glue, curated, model,
         mails, evidence, catalog, athena, pbi]

# Real time (orange).
s.arrow([core.bottom(), alb.top()], "realtime", "HTTPS")
s.arrow([alb.right(), engine.left()], "realtime")
s.arrow([engine.bottom(), cache.top()], "realtime", "4 viajes por decisión", both=True)
s.arrow([rates.right(-14), (lane(0), rates.cy - 14), (lane(0), engine.cy + 18), engine.left(18)], "realtime", "tasa del día", at=1, dashed=True, lx=0, ly=8)

# Asynchronous (blue).
s.arrow([engine.top(), sns_dec.bottom()], "async", "publica la decisión")
s.arrow([sns_dec.right(), sqs.left()], "async")
s.arrow([sqs.bottom(), consumers.top()], "async")
s.arrow([consumers.right(-14), rds.left(-14)], "async")
s.arrow([consumers.bottom(), raw.top()], "async", "analítica")

# Batch and the night (green).
s.arrow([sched.bottom(), alerts.top()], "batch", "cada 5 min y 06:30")
s.arrow([sched.right(), (sfn.cx, sched.cy), sfn.top()], "batch", "02:00 Bogotá", at=1, ly=-30)
s.arrow([frank.top(), rates_fn.bottom()], "batch", "trae las tasas")
s.arrow([rates_fn.top(), rates.bottom()], "batch", "guarda")
s.arrow([loader.top(), cache.bottom()], "batch", "reemplaza la lista")
s.arrow([rds.left(18), (lane(2) + 14, rds.cy + 18), (lane(2) + 14, gap(3) + 14), (loader.cx + 60, gap(3) + 14), loader.top(60)], "batch", "lee", at=2, lx=60)
s.arrow([alerts.bottom(), rds.top()], "batch", "escala y purga")
s.arrow([alerts.top(100), (alerts.cx + 100, gap(0)), (mails.cx, gap(0)), mails.top()], "async", "supervisor y cumplimiento", at=1, lx=60)
s.arrow([partners.top(), raw.bottom()], "batch", "suben el archivo")
s.arrow([kaggle.right(), admin.left()], "batch")
s.arrow([admin.right(), (lane(3) + 12, admin.cy), (lane(3) + 12, rds.cy + 18), rds.right(18)], "batch", "seed y Kaggle", at=1, ly=200)
s.arrow([dbboot.right(), (lane(3) + 12, dbboot.cy), (lane(3) + 12, rds.cy + 18), rds.right(18)], "batch")
s.arrow([sfn.bottom(), night.top()], "batch", "invoca")
s.arrow([night.left(-14), rds.right(-14)], "batch", both=True)
s.arrow([sfn.right(), mails.left()], "batch")
s.arrow([sfn.right(18), (lane(4) - 10, sfn.cy + 18), (lane(4) - 10, glue.cy), glue.right()], "batch", "dispara (.sync)", at=1, ly=50)
s.arrow([raw.right(-16), (lane(2) - 6, raw.cy - 16), (lane(2) - 6, gap(2) - 8), (night.cx - 110, gap(2) - 8), night.bottom(-110)], "batch", both=True)
s.arrow([raw.right(-16), (lane(2) - 6, raw.cy - 16), (lane(2) - 6, gap(2) - 8), (lane(3) - 12, gap(2) - 8), (lane(3) - 12, glue.cy - 14), glue.left(-14)], "batch")
s.arrow([glue.bottom(), curated.top()], "batch", "limpia")
s.arrow([curated.bottom(), model.top()], "analytics", "modela")
s.arrow([model.right(), catalog.left()], "analytics")
s.arrow([catalog.right(), athena.left()], "analytics")
s.arrow([athena.bottom(), pbi.top()], "analytics", "al tablero")

# Management (gray).
s.arrow([people.top(), api.bottom()], "admin", "HTTPS + Cognito")
s.arrow([api.top(), rds.bottom()], "admin", "reglas y casos")
s.arrow([api.left(14), (lane(2) + 6, api.cy + 14), (lane(2) + 6, gap(3) - 4), (lane(1) - 6, gap(3) - 4), (lane(1) - 6, cache.cy + 14), cache.right(14)], "admin", "publica el catálogo", at=2)
s.arrow([api.right(14), (lane(3), api.cy + 14), (lane(3), gap(3)), (lane(4), gap(3)), (lane(4), evidence.cy + 14), evidence.left(14)], "admin", "evidencia al resolver", at=2)

for c in cards:
    s.card(c)

# Bottom panels.
py = 960
panel(s, 40, py, 560, 236, "Red y seguridad", [
    ("network", "VPC", "Amazon VPC · 2 zonas", "Subredes públicas, de aplicación y de datos"),
    ("network", "NAT", "NAT Gateway ×2 · endpoints S3 y DynamoDB", "Salida de las subredes privadas, una por zona"),
    ("security", "IAM", "IAM · KMS · Systems Manager", "Un rol por componente, cifrado, claves en Parameter Store"),
    ("security", "COG", "Amazon Cognito", "Inicio de sesión de analistas (analista) y gerente (gerente)"),
])
panel(s, 620, py, 560, 236, "Despliegue y pruebas", [
    ("compute", "ECR", "Amazon ECR", "Imágenes del motor, admin y APIs, tag = commit"),
    ("management", "TF", "Terraform · un solo apply", "Construye, siembra y carga los datos de la demo"),
    ("management", "GH", "GitHub Actions", "CI (lint, pruebas, imagen, Terraform) y Deploy con OIDC"),
    ("compute", "EC2", "EC2 · Locust en la VPC", "Prueba de carga a 50, 150 y 300 tx/s (opcional)"),
])
panel(s, 1200, py, 560, 236, "Observabilidad y costo", [
    ("management", "CW", "CloudWatch", "Logs, dashboard, filtros del log de decisiones"),
    ("management", "AL", "Alarmas → SNS alarmas operativas", "Motor, colas DLQ, conciliación, tasas, analítica"),
    ("management", "CT", "CloudTrail y AWS Budgets", "Auditoría y alerta de gasto (USD 5 en dev)"),
    ("database", "PG", "Un usuario de BD por componente", "Solo db-bootstrap tiene la clave maestra"),
])
legend(s, 1780, py, 530, 236, [
    ("realtime", "Decisión en tiempo real (≤ 200 ms)", False),
    ("async", "Procesamiento asíncrono, después de responder", False),
    ("batch", "Procesos programados y Data Lake", False),
    ("analytics", "Analítica y tablero", False),
    ("admin", "Administración de reglas y casos", False),
    ("realtime", "Punteada: lectura en memoria, no en cada decisión", True),
    ("admin", "El punto marca dónde nace la flecha", False),
], "≈ $346 al mes en producción · ≈ $17 en desarrollo")

if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "static" / "img" / "architecture-flow.jpg"
    render(s.svg(), out)
    print(out)
